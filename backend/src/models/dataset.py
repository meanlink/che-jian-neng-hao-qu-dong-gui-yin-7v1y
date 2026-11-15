from sqlalchemy import String, JSON, Double, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Dataset(Base):
    """Logical batch header. Its readable content always comes from a published version."""
    __tablename__ = 'datasets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    records: Mapped[list] = mapped_column(JSON, default=list)
    checksum: Mapped[str] = mapped_column(String(64), default='')
    created_at: Mapped[float] = mapped_column(Double)
    # manual: one-off JSON/CSV import; source: continuously synchronised simulated upstream.
    mode: Mapped[str] = mapped_column(String(20), default='manual')
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey('simulated_sources.id'), nullable=True)


class DatasetVersion(Base):
    """Immutable-once-published batch version. In-flight versions live here too."""
    __tablename__ = 'dataset_versions'
    __table_args__ = (UniqueConstraint('dataset_id', 'version', name='uq_dataset_version'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    version: Mapped[int] = mapped_column(Integer)
    # full_in_progress | catching_up | synced | needs_rebuild
    status: Mapped[str] = mapped_column(String(24), default='full_in_progress')
    # full | incremental | manual
    sync_mode: Mapped[str] = mapped_column(String(20), default='full')
    records: Mapped[list] = mapped_column(JSON, default=list)

    base_version_id: Mapped[int | None] = mapped_column(ForeignKey('dataset_versions.id'), nullable=True)
    snapshot_seq: Mapped[int] = mapped_column(Integer, default=0)
    source_position: Mapped[int] = mapped_column(Integer, default=0)
    target_seq: Mapped[int] = mapped_column(Integer, default=0)
    page_cursor: Mapped[str] = mapped_column(String(160), default='')
    token_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    pages: Mapped[int] = mapped_column(Integer, default=0)
    upserts: Mapped[int] = mapped_column(Integer, default=0)
    deletes: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)

    actor: Mapped[str] = mapped_column(String(150), default='')
    error: Mapped[str] = mapped_column(String(1000), default='')
    rebuild_reason: Mapped[str] = mapped_column(String(1000), default='')
    checksum: Mapped[str] = mapped_column(String(64), default='')
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
    published_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    superseded_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    # Equals dataset_id while the version is unpublished, NULL afterwards. The unique
    # constraint lets the database itself reject a second in-flight batch.
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
