from fastapi import HTTPException
from sqlalchemy import select
from src.models import Dataset, DatasetVersion
from src.services.records import validate
from src.utils.serialization import checksum
import time


def create(db, data):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(Dataset).where(Dataset.name == name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    validate(data.records)
    now = time.time()
    d = Dataset(name=name, source=data.source, records=data.records, checksum=checksum(data.records),
                created_at=now, mode='manual')
    db.add(d)
    db.flush()
    # A manual import is itself a complete published version.
    v = DatasetVersion(dataset_id=d.id, version=1, status='synced', sync_mode='manual', records=data.records,
                       row_count=len(data.records), checksum=d.checksum,
                       created_at=now, updated_at=now, published_at=now)
    db.add(v)
    db.flush()
    d.current_version_id = v.id
    return d


def create_source(db, data):
    from src.services import sync
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(Dataset).where(Dataset.name == name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    source = sync_source_lookup(db, data.simulated_source_id)
    now = time.time()
    d = Dataset(name=name, source=source.name, records=[], checksum='', created_at=now, mode='source',
                source_id=source.id)
    db.add(d)
    db.flush()
    return d


def sync_source_lookup(db, source_id):
    from src.models import SimulatedSource
    source = db.get(SimulatedSource, source_id)
    if not source:
        raise HTTPException(404, '模拟源不存在')
    return source
