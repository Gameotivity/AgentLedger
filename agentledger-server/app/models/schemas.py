"""Pydantic schemas for API request/response validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# --- Events ---

class EventIn(BaseModel):
    type: str = Field(default="llm_call", description="Event type: llm_call or task_span")
    agent_name: str
    task_name: str | None = None
    task_id: str | None = None
    step: int | None = None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    prompt_hash: str | None = None
    status: str = "success"
    error: str | None = None
    metadata: dict[str, Any] | None = None


class EventBatchIn(BaseModel):
    events: list[EventIn]


class EventOut(BaseModel):
    id: str
    project_id: str
    event_type: str
    agent_name: str
    task_name: str | None
    model: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: float
    status: str
    created_at: datetime


class BatchResult(BaseModel):
    accepted: int
    failed: int = 0


# --- Agents ---

class AgentSummaryOut(BaseModel):
    agent_name: str
    total_cost: float
    total_tokens: int
    call_count: int
    avg_latency: float
    waste_cost: float
    waste_pct: float
    top_model: str | None


class AgentCostBreakdown(BaseModel):
    agent_name: str
    by_task: list[dict[str, Any]]
    by_model: list[dict[str, Any]]
    by_period: list[dict[str, Any]]
    total_cost: float
    total_calls: int


# --- Waste ---

class WasteFlagOut(BaseModel):
    id: str
    agent_name: str
    task_name: str | None
    waste_type: str
    estimated_waste_usd: float
    suggestion: str | None
    created_at: datetime


# --- Recommendations ---

class RecommendationOut(BaseModel):
    agent_name: str
    task_pattern: str | None
    current_model: str
    recommended_model: str
    estimated_monthly_savings: float
    confidence: float
    reasoning: str | None


# --- Budgets ---

class BudgetIn(BaseModel):
    project_id: str
    agent_name: str | None = None
    limit_usd: float
    period: str = "monthly"  # daily | weekly | monthly
    alert_threshold_pct: float = 0.8
    webhook_url: str | None = None


class BudgetOut(BaseModel):
    id: str
    project_id: str
    agent_name: str | None
    limit_usd: float
    period: str
    alert_threshold_pct: float
    webhook_url: str | None
    current_spend: float = 0.0
    pct_used: float = 0.0


# --- Dashboard ---

class DashboardOut(BaseModel):
    total_spend: float
    total_calls: int
    total_waste: float
    potential_savings: float
    top_agents: list[AgentSummaryOut]
    recent_waste: list[WasteFlagOut]
    top_recommendations: list[RecommendationOut]
    spend_trend: list[dict[str, Any]]
