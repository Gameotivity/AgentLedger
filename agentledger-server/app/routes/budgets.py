"""POST /budgets — Create/update budget guardrails."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import Budget, Event
from app.models.schemas import BudgetIn, BudgetOut

router = APIRouter()


@router.post("/budgets", response_model=BudgetOut)
async def create_or_update_budget(
    budget_in: BudgetIn,
    db: AsyncSession = Depends(get_db),
):
    """Create or update budget guardrails. Per-project or per-agent limits with alert webhooks."""
    # Upsert
    result = await db.execute(
        select(Budget).where(
            Budget.project_id == budget_in.project_id,
            Budget.agent_name == budget_in.agent_name,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.limit_usd = budget_in.limit_usd
        existing.period = budget_in.period
        existing.alert_threshold_pct = budget_in.alert_threshold_pct
        existing.webhook_url = budget_in.webhook_url
        budget = existing
    else:
        budget = Budget(
            project_id=budget_in.project_id,
            agent_name=budget_in.agent_name,
            limit_usd=budget_in.limit_usd,
            period=budget_in.period,
            alert_threshold_pct=budget_in.alert_threshold_pct,
            webhook_url=budget_in.webhook_url,
        )
        db.add(budget)

    await db.commit()
    await db.refresh(budget)

    current_spend = await _get_current_spend(db, budget)
    pct = (current_spend / budget.limit_usd * 100) if budget.limit_usd > 0 else 0

    return BudgetOut(
        id=str(budget.id),
        project_id=budget.project_id,
        agent_name=budget.agent_name,
        limit_usd=budget.limit_usd,
        period=budget.period,
        alert_threshold_pct=budget.alert_threshold_pct,
        webhook_url=budget.webhook_url,
        current_spend=round(current_spend, 4),
        pct_used=round(pct, 1),
    )


@router.get("/budgets", response_model=list[BudgetOut])
async def list_budgets(
    project: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Budget).where(Budget.project_id == project))
    budgets = result.scalars().all()

    out = []
    for b in budgets:
        spend = await _get_current_spend(db, b)
        pct = (spend / b.limit_usd * 100) if b.limit_usd > 0 else 0
        out.append(
            BudgetOut(
                id=str(b.id),
                project_id=b.project_id,
                agent_name=b.agent_name,
                limit_usd=b.limit_usd,
                period=b.period,
                alert_threshold_pct=b.alert_threshold_pct,
                webhook_url=b.webhook_url,
                current_spend=round(spend, 4),
                pct_used=round(pct, 1),
            )
        )
    return out


async def _get_current_spend(db: AsyncSession, budget: Budget) -> float:
    """Calculate current spend for a budget's period."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    if budget.period == "daily":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif budget.period == "weekly":
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # monthly
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    query = select(func.coalesce(func.sum(Event.cost_usd), 0.0)).where(
        Event.project_id == budget.project_id,
        Event.created_at >= start,
    )
    if budget.agent_name:
        query = query.where(Event.agent_name == budget.agent_name)

    result = await db.execute(query)
    return result.scalar() or 0.0
