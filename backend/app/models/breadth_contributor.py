"""Persisted date-level breadth contributor snapshots."""

from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..database import Base


class MarketBreadthContributorSnapshot(Base):
    __tablename__ = "market_breadth_contributor_snapshots"

    id = Column(Integer, primary_key=True)
    market = Column(String(8), nullable=False)
    date = Column(Date, nullable=False)
    calculation_revision = Column(Integer, nullable=False)
    schema_id = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    contributors = relationship(
        "MarketBreadthContributor",
        back_populates="snapshot",
        cascade="all, delete-orphan",
        order_by="MarketBreadthContributor.symbol",
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["date", "market"],
            ["market_breadth.date", "market_breadth.market"],
            name="fk_breadth_contributor_snapshot_aggregate",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "market",
            "date",
            name="uq_breadth_contributor_snapshot_market_date",
        ),
        Index(
            "ix_breadth_contributor_snapshot_market_date",
            "market",
            "date",
        ),
    )


class MarketBreadthContributor(Base):
    __tablename__ = "market_breadth_contributors"

    id = Column(Integer, primary_key=True)
    snapshot_id = Column(
        Integer,
        ForeignKey(
            "market_breadth_contributor_snapshots.id",
            name="fk_breadth_contributor_snapshot",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )
    symbol = Column(String(32), nullable=False)
    company_name = Column(String(255), nullable=True)
    ibd_industry_group = Column(String(255), nullable=False)
    daily_change_pct = Column(Float, nullable=False)
    signals_json = Column(JSON, nullable=False)

    snapshot = relationship(
        "MarketBreadthContributorSnapshot",
        back_populates="contributors",
    )

    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "symbol",
            name="uq_breadth_contributor_snapshot_symbol",
        ),
    )
