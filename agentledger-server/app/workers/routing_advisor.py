"""Routing advisor — analyzes model usage patterns and recommends cheaper alternatives."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Event, RoutingRecommendation

logger = logging.getLogger("agentledger.routing")

_PRICING_FILE = Path(__file__).resolve().parent.parent.parent.parent / "pricing" / "models.json"


def _load_pricing() -> dict[str, dict]:
    if _PRICING_FILE.exists():
        with _PRICING_FILE.open() as f:
            data = json.load(f)
        return {
            entry["model"]: {
                "input": entry.get("input_cost_per_1m", 0),
                "output": entry.get("output_cost_per_1m", 0),
                "tier": entry.get("tier", 2),
                "provider": entry.get("provider", "unknown"),
            }
            for entry in data.get("models", [])
        }
    return {}


def _find_cheaper_alternative(
    current_model: str, avg_tokens_out: float, pricing: dict[str, dict]
) -> tuple[str, float, float] | None:
    """Find a cheaper model that can handle the task. Returns (model, savings_ratio, confidence)."""
    current = pricing.get(current_model)
    if not current:
        return None

    current_tier = current["tier"]
    current_cost_per_call = current["input"] + current["output"]  # rough per-1M comparison

    best_alt = None
    best_savings = 0.0

    for model, info in pricing.items():
        if model == current_model:
            continue
        if info["tier"] >= current_tier:
            continue

        alt_cost = info["input"] + info["output"]
        savings_ratio = 1 - (alt_cost / current_cost_per_call) if current_cost_per_call > 0 else 0

        if savings_ratio > best_savings:
            # Confidence based on task complexity (avg output tokens)
            if avg_tokens_out < 200:
                confidence = 0.9  # Short outputs = high confidence cheap model works
            elif avg_tokens_out < 500:
                confidence = 0.7
            elif avg_tokens_out < 1000:
                confidence = 0.5
            else:
                confidence = 0.3

            best_alt = (model, savings_ratio, confidence)
            best_savings = savings_ratio

    return best_alt


async def generate_recommendations(db: AsyncSession, project_id: str) -> int:
    """Analyze usage patterns and generate routing recommendations. Returns count."""
    pricing = _load_pricing()
    if not pricing:
        logger.warning("No pricing data available, skipping routing analysis")
        return 0

    # Get per-agent, per-task, per-model usage patterns
    result = await db.execute(
        select(
            Event.agent_name,
            Event.task_name,
            Event.model,
            func.count(Event.id).label("call_count"),
            func.sum(Event.cost_usd).label("total_cost"),
            func.avg(Event.tokens_out).label("avg_tokens_out"),
            func.avg(Event.tokens_in).label("avg_tokens_in"),
        )
        .where(
            Event.project_id == project_id,
            Event.event_type == "llm_call",
            Event.model.isnot(None),
        )
        .group_by(Event.agent_name, Event.task_name, Event.model)
        .having(func.count(Event.id) >= 5)  # Need enough data to recommend
    )

    recs_created = 0
    for row in result.all():
        alt = _find_cheaper_alternative(row.model, row.avg_tokens_out or 0, pricing)
        if not alt:
            continue

        alt_model, savings_ratio, confidence = alt
        monthly_projection = row.total_cost * 30  # rough monthly projection
        monthly_savings = monthly_projection * savings_ratio

        if monthly_savings < 1.0:  # Not worth recommending under $1/month
            continue

        rec = RoutingRecommendation(
            project_id=project_id,
            agent_name=row.agent_name,
            task_pattern=row.task_name,
            current_model=row.model,
            recommended_model=alt_model,
            estimated_monthly_savings=round(monthly_savings, 2),
            confidence=round(confidence, 2),
            reasoning=f"'{row.agent_name}' uses {row.model} for '{row.task_name}' "
                      f"({row.call_count} calls, avg {int(row.avg_tokens_out or 0)} output tokens). "
                      f"Switch to {alt_model} to save ~${monthly_savings:.0f}/month.",
        )
        db.add(rec)
        recs_created += 1

    if recs_created:
        await db.commit()
        logger.info("Created %d routing recommendations for project %s", recs_created, project_id)

    return recs_created
