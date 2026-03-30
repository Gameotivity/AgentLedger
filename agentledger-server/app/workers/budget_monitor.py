"""Budget monitor — checks spend against limits and sends webhook alerts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Budget, Event

logger = logging.getLogger("agentledger.budget")


async def check_budgets(db: AsyncSession) -> int:
    """Check all enabled budgets and fire alerts for those exceeding thresholds. Returns alert count."""
    result = await db.execute(select(Budget).where(Budget.enabled.is_(True)))
    budgets = result.scalars().all()

    alerts_sent = 0
    now = datetime.now(timezone.utc)

    for budget in budgets:
        # Determine period start
        if budget.period == "daily":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif budget.period == "weekly":
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        else:  # monthly
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Calculate spend
        spend_query = select(func.coalesce(func.sum(Event.cost_usd), 0.0)).where(
            Event.project_id == budget.project_id,
            Event.created_at >= start,
        )
        if budget.agent_name:
            spend_query = spend_query.where(Event.agent_name == budget.agent_name)

        spend_result = await db.execute(spend_query)
        current_spend = spend_result.scalar() or 0.0

        pct_used = (current_spend / budget.limit_usd) if budget.limit_usd > 0 else 0

        if pct_used >= budget.alert_threshold_pct and budget.webhook_url:
            await _send_alert(budget, current_spend, pct_used)
            alerts_sent += 1

    if alerts_sent:
        logger.info("Sent %d budget alerts", alerts_sent)
    return alerts_sent


async def _send_alert(budget: Budget, current_spend: float, pct_used: float) -> None:
    """Send a budget alert via webhook."""
    agent_label = budget.agent_name or "all agents"
    payload = {
        "text": (
            f"AgentLedger Budget Alert: {agent_label} in project '{budget.project_id}' "
            f"has used {pct_used:.0%} of its {budget.period} budget "
            f"(${current_spend:.2f} / ${budget.limit_usd:.2f})"
        ),
        "project": budget.project_id,
        "agent": budget.agent_name,
        "current_spend": round(current_spend, 4),
        "limit": budget.limit_usd,
        "period": budget.period,
        "pct_used": round(pct_used * 100, 1),
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(budget.webhook_url, json=payload, timeout=10.0)
            resp.raise_for_status()
            logger.info("Budget alert sent for %s/%s", budget.project_id, agent_label)
    except Exception as exc:
        logger.error("Failed to send budget alert to %s: %s", budget.webhook_url, exc)
