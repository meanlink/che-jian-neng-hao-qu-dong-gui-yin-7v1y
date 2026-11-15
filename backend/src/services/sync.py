"""Paged full read plus change-log catch-up, producing attributable batch versions.

Guarantees:
- writes at the source during paging are replayed from the change log before publish;
- interrupted runs resume from the stored page cursor / source position on the same
  in-flight version, so a retry never mints a duplicate batch;
- an expired incremental credential forces a full rebuild while the old published
  version keeps serving jobs until the new one is complete;
- publishing swaps the dataset's readable version in one commit, and jobs pin the
  version they were created against.
"""
import time
from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from src.constants.enums import SyncStatus, SyncMode
from src.models import Dataset, DatasetVersion, SimulatedSource
from src.services import simulation
from src.services.records import business
from src.utils.serialization import checksum

ACTIVE = (SyncStatus.full_in_progress.value, SyncStatus.catching_up.value)


class SourceInterrupted(Exception):
    pass


def _lock_dataset(db, dataset_id):
    return db.get(Dataset, dataset_id, with_for_update=True)


def _source(db, dataset):
    if not dataset.source_id:
        raise HTTPException(409, '该批次未绑定模拟源')
    source = db.get(SimulatedSource, dataset.source_id, with_for_update=True)
    if not source:
        raise HTTPException(409, '模拟源已不存在')
    return source


def _active(db, dataset):
    dataset_id = dataset.id if isinstance(dataset, Dataset) else dataset
    return db.scalar(select(DatasetVersion).where(
        DatasetVersion.dataset_id == dataset_id,
        DatasetVersion.published_at.is_(None),
        DatasetVersion.status.in_(ACTIVE),
    ).order_by(DatasetVersion.id.desc()))


def _pending_rebuild(db, dataset_id):
    return db.scalar(select(DatasetVersion).where(
        DatasetVersion.dataset_id == dataset_id,
        DatasetVersion.published_at.is_(None),
        DatasetVersion.status == SyncStatus.needs_rebuild.value,
    ).order_by(DatasetVersion.id.desc()))


def _published(db, dataset):
    return db.get(DatasetVersion, dataset.current_version_id) if dataset.current_version_id else None


def _next_number(db, dataset_id):
    return int(db.scalar(select(func.max(DatasetVersion.version)).where(DatasetVersion.dataset_id == dataset_id)) or 0) + 1


def _token_ok(source, version):
    return version.token_id is not None and source.token_no == version.token_id and source.token_expires_at > time.time()


def _renew_if_expired(source):
    if source.token_expires_at <= time.time():
        simulation.renew_token(source)
    return source.token_no


def _mark_rebuild(db, version, reason):
    version.status = SyncStatus.needs_rebuild.value
    version.active_slot = None
    version.error = reason[:990]
    version.updated_at = time.time()
    db.commit()


