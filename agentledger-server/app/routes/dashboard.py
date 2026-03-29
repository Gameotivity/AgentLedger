"""GET /dashboard — Aggregated dashboard data for the web UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import Event, WasteFlag, RoutingRecommendation
from app.models.schemas import (
    AgentSummaryOut,
    DashboardOut,
    RecommendationOut,
    WasteFlagOut,
)

router = APIRouter()


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    project: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated dashboard data: total spend, top agents, top waste, savings available, trend charts."""

    # Total spend & calls
    totals = await db.execute(
        select(
            func.coalesce(func.sum(Event.cost_usd), 0.0).label("spend"),
            func.count(Event.id).label("calls"),
        ).where(Event.project_id == project, Event.event_type == "llm_call")
    )
    total_row = totals.one()
    total_spend = total_row.spend
    total_calls = total_row.calls

    # Total waste
    waste_total = await db.execute(
        select(func.coalesce(func.sum(WasteFlag.estimated_waste_usd), 0.0))
        .where(WasteFlag.project_id == project)
    )
    total_waste = waste_total.scalar() or 0.0

    # Potential savings
    savings_total = await db.execute(
        select(func.coalesce(func.sum(RoutingRecommendation.estimated_monthly_savings), 0.0))
        .where(RoutingRecommendation.project_id == project)
    )
    potential_savings = savings_total.scalar() or 0.0

    # Top agents
    agent_rows = await db.execute(
        select(
            Event.agent_name,
            func.sum(Event.cost_usd).label("total_cost"),
            func.sum(Event.tokens_in + Event.tokens_out).label("total_tokens"),
            func.count(Event.id).label("call_count"),
            func.avg(Event.latency_ms).label("avg_latency"),
        )
        .where(Event.project_id == project, Event.event_type == "llm_call")
        .group_by(Event.agent_name)
        .order_by(func.sum(Event.cost_usd).desc())
        .limit(10)
    )
    top_agents = [
        AgentSummaryOut(
            agent_name=r.agent_name,
            total_cost=round(r.total_cost or 0, 4),
            total_tokens=r.total_tokens or 0,
            call_count=r.call_count or 0,
            avg_latency=round(r.avg_latency or 0, 2),
            waste_cost=0,
            waste_pct=0,
            top_model=None,
        )
        for r in agent_rows.all()
    ]

    # Recent waste
    waste_rows = await db.execute(
        select(WasteFlag)
        .where(WasteFlag.project_id == project)
        .order_by(WasteFlag.estimated_waste_usd.desc())
        .limit(5)
    )
    recent_waste = [
        WasteFlagOut(
            id=str(w.id),
            agent_name=w.agent_name,
            task_name=w.task_name,
            waste_type=w.waste_type,
            estimated_waste_usd=round(w.estimated_waste_usd, 4),
            suggestion=w.suggestion,
            created_at=w.created_at,
        )
        for w in waste_rows.scalars().all()
    ]

    # Top recommendations
    rec_rows = await db.execute(
        select(RoutingRecommendation)
        .where(RoutingRecommendation.project_id == project)
        .order_by(RoutingRecommendation.estimated_monthly_savings.desc())
        .limit(5)
    )
    top_recs = [
        RecommendationOut(
            agent_name=r.agent_name,
            task_pattern=r.task_pattern,
            current_model=r.current_model,
            recommended_model=r.recommended_model,
            estimated_monthly_savings=round(r.estimated_monthly_savings, 2),
            confidence=round(r.confidence, 2),
            reasoning=r.reasoning,
        )
        for r in rec_rows.scalars().all()
    ]

    # Spend trend (last 30 days)
    trend_rows = await db.execute(
        select(
            func.date_trunc("day", Event.created_at).label("day"),
            func.sum(Event.cost_usd).label("cost"),
            func.count(Event.id).label("calls"),
        )
        .where(Event.project_id == project, Event.event_type == "llm_call")
        .group_by(func.date_trunc("day", Event.created_at))
        .order_by(func.date_trunc("day", Event.created_at))
        .limit(30)
    )
    spend_trend = [
        {"date": str(r.day.date()), "cost": round(r.cost, 4), "calls": r.calls}
        for r in trend_rows.all()
    ]

    return DashboardOut(
        total_spend=round(total_spend, 4),
        total_calls=total_calls,
        total_waste=round(total_waste, 4),
        potential_savings=round(potential_savings, 2),
        top_agents=top_agents,
        recent_waste=recent_waste,
        top_recommendations=top_recs,
        spend_trend=spend_trend,
    )
