from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.middlewares.auth import current_user, can_write
from src.models import Dataset, DatasetVersion
from src.schemas.dataset import DatasetInput
from src.schemas.simulation import SourceDatasetInput, SyncStart, SyncModeInput
from src.services import datasets, sync
from src.services.audit import record
from src.utils.serialization import dataset_dict, dataset_version_dict
router = APIRouter(prefix='/datasets')


def _detail(db, d):
    return {**dataset_dict(d, sync.dataset_view(db, d)), 'records': d.records}


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [dataset_dict(d, sync.dataset_view(db, d)) for d in db.scalars(select(Dataset).order_by(Dataset.id.desc()))]


@router.post('', status_code=201)
def create(data: DatasetInput, db=Depends(get_db), u=Depends(can_write)):
    d = datasets.create(db, data)
    record(db, u.email, 'dataset.create', {'id': d.id, 'rows': len(d.records), 'version_id': d.current_version_id})
    db.commit()
    return _detail(db, d)


@router.post('/source', status_code=201)
def create_from_source(data: SourceDatasetInput, db=Depends(get_db), u=Depends(can_write)):
    d = datasets.create_source(db, data)
    record(db, u.email, 'dataset.source_link', {'id': d.id, 'source_id': d.source_id})
    db.commit()
    return _detail(db, d)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    d = db.get(Dataset, id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    return _detail(db, d)


@router.get('/{id}/versions')
def versions(id: int, db=Depends(get_db), u=Depends(current_user)):
    d = db.get(Dataset, id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    rows = db.scalars(select(DatasetVersion).where(DatasetVersion.dataset_id == id)
                      .order_by(DatasetVersion.version.desc()))
    return [dataset_version_dict(v) for v in rows]


@router.get('/{id}/versions/{version_id}')
def version_detail(id: int, version_id: int, db=Depends(get_db), u=Depends(current_user)):
    v = db.get(DatasetVersion, version_id)
    if not v or v.dataset_id != id:
        raise HTTPException(404, '批次版本不存在')
    if v.published_at is None and v.status not in ('needs_rebuild',):
        raise HTTPException(409, '该版本尚未发布，不能作为分析依据')
    return {**dataset_version_dict(v), 'records': v.records}


@router.get('/{id}/verify')
def verify(id: int, version_id: int | None = None, db=Depends(get_db), u=Depends(current_user)):
    d = db.get(Dataset, id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    return sync.verify(db, d, version_id)


def _run(db, dataset_id, actor, mode='auto', max_pages=None, resume=False):
    if resume:
        outcome = sync.resume(db, dataset_id, actor, max_pages)
    else:
        requested = None if mode == 'auto' else mode
        outcome = sync.advance(db, dataset_id, actor, max_pages, requested)
    version = outcome['version']
    payload = {'version': dataset_version_dict(version), 'unchanged': outcome['unchanged'],
               'interrupted': outcome['interrupted'], 'dataset': _detail(db, db.get(Dataset, dataset_id))}
    return payload


@router.post('/{id}/sync')
def start_sync(id: int, data: SyncStart, db=Depends(get_db), u=Depends(can_write)):
    d = db.get(Dataset, id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    if d.mode != 'source':
        raise HTTPException(409, '人工导入批次不支持源端追平；请创建模拟源接入批次')
    payload = _run(db, id, u.email, mode='auto', max_pages=data.max_pages)
    v = payload['version']
    record(db, u.email, 'dataset.sync', {'id': id, 'version': v['version'], 'status': v['status'],
                                         'mode': v['sync_mode'], 'source_position': v['source_position']})
    db.commit()
    return payload


@router.post('/{id}/sync/resume')
def resume_sync(id: int, data: SyncStart, db=Depends(get_db), u=Depends(can_write)):
    d = db.get(Dataset, id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    if d.mode != 'source':
        raise HTTPException(409, '人工导入批次不支持源端追平；请创建模拟源接入批次')
    payload = _run(db, id, u.email, max_pages=data.max_pages, resume=True)
    v = payload['version']
    record(db, u.email, 'dataset.sync.resume', {'id': id, 'version': v['version'], 'status': v['status'],
                                                'source_position': v['source_position'], 'pages': v['pages']})
    db.commit()
    return payload


@router.post('/{id}/sync/{mode}')
def start_sync_mode(id: int, mode: str, data: SyncModeInput, db=Depends(get_db), u=Depends(can_write)):
    if mode not in ('full', 'incremental'):
        raise HTTPException(422, '仅支持 full 或 incremental 同步')
    d = db.get(Dataset, id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    if d.mode != 'source':
        raise HTTPException(409, '人工导入批次不支持源端追平；请创建模拟源接入批次')
    payload = _run(db, id, u.email, mode=mode, max_pages=data.max_pages)
    v = payload['version']
    record(db, u.email, 'dataset.sync', {'id': id, 'version': v['version'], 'status': v['status'],
                                         'mode': v['sync_mode'], 'requested': mode})
    db.commit()
    return payload