def _rebuild_marker(db, dataset, source, published, actor, pending):
    if pending:
        return pending
    now = time.time()
    version = DatasetVersion(
        dataset_id=dataset.id, version=_next_number(db, dataset.id),
        status=SyncStatus.needs_rebuild.value, sync_mode=SyncMode.full.value,
        records=[], base_version_id=published.id if published else None,
        snapshot_seq=source.seq, source_position=published.source_position if published else 0,
        target_seq=source.seq, token_id=source.token_no, actor=actor,
        error='增量接入凭据已过期，必须从全量重建；旧版保持可用。',
        rebuild_reason='增量凭据已过期，需全量重建后才能追平；旧版在重建齐全前继续可用。',
        created_at=now, updated_at=now,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = _pending_rebuild(db, dataset.id)
        if existing:
            return existing
        raise HTTPException(409, '并发同步发生冲突，请刷新后重试') from None
    db.commit()
    return version


def _reset_for_full(db, source, version):
    """Restart a pending version in place as a full read with a fresh credential."""
    version.sync_mode = SyncMode.full.value
    version.status = SyncStatus.full_in_progress.value
    version.records = []
    version.row_count = 0
    version.pages = 0
    version.page_cursor = ''
    version.upserts = 0
    version.deletes = 0
    version.snapshot_seq = source.seq
    version.source_position = source.seq
    version.target_seq = 0
    version.token_id = _renew_if_expired(source)
    version.error = ''
    version.rebuild_reason = '凭据过期后的全量重建；旧版在全量齐全前继续可用。'
    version.updated_at = time.time()
    version.active_slot = version.dataset_id
    db.commit()
    return version


def begin(db, dataset_id, actor, requested_mode=None):
    """Create, revive or return the single in-flight version for a dataset."""
    dataset = _lock_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(404, '数据批次不存在')
    if dataset.mode != 'source':
        raise HTTPException(409, '该批次为人工导入批次，请先建立模拟源接入批次')
    source = _source(db, dataset)
    active = _active(db, dataset)
    if active:
        return dataset, source, active, False

    published = _published(db, dataset)
    pending = _pending_rebuild(db, dataset.id)
    if requested_mode == SyncMode.incremental.value and published is not None and not _token_ok(source, published):
        # An explicit incremental run with an expired credential only records the
        # required rebuild; nothing is published until a complete full read exists.
        return dataset, source, _rebuild_marker(db, dataset, source, published, actor, pending), False
    incremental = (requested_mode is None or requested_mode == SyncMode.incremental.value) \
        and published is not None and _token_ok(source, published)
    if incremental and source.seq == published.source_position:
        return dataset, source, published, True
    if not incremental and pending:
        return dataset, source, _reset_for_full(db, source, pending), False

    mode = SyncMode.incremental.value if incremental else SyncMode.full.value
    now = time.time()
    version = DatasetVersion(
        dataset_id=dataset.id, version=_next_number(db, dataset.id),
        status=SyncStatus.catching_up.value if incremental else SyncStatus.full_in_progress.value,
        sync_mode=mode, records=list(published.records) if incremental else [],
        base_version_id=published.id if published else None,
        snapshot_seq=published.source_position if incremental else source.seq,
        source_position=published.source_position if incremental else source.seq,
        target_seq=source.seq if incremental else 0,
        token_id=_renew_if_expired(source) if not incremental else source.token_no,
        actor=actor, created_at=now, updated_at=now,
        active_slot=dataset.id,
        rebuild_reason=('增量凭据已过期，本次改为全量重建；旧版在全量齐全前继续可用。'
                        if not incremental and published is not None else ''),
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError:
        # Another sync won the single in-flight slot; join it instead of duplicating.
        db.rollback()
        dataset = _lock_dataset(db, dataset_id)
        active = _active(db, dataset)
        if not active:
            raise HTTPException(409, '并发同步发生冲突，请刷新后重试') from None
        return dataset, _source(db, dataset), active, False
    version.row_count = len(version.records)
    db.commit()
    return dataset, source, version, False


def _fetch_page(db, source, version):
    page_no = version.pages + 1
    if source.latency_ms:
        time.sleep(source.latency_ms / 1000)
    if source.fail_at_page == page_no:
        source.fail_at_page = None  # one-shot fault so the retry can proceed
        db.commit()
        raise SourceInterrupted(f'模拟源在第 {page_no} 页中断；已保存 {version.pages} 页与游标“{version.page_cursor or "首页"}”，重试将从源端位置继续。')
    return simulation.page(source, version.page_cursor, version.snapshot_seq)


def _advance_full(db, source, version, max_pages):
    # On a resumed run keep the already-read pages; on a fresh run the snapshot position
    # is the boundary: every later write is replayed from the change log.
    current = {row['day']: row for row in version.records}
    read = 0
    while True:
        if max_pages is not None and read >= max_pages:
            return False
        if not _token_ok(source, version):
            _mark_rebuild(db, version, '全量读取期间接入凭据已失效，需重建全量；旧版保持可用。')
            return True
        rows, cursor, more = _fetch_page(db, source, version)
        for row in rows:
            current[row['day']] = row
        version.page_cursor = cursor
        version.pages += 1
        version.records = sorted(current.values(), key=lambda row: str(row.get('day', '')))
        version.row_count = len(version.records)
        version.updated_at = time.time()
        read += 1
        db.commit()
        if not more:
            version.status = SyncStatus.catching_up.value
            version.target_seq = source.seq
            version.page_cursor = ''
            version.updated_at = time.time()
            db.commit()
            return True


def _fire_fault(db, source, seq):
    if source.fail_at_seq == seq:
        source.fail_at_seq = None
        db.commit()
        raise SourceInterrupted(f'模拟源在变更位置 {seq} 中断；已追平至位置 {seq - 1}，重试将按源端位置继续。')


def _apply(current, change):
    if change.deleted:
        current.pop(change.key, None)
        return 'delete'
    current[change.key] = dict(change.record)
    return 'upsert'


def _advance_catch_up(db, source, version):
    current = {row['day']: row for row in version.records}
    while version.source_position < version.target_seq:
        batch = simulation.changes(db, source.id, version.source_position, limit=200)
        batch = [change for change in batch if change.seq <= version.target_seq]
        if not batch:
            # Positions without logged changes predate the change feed; align rather than stall.
            version.source_position = version.target_seq
            break
        for change in batch:
            if not _token_ok(source, version):
                _mark_rebuild(db, version, '追平期间接入凭据已失效，需重建全量；旧版保持可用。')
                return True
            _fire_fault(db, source, change.seq)
            action = _apply(current, change)
            version.source_position = change.seq
            if action == 'delete':
                version.deletes += 1
            else:
                version.upserts += 1
            # Position and records move together: an interruption can never leave a
            # recorded position ahead of the rows actually stored.
            version.records = sorted(current.values(), key=lambda row: str(row.get('day', '')))
            version.row_count = len(version.records)
            version.updated_at = time.time()
            db.commit()
    return False


def _publish(db, dataset, version):
    dataset = _lock_dataset(db, dataset.id)
    if dataset.current_version_id != version.base_version_id:
        _mark_rebuild(db, version, '发布前已有并发批次切换，本批次保留为待重建，不覆盖新版本。')
        return version
    records = business(version.records)
    digest = checksum(records)
    now = time.time()
    version.records = records
    version.row_count = len(records)
    version.checksum = digest
    version.status = SyncStatus.synced.value
    version.published_at = now
    version.updated_at = now
    version.source_position = version.target_seq
    version.active_slot = None
    if dataset.current_version_id:
        previous = db.get(DatasetVersion, dataset.current_version_id)
        if previous:
            previous.superseded_at = now
    dataset.current_version_id = version.id
    dataset.records = records
    dataset.checksum = digest
    db.commit()
    return version


def advance(db, dataset_id, actor, max_pages=None, requested_mode=None):
    """Run up to max_pages full pages, then catch up and publish when complete."""
    dataset, source, version, unchanged = begin(db, dataset_id, actor, requested_mode)
    if unchanged:
        return {'version': version, 'unchanged': True, 'interrupted': None}
    if version.status == SyncStatus.needs_rebuild.value:
        return {'version': version, 'unchanged': False, 'interrupted': None}
    interrupted = None
    try:
        if version.status == SyncStatus.full_in_progress.value:
            if not _advance_full(db, source, version, max_pages):
                return {'version': version, 'unchanged': False, 'interrupted': None}
            if version.status == SyncStatus.needs_rebuild.value:
                return {'version': version, 'unchanged': False, 'interrupted': None}
        if version.status == SyncStatus.catching_up.value:
            if not _token_ok(source, version):
                _mark_rebuild(db, version, '接入凭据已失效，需重建全量；旧版保持可用。')
                return {'version': version, 'unchanged': False, 'interrupted': None}
            if _advance_catch_up(db, source, version):
                return {'version': version, 'unchanged': False, 'interrupted': None}
            version = _publish(db, dataset, version)
    except SourceInterrupted as error:
        interrupted = str(error)
    return {'version': version, 'unchanged': False, 'interrupted': interrupted}


def resume(db, dataset_id, actor, max_pages=None):
    """Resume the single in-flight version; never creates a second batch for a retry."""
    dataset = _lock_dataset(db, dataset_id)
    if not dataset:
        raise HTTPException(404, '数据批次不存在')
    if dataset.mode != 'source':
        raise HTTPException(409, '人工导入批次不支持源端追平；请创建模拟源接入批次')
    return advance(db, dataset_id, actor, max_pages)


def verify(db, dataset, version_id=None):
    """Compare a published version with the current source so intake results are checkable."""
    version = db.get(DatasetVersion, version_id) if version_id else _published(db, dataset)
    if not version:
        raise HTTPException(404, '该批次尚无已发布版本')
    if version.dataset_id != dataset.id:
        raise HTTPException(404, '批次版本不属于该批次')
    source = db.get(SimulatedSource, dataset.source_id) if dataset.source_id else None
    if not source:
        raise HTTPException(409, '该批次未绑定模拟源')
    live = {str(row['record']['day']): row['record'] for row in source.records if not row['_deleted']}
    taken = {str(row['day']): row for row in version.records}
    missing = sorted(set(live) - set(taken))
    extra = sorted(set(taken) - set(live))
    changed = sorted(key for key in set(live) & set(taken) if live[key] != taken[key])
    return {
        'dataset_id': dataset.id, 'version': version.version, 'version_id': version.id,
        'source_rows': len(live), 'version_rows': len(taken),
        'missing': missing[:50], 'extra': extra[:50], 'changed': changed[:50],
        'missing_total': len(missing), 'extra_total': len(extra), 'changed_total': len(changed),
        'source_position': version.source_position, 'source_head': source.seq,
        'clean': not missing and not extra and not changed,
    }


def dataset_view(db, dataset):
    """Status, source position and version lineage for the UI."""
    published = _published(db, dataset)
    active = _active(db, dataset)
    pending = _pending_rebuild(db, dataset.id)
    latest = db.scalar(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
                       .order_by(DatasetVersion.version.desc()))
    source = db.get(SimulatedSource, dataset.source_id) if dataset.source_id else None
    token_valid = bool(source and source.token_expires_at > time.time())
    if dataset.mode != 'source':
        state = 'manual'
    elif active:
        state = active.status
    elif pending:
        state = SyncStatus.needs_rebuild.value
    elif published and not token_valid:
        state = SyncStatus.needs_rebuild.value
    elif published:
        state = published.status
    else:
        state = 'not_started'
    position = active.source_position if active else (published.source_position if published else 0)
    head = active or pending or latest
    return {
        'sync_status': state,
        'source_position': position,
        'source_head': source.seq if source else 0,
        'lag': (source.seq - position) if source else 0,
        'current_version': published.version if published else None,
        'current_version_id': published.id if published else None,
        'current_version_superseded': bool(published and published.superseded_at),
        'active_version': active.version if active else None,
        'active_version_id': active.id if active else None,
        'pending_version': pending.version if pending else None,
        'pending_version_id': pending.id if pending else None,
        'last_error': (head.error if head else '') or '',
        'rebuild_reason': (head.rebuild_reason if head else '') or '',
        'token_valid': token_valid,
        'token_id': source.token_no if source else None,
        'source_name': source.name if source else '',
        'source_id': source.id if source else None,
        'ready': published is not None,
    }
