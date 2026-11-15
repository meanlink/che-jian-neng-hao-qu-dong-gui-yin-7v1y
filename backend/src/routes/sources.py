from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.middlewares.auth import current_user, can_write
from src.models import Dataset, SimulatedSource
from src.schemas.simulation import SourceInput, SourceConfig, OpsInput
from src.services import simulation, sync
from src.services.audit import record
from src.utils.serialization import dataset_dict
router = APIRouter(prefix='/sources')


def _view(db, source):
    base = simulation.summary(source)
    linked = [dataset_dict(d, sync.dataset_view(db, d)) for d in
              db.scalars(select(Dataset).where(Dataset.source_id == source.id).order_by(Dataset.id))]
    return {**base, 'sample': simulation.sample(source), 'datasets': linked}


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [_view(db, s) for s in db.scalars(select(SimulatedSource).order_by(SimulatedSource.id))]


@router.post('', status_code=201)
def create(data: SourceInput, db=Depends(get_db), u=Depends(can_write)):
    s = simulation.create(db, data.name, data.label, page_size=data.page_size,
                          latency_ms=data.latency_ms, token_seconds=data.token_seconds)
    record(db, u.email, 'source.create', {'id': s.id, 'rows': len(simulation.visible(s))})
    db.commit()
    return _view(db, s)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    s = db.get(SimulatedSource, id)
    if not s:
        raise HTTPException(404, '模拟源不存在')
    return _view(db, s)


@router.patch('/{id}')
def config(id: int, data: SourceConfig, db=Depends(get_db), u=Depends(can_write)):
    try:
        s = simulation.config(db, id, data.model_dump(exclude_unset=True))
    except (TypeError, ValueError):
        raise HTTPException(422, '模拟源参数不合法') from None
    record(db, u.email, 'source.config', {'id': id, 'config': data.model_dump(exclude_unset=True)})
    db.commit()
    return _view(db, s)


@router.post('/{id}/expire-token')
def expire(id: int, db=Depends(get_db), u=Depends(can_write)):
    s = simulation.expire_token(db, id)
    record(db, u.email, 'source.token_expired', {'id': id, 'token': s.token_no})
    db.commit()
    return _view(db, s)


@router.post('/{id}/renew-token')
def renew(id: int, db=Depends(get_db), u=Depends(can_write)):
    s = db.get(SimulatedSource, id)
    if not s:
        raise HTTPException(404, '模拟源不存在')
    simulation.renew_token(s)
    record(db, u.email, 'source.token_renewed', {'id': id, 'token': s.token_no})
    db.commit()
    return _view(db, s)


@router.post('/{id}/ops')
def ops(id: int, data: OpsInput, db=Depends(get_db), u=Depends(can_write)):
    try:
        s, applied = simulation.apply_ops(db, id, data.ops)
    except HTTPException:
        raise
    record(db, u.email, 'source.write', {'id': id, 'ops': applied, 'seq': s.seq})
    db.commit()
    return {**_view(db, s), 'applied': applied}
