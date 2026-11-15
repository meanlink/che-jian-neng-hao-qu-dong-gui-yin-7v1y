from pydantic import BaseModel, Field


class SourceInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    label: str = Field(default='', max_length=200)
    page_size: int = Field(default=25, ge=1, le=200)
    latency_ms: int = Field(default=0, ge=0, le=500)
    token_seconds: int = Field(default=3600, ge=1, le=86400)


class SourceConfig(BaseModel):
    page_size: int | None = Field(default=None, ge=1, le=200)
    latency_ms: int | None = Field(default=None, ge=0, le=500)
    token_seconds: int | None = Field(default=None, ge=1, le=86400)
    fail_at_page: int | None = Field(default=None, ge=1)
    fail_at_seq: int | None = Field(default=None, ge=1)


class OpsInput(BaseModel):
    ops: list[dict] = Field(min_length=1, max_length=200)


class SourceDatasetInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    simulated_source_id: int


class SyncStart(BaseModel):
    max_pages: int | None = Field(default=None, ge=1, le=10000)


class SyncModeInput(BaseModel):
    mode: str = Field(default='auto', pattern='^(auto|full|incremental)$')
    max_pages: int | None = Field(default=None, ge=1, le=10000)
