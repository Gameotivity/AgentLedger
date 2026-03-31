"""SQLAlchemy models for AgentLedger — maps to the data model from the blueprint."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid_str() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Event(Base):
    """Raw event log. Every LLM call your agents make. Immutable append-only."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # llm_call | task_span
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    task_name: Mapped[str | None] = mapped_column(String(255))
    task_id: Mapped[str | None] = mapped_column(String(255))
    step: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(255))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    prompt_hash: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), default="success")
    error: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_events_project_agent", "project_id", "agent_name"),
        Index("ix_events_created_at", "created_at"),
        Index("ix_events_prompt_hash", "prompt_hash"),
    )


class AgentSummary(Base):
    """Pre-aggregated summaries for fast dashboard rendering."""

    __tablename__ = "agent_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)  # hour | day | week
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_latency: Mapped[float] = mapped_column(Float, default=0.0)
    waste_cost: Mapped[float] = mapped_column(Float, default=0.0)
    top_model: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_summary_project_agent_period", "project_id", "agent_name", "period", "period_start", unique=True),
    )


class WasteFlag(Base):
    """Waste detection results — links back to specific events with actionable fixes."""

    __tablename__ = "waste_flags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_id: Mapped[str | None] = mapped_column(String(36))
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_name: Mapped[str | None] = mapped_column(String(255))
    waste_type: Mapped[str] = mapped_column(String(50), nullable=False)
    estimated_waste_usd: Mapped[float] = mapped_column(Float, default=0.0)
    suggestion: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RoutingRecommendation(Base):
    """Model routing recommendations with estimated savings."""

    __tablename__ = "routing_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    task_pattern: Mapped[str | None] = mapped_column(String(255))
    current_model: Mapped[str] = mapped_column(String(255), nullable=False)
    recommended_model: Mapped[str] = mapped_column(String(255), nullable=False)
    estimated_monthly_savings: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reasoning: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Budget(Base):
    """Budget guardrails — per-project or per-agent limits with alert webhooks."""

    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_name: Mapped[str | None] = mapped_column(String(255))
    limit_usd: Mapped[float] = mapped_column(Float, nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    alert_threshold_pct: Mapped[float] = mapped_column(Float, default=0.8)
    webhook_url: Mapped[str | None] = mapped_column(String(500))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_budget_project_agent", "project_id", "agent_name", unique=True),
    )


class AgentEdge(Base):
    """Agent interaction topology — directed edges in the agent DAG.

    Encodes who-calls-who: (source_agent) → (target_agent) with context
    retention factor α. Used by the Shapley attribution engine to compute
    fair cost allocation per Theorem 3.2 (superadditivity of cost game).
    """

    __tablename__ = "agent_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_agent: Mapped[str] = mapped_column(String(255), nullable=False)
    target_agent: Mapped[str] = mapped_column(String(255), nullable=False)
    topology: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pipeline"
    )  # pipeline | tree | debate
    context_retention: Mapped[float] = mapped_column(
        Float, default=1.0
    )  # α_{ik} from Eq. 2
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_edge_project_src_tgt",
            "project_id", "source_agent", "target_agent",
            unique=True,
        ),
    )


class ShapleyAttribution(Base):
    """Shapley cost attribution results — fair cost allocation per agent.

    Stores the decomposition: direct cost + propagation cost = Shapley value.
    Computed from closed-form formulas (Theorems 4.1, 4.3, 4.4).
    """

    __tablename__ = "shapley_attributions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    topology: Mapped[str] = mapped_column(String(20), nullable=False)
    direct_cost: Mapped[float] = mapped_column(Float, default=0.0)
    propagation_cost: Mapped[float] = mapped_column(Float, default=0.0)
    shapley_value: Mapped[float] = mapped_column(Float, default=0.0)
    shapley_pct: Mapped[float] = mapped_column(Float, default=0.0)
    details_json: Mapped[dict | None] = mapped_column(JSON)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_shapley_project_agent",
            "project_id", "agent_name",
            unique=True,
        ),
    )


class ModelPricing(Base):
    """Community-maintained pricing database."""

    __tablename__ = "model_pricing"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    input_cost_per_1m: Mapped[float] = mapped_column(Float, nullable=False)
    output_cost_per_1m: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
