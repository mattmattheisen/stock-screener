"""Experimental point-in-time CAN SLIM V1-vs-V2 shadow evidence."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from ..database import Base


class CANSLIMV2ShadowComparison(Base):
    """Immutable same-snapshot comparison between legacy CAN SLIM and V2."""

    __tablename__ = "canslim_v2_shadow_comparisons"

    id = Column(Integer, primary_key=True)
    as_of_date = Column(Date, nullable=False)
    run_ref = Column(String(128), nullable=False)
    symbol = Column(String(32), nullable=False)
    methodology_version = Column(String(64), nullable=False)

    v1_score = Column(Float, nullable=False)
    v1_passes = Column(Boolean, nullable=False)
    v1_rating = Column(String(32), nullable=False)

    v2_stock_score = Column(Float, nullable=False)
    v2_stock_passes = Column(Boolean, nullable=False)
    v2_market_passes = Column(Boolean, nullable=False)
    v2_actionable = Column(Boolean, nullable=False)
    v2_rating = Column(String(32), nullable=False)
    v2_status = Column(String(64), nullable=False)

    market_exposure_score = Column(Float, nullable=True)
    market_stance = Column(String(64), nullable=True)
    score_delta_v2_minus_v1 = Column(Float, nullable=False)
    action_disagreement = Column(Boolean, nullable=False)

    evidence_hash = Column(String(64), nullable=False)
    evidence_json = Column(JSON, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "as_of_date",
            "run_ref",
            "symbol",
            "methodology_version",
            name="uq_canslim_v2_shadow_identity",
        ),
        Index(
            "ix_canslim_v2_shadow_asof_symbol",
            "as_of_date",
            "symbol",
        ),
        Index(
            "ix_canslim_v2_shadow_methodology",
            "methodology_version",
        ),
        Index(
            "ix_canslim_v2_shadow_disagreement",
            "action_disagreement",
            "as_of_date",
        ),
    )
