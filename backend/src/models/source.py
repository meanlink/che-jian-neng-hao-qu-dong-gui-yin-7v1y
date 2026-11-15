from sqlalchemy import String, JSON, Double, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class SimulatedSource(Base):
    """Independent upstream ledger that keeps accepting writes while a batch is read."""
    __tablename__ = 'simulated_sources'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    label: Mapped[str] = mapped_column(String(200), default='')
    # Each row: public fields + _key (day), _seq (last change position), _deleted (tombstone).
    records: Mapped[list] = mapped_column(JSON, default=list)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    page_size: Mapped[int] = mapped_column(Integer, default=25)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    fail_at_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fail_at_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_no: Mapped[int] = mapped_column(Integer, default=1)
    token_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    token_expires_at: Mapped[float] = mapped_column(Double, default=0.0)
    created_at: Mapped[float] = mapped_column(Double)
    updated_at: Mapped[float] = mapped_column(Double)
