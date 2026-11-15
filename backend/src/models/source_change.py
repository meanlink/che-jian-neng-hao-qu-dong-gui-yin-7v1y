from sqlalchemy import String, Integer, JSON, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class SourceChange(Base):
    """Append-only upstream change log; tombstone rows keep deletions observable."""
    __tablename__ = 'source_changes'
    __table_args__ = (Index('ix_source_changes_source_seq', 'source_id', 'seq'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey('simulated_sources.id'))
    seq: Mapped[int] = mapped_column(Integer)
    key: Mapped[str] = mapped_column(String(160))
    deleted: Mapped[bool] = mapped_column(default=False)
    record: Mapped[dict] = mapped_column(JSON, default=dict)
