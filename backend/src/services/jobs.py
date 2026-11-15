import time
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Dataset, Job, DatasetVersion
from src.services.business import metadata
def create(db, data, user):
    d=db.get(Dataset,data.dataset_id)
    if not d: raise HTTPException(404,'数据批次不存在')
    # Pin the complete published batch now; a later publish must not change this trial's input.
    if not d.current_version_id: raise HTTPException(409,'该批次尚无已发布的全量版本，请先完成同步')
    v=db.get(DatasetVersion,d.current_version_id)
    if not v or v.status!='synced' or v.published_at is None: raise HTTPException(409,'该批次尚无已发布的全量版本，请先完成同步')
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(data.params)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(data.params)
    for key,p in allowed.items():
        value=params[key]
        if p['type']=='number':
            try:
                value=float(value)
                if not (p.get('min',-1e9)<=value<=p.get('max',1e9)): raise ValueError()
                params[key]=value
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(value) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    j=Job(name=data.name, dataset_id=data.dataset_id, dataset_version_id=v.id, params=params, created_by=user.id, created_at=time.time(), status='queued')
    db.add(j); db.flush()
    return j
def enqueue(job_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',job_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback
