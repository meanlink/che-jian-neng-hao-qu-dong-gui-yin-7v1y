from enum import Enum


class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'


class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'


class SyncStatus(str, Enum):
    full_in_progress = 'full_in_progress'
    catching_up = 'catching_up'
    synced = 'synced'
    needs_rebuild = 'needs_rebuild'


class SyncMode(str, Enum):
    full = 'full'
    incremental = 'incremental'
    manual = 'manual'
