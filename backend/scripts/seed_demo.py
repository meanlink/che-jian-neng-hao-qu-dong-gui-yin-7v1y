import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, DatasetVersion, Job, Report, Delivery, Audit, SimulatedSource
from src.services.business import metadata, analyze
from src.services.reports import deliver
from src.services import simulation, sync
from src.utils.security import hash_password
from src.utils.serialization import checksum


def seed():
    migrate()
    with Session() as db:
        for role, name in [('admin', '林知 · 业务负责人'), ('analyst', '陈舟 · 分析员'), ('viewer', '周禾 · 观察员')]:
            email = role + '@demo.local'
            if not db.scalar(select(User).where(User.email == email)):
                db.add(User(email=email, name=name, role=role, password=hash_password('Demo123!')))
        db.flush()
        m = metadata()
        simulation.ensure_demo(db)
        db.commit()

        d = db.scalar(select(Dataset).where(Dataset.name == m['dataset_name']))
        if not d:
            source = db.scalar(select(SimulatedSource).where(SimulatedSource.name == simulation.SOURCE_NAME))
            d = Dataset(name=m['dataset_name'], source=source.name, records=[], checksum='', created_at=time.time(),
                        mode='source', source_id=source.id)
            db.add(d)
            db.flush()
            db.commit()
            # The demo baseline is a complete published batch built through the same sync path.
            sync.advance(db, d.id, 'seed')
            d = db.get(Dataset, d.id)

        if not db.scalar(select(Job).where(Job.name == '基线复核 · ' + m['name'])):
            params = {p['key']: p['default'] for p in m.get('parameters', [])}
            version = db.get(DatasetVersion, d.current_version_id)
            result = analyze(version.records, params)
            json.dumps(result, ensure_ascii=False, allow_nan=False)
            admin = db.scalar(select(User).where(User.role == 'admin'))
            j = Job(name='基线复核 · ' + m['name'], dataset_id=d.id, dataset_version_id=version.id, params=params,
                    status='completed', result=result, created_by=admin.id, created_at=time.time() - 3600,
                    finished_at=time.time() - 3595, approved=True)
            db.add(j); db.flush()
            r = Report(name='每日业务复核简报', job_id=j.id, destination='业务复核组 · 本地收件箱',
                       interval_seconds=86400, next_run=time.time() + 86400, enabled=True)
            db.add(r); db.flush(); deliver(db, r)
            db.add(Audit(actor='seed', action='demo.baseline', detail={'dataset': d.id, 'version': version.version}, at=time.time()))
        db.commit()
        counts = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                  for model in [User, Dataset, DatasetVersion, Job, Report, Delivery, Audit, SimulatedSource]}
        print(json.dumps(counts, ensure_ascii=False))
        return counts


if __name__ == '__main__':
    seed()
