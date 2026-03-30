"""GET /agents — Agent listing and per-agent cost breakdown."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import Event, WasteFlag
from app.models.schemas import AgentSummaryOut, AgentCostBreakdown

router = APIRouter()


@router.get("/agents", response_model=list[AgentSummaryOut])
async def list_agents(
    project: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """List all agents in project with summary stats."""
    result = await db.execute(
        select(
            Event.agent_name,
            func.sum(Event.cost_usd).label("total_cost"),
            func.sum(Event.tokens_in + Event.tokens_out).label("total_tokens"),
            func.count(Event.id).label("call_count"),
            func.avg(Event.latency_ms).label("avg_latency"),
            Event.model.label("top_model"),
        )
        .where(Event.project_id == project, Event.event_type == "llm_call")
        .group_by(Event.agent_name)
        .order_by(func.sum(Event.cost_usd).desc())
    )
    rows = result.all()

    agents = []
    for row in rows:
        waste_result = await db.execute(
            select(func.coalesce(func.sum(WasteFlag.estimated_waste_usd), 0.0))
            .where(WasteFlag.project_id == project, WasteFlag.agent_name == row.agent_name)
        )
        waste_cost = waste_result.scalar() or 0.0
        total_cost = row.total_cost or 0.0

        agents.append(
            AgentSummaryOut(
                agent_name=row.agent_name,
                total_cost=round(total_cost, 4),
                total_tokens=row.total_tokens or 0,
                call_count=row.call_count or 0,
                avg_latency=round(row.avg_latency or 0, 2),
                waste_cost=round(waste_cost, 4),
                waste_pct=round((waste_cost / total_cost * 100) if total_cost > 0 else 0, 1),
                top_model=row.top_model,
            )
        )
    return agents


@router.get("/agents/{name}/costs", response_model=AgentCostBreakdown)
async def agent_costs(
    name: str,
    project: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Detailed cost breakdown for one agent — the agent P&L."""
    # By task
    task_result = await db.execute(
        select(
            Event.task_name,
            func.sum(Event.cost_usd).label("cost"),
            func.count(Event.id).label("calls"),
        )
        .where(Event.project_id == project, Event.agent_name == name, Event.event_type == "llm_call")
        .group_by(Event.task_name)
        .order_by(func.sum(Event.cost_usd).desc())
    )
    by_task = [{"task": r.task_name, "cost": round(r.cost, 4), "calls": r.calls} for r in task_result.all()]

    # By model
    model_result = await db.execute(
        select(
            Event.model,
            func.sum(Event.cost_usd).label("cost"),
            func.count(Event.id).label("calls"),
            func.sum(Event.tokens_in).label("tokens_in"),
            func.sum(Event.tokens_out).label("tokens_out"),
        )
        .where(Event.project_id == project, Event.agent_name == name, Event.event_type == "llm_call")
        .group_by(Event.model)
        .order_by(func.sum(Event.cost_usd).desc())
    )
    by_model = [
        {"model": r.model, "cost": round(r.cost, 4), "calls": r.calls, "tokens_in": r.tokens_in, "tokens_out": r.tokens_out}
        for r in model_result.all()
    ]

    # By day (SQLite-compatible: use date() instead of date_trunc)
    period_result = await db.execute(
        select(
            func.date(Event.created_at).label("day"),
            func.sum(Event.cost_usd).label("cost"),
            func.count(Event.id).label("calls"),
        )
        .where(Event.project_id == project, Event.agent_name == name, Event.event_type == "llm_call")
        .group_by(func.date(Event.created_at))
        .order_by(func.date(Event.created_at))
    )
    by_period = [{"date": str(r.day), "cost": round(r.cost, 4), "calls": r.calls} for r in period_result.all()]

    total_cost = sum(t["cost"] for t in by_task)
    total_calls = sum(t["calls"] for t in by_task)

    return AgentCostBreakdown(
        agent_name=name,
        by_task=by_task,
        by_model=by_model,
        by_period=by_period,
        total_cost=round(total_cost, 4),
        total_calls=total_calls,
    )
