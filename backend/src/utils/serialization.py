import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d, view=None):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at, 'mode':d.mode, **(view or {})}
def dataset_version_dict(v):
    return {'id':v.id, 'dataset_id':v.dataset_id, 'version':v.version, 'status':v.status, 'sync_mode':v.sync_mode,
            'base_version_id':v.base_version_id, 'snapshot_seq':v.snapshot_seq, 'source_position':v.source_position,
            'target_seq':v.target_seq, 'pages':v.pages, 'row_count':v.row_count, 'upserts':v.upserts,
            'deletes':v.deletes, 'token_id':v.token_id, 'error':v.error, 'rebuild_reason':v.rebuild_reason, 'checksum':v.checksum,
            'created_at':v.created_at, 'updated_at':v.updated_at, 'published_at':v.published_at,
            'superseded_at':v.superseded_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','dataset_version_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
