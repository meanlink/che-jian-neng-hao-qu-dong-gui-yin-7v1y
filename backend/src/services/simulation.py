"""Independent simulated upstream ledger with a durable change feed.

The ledger keeps accepting writes at any time. Readers page a snapshot and then
replay the change log, so changes made while a batch is being read are neither
lost nor read twice.
"""
import time
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from src.models import SimulatedSource
from src.models.source_change import SourceChange
from src.services.business import seed_records

SOURCE_NAME = '澄川冲压一线 · 模拟源'


def _row(record, seq, deleted=False):
    return {'_key': str(record['day']), '_seq': seq, '_deleted': deleted, 'record': record}


def _find(source, key):
    for row in source.records:
        if row['_key'] == key:
            return row
    return None


def create(db, name, label='', records=None, page_size=25, latency_ms=0, token_seconds=3600):
    name = name.strip()
    if len(name) < 2:
        raise HTTPException(422, '模拟源名称至少需要两个字符')
    if db.scalar(select(SimulatedSource).where(SimulatedSource.name == name)):
        raise HTTPException(409, '该模拟源名称已存在')
    rows = []
    seq = 0
    for record in records if records is not None else seed_records():
        seq += 1
        rows.append(_row(record, seq))
    now = time.time()
    source = SimulatedSource(name=name, label=label or '可随时写入的独立模拟台账', records=rows, seq=seq,
                             page_size=max(1, min(int(page_size), 200)), latency_ms=max(0, min(int(latency_ms), 500)),
                             token_seconds=max(1, int(token_seconds)), token_expires_at=now + max(1, int(token_seconds)),
                             created_at=now, updated_at=now)
    db.add(source)
    db.flush()
    return source


def ensure_demo(db):
    if db.scalar(select(SimulatedSource).where(SimulatedSource.name == SOURCE_NAME)):
        return
    create(db, SOURCE_NAME, '独立模拟源：翻页期间仍可写入、可撤销样本、可模拟中断', page_size=25, latency_ms=0, token_seconds=3600)


def _source(db, source_id):
    source = db.get(SimulatedSource, source_id, with_for_update=True)
    if not source:
        raise HTTPException(404, '模拟源不存在')
    return source


def visible(source):
    return [dict(row['record']) for row in source.records if not row['_deleted']]


def summary(source):
    rows = [row for row in source.records if not row['_deleted']]
    return {
        'id': source.id, 'name': source.name, 'label': source.label,
        'rows': len(rows), 'seq': source.seq, 'page_size': source.page_size,
        'latency_ms': source.latency_ms,
        'token_expires_at': source.token_expires_at,
        'token_valid': source.token_expires_at > time.time(),
        'token_seconds': source.token_seconds, 'token_no': source.token_no,
        'fail_at_page': source.fail_at_page, 'fail_at_seq': source.fail_at_seq,
        'updated_at': source.updated_at,
    }


def sample(source, limit=30):
    rows = sorted(visible(source), key=lambda r: str(r.get('day', '')))
    return rows[:limit]


def page(source, cursor, snapshot_seq):
    """Keyset page of current rows ordered by business day.

    Rows are read in their live state; every change after ``snapshot_seq`` is
    replayed from the change log before publishing, so a mid-page update or
    deletion is neither lost nor applied twice.
    """
    rows = [dict(row['record']) for row in source.records
            if not row['_deleted'] and (not cursor or str(row['_key']) > cursor)]
    rows.sort(key=lambda r: str(r.get('day', '')))
    chunk = rows[:source.page_size]
    more = len(rows) > source.page_size
    next_cursor = str(chunk[-1].get('day', '')) if chunk else (cursor or '')
    return chunk, next_cursor, more


def config(db, source_id, payload):
    source = _source(db, source_id)
    if 'page_size' in payload:
        source.page_size = max(1, min(int(payload['page_size']), 200))
    if 'latency_ms' in payload:
        source.latency_ms = max(0, min(int(payload['latency_ms']), 500))
    if 'token_seconds' in payload:
        source.token_seconds = max(1, min(int(payload['token_seconds']), 86400))
    if 'fail_at_page' in payload:
        value = payload['fail_at_page']
        source.fail_at_page = None if value in (None, '', 0) else max(1, int(value))
    if 'fail_at_seq' in payload:
        value = payload['fail_at_seq']
        source.fail_at_seq = None if value in (None, '', 0) else max(1, int(value))
    source.updated_at = time.time()
    return source


def expire_token(db, source_id):
    source = _source(db, source_id)
    source.token_expires_at = time.time() - 1
    source.updated_at = time.time()
    return source


def renew_token(source):
    source.token_no += 1
    source.token_expires_at = time.time() + source.token_seconds
    source.updated_at = time.time()


def apply_ops(db, source_id, ops):
    """Apply upserts/deletes, assigning each one the next source position."""
    source = _source(db, source_id)
    if not isinstance(ops, list) or not ops:
        raise HTTPException(422, '请至少提供一条变更')
    applied = []
    for op in ops:
        action = op.get('action')
        if action == 'upsert':
            record = dict(op.get('record') or {})
            key = str(record.get('day', '')).strip()
            if not key:
                raise HTTPException(422, '新增或修改样本必须包含日期')
            existing = _find(source, key)
            if existing:
                merged = {**existing['record'], **record}
            else:
                from src.services.business import metadata
                merged = {c['key']: record.get(c['key'], '') for c in metadata()['columns']}
            from src.services import records as record_service
            record_service.validate([merged])
            source.seq += 1
            if existing:
                existing['record'] = merged
                existing['_seq'] = source.seq
                existing['_deleted'] = False
            else:
                row = _row(merged, source.seq)
                source.records.append(row)
            db.add(SourceChange(source_id=source.id, seq=source.seq, key=key, deleted=False, record=merged))
            applied.append({'action': 'upsert', 'key': key, 'seq': source.seq})
        elif action == 'delete':
            key = str(op.get('key', '')).strip()
            existing = _find(source, key)
            if not existing or existing['_deleted']:
                raise HTTPException(422, f'样本 {key or "（空）"} 不存在或已撤销')
            source.seq += 1
            existing['_deleted'] = True
            existing['_seq'] = source.seq
            db.add(SourceChange(source_id=source.id, seq=source.seq, key=key, deleted=True, record={}))
            applied.append({'action': 'delete', 'key': key, 'seq': source.seq})
        else:
            raise HTTPException(422, '变更动作仅支持 upsert 或 delete')
    source.updated_at = time.time()
    flag_modified(source, 'records')
    return source, applied


def changes(db, source_id, after, limit=500):
    return list(db.scalars(select(SourceChange).where(SourceChange.source_id == source_id, SourceChange.seq > after)
                           .order_by(SourceChange.seq).limit(limit)))
