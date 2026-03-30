"""Waste detection engine — finds retry loops, over-qualified models, and context bloat."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Event, WasteFlag

logger = logging.getLogger("agentledger.waste")

# Model tier mapping — used to detect over-qualified model usage
_MODEL_TIERS: dict[str, int] = {}
_PRICING_FILE = Path(__file__).resolve().parent.parent.parent.parent / "pricing" / "models.json"


def _load_tiers() -> dict[str, int]:
    global _MODEL_TIERS
    if _MODEL_TIERS:
        return _MODEL_TIERS
    if _PRICING_FILE.exists():
        with _PRICING_FILE.open() as f:
            data = json.load(f)
        for entry in data.get("models", []):
            _MODEL_TIERS[entry["model"]] = entry.get("tier", 2)  # 1=cheap, 2=mid, 3=expensive
    return _MODEL_TIERS


async def detect_retry_loops(db: AsyncSession, project_id: str) -> list[WasteFlag]:
    """Flag cases where the same prompt hash appears 3+ times in a task — indicates retry loops."""
    result = await db.execute(
        select(
            Event.agent_name,
            Event.task_id,
            Event.task_name,
            Event.prompt_hash,
            func.count(Event.id).label("repeat_count"),
            func.sum(Event.cost_usd).label("total_cost"),
        )
        .where(
            Event.project_id == project_id,
            Event.event_type == "llm_call",
            Event.prompt_hash.isnot(None),
        )
        .group_by(Event.agent_name, Event.task_id, Event.task_name, Event.prompt_hash)
        .having(func.count(Event.id) >= 3)
    )

    flags = []
    for row in result.all():
        # Waste = cost of all calls beyond the first one
        waste = row.total_cost * (1 - 1 / row.repeat_count)
        flag = WasteFlag(
            project_id=project_id,
            agent_name=row.agent_name,
            task_name=row.task_name,
            waste_type="retry_loop",
            estimated_waste_usd=round(waste, 6),
            suggestion=f"Same prompt repeated {row.repeat_count}x in task '{row.task_name}'. "
                        f"Consider adding error handling or caching. Estimated waste: ${waste:.2f}",
            details_json={
                "prompt_hash": row.prompt_hash,
                "repeat_count": row.repeat_count,
                "task_id": row.task_id,
            },
        )
        flags.append(flag)
    return flags


async def detect_over_qualified_models(db: AsyncSession, project_id: str) -> list[WasteFlag]:
    """Flag tasks where an expensive model is used but output complexity suggests a cheaper one would work."""
    tiers = _load_tiers()

    # Find tasks using tier-3 (expensive) models with low output token counts
    # Low output tokens + expensive model = likely over-qualified
    result = await db.execute(
        select(
            Event.agent_name,
            Event.task_name,
            Event.model,
            func.avg(Event.tokens_out).label("avg_tokens_out"),
            func.count(Event.id).label("call_count"),
            func.sum(Event.cost_usd).label("total_cost"),
        )
        .where(
            Event.project_id == project_id,
            Event.event_type == "llm_call",
            Event.model.isnot(None),
        )
        .group_by(Event.agent_name, Event.task_name, Event.model)
    )

    flags = []
    for row in result.all():
        tier = tiers.get(row.model, 2)
        if tier < 3:
            continue
        # If avg output is under 500 tokens, a cheaper model likely suffices
        if (row.avg_tokens_out or 0) > 500:
            continue

        estimated_savings = row.total_cost * 0.7  # ~70% savings switching from tier 3 to tier 1
        flag = WasteFlag(
            project_id=project_id,
            agent_name=row.agent_name,
            task_name=row.task_name,
            waste_type="over_qualified_model",
            estimated_waste_usd=round(estimated_savings, 6),
            suggestion=f"'{row.agent_name}' uses {row.model} for '{row.task_name}' but avg output is "
                        f"only {int(row.avg_tokens_out or 0)} tokens. A cheaper model could handle this. "
                        f"Potential savings: ${estimated_savings:.2f}",
            details_json={
                "model": row.model,
                "avg_tokens_out": round(row.avg_tokens_out or 0, 0),
                "call_count": row.call_count,
            },
        )
        flags.append(flag)
    return flags


async def detect_context_bloat(db: AsyncSession, project_id: str) -> list[WasteFlag]:
    """Flag tasks where input tokens grow linearly across steps — indicates context window bloat."""
    result = await db.execute(
        select(
            Event.agent_name,
            Event.task_id,
            Event.task_name,
            Event.step,
            Event.tokens_in,
            Event.cost_usd,
        )
        .where(
            Event.project_id == project_id,
            Event.event_type == "llm_call",
            Event.task_id.isnot(None),
            Event.step.isnot(None),
        )
        .order_by(Event.task_id, Event.step)
    )

    tasks: dict[str, list] = defaultdict(list)
    task_meta: dict[str, dict] = {}
    for row in result.all():
        tasks[row.task_id].append({"step": row.step, "tokens_in": row.tokens_in, "cost": row.cost_usd})
        task_meta[row.task_id] = {"agent_name": row.agent_name, "task_name": row.task_name}

    flags = []
    for task_id, steps in tasks.items():
        if len(steps) < 3:
            continue
        # Check if tokens_in is consistently growing
        token_sequence = [s["tokens_in"] for s in steps]
        growth_count = sum(1 for i in range(1, len(token_sequence)) if token_sequence[i] > token_sequence[i - 1])
        if growth_count / (len(token_sequence) - 1) < 0.7:
            continue

        # Estimate waste: excess tokens beyond the first step's baseline
        baseline = token_sequence[0]
        excess_tokens = sum(max(0, t - baseline) for t in token_sequence[1:])
        total_cost = sum(s["cost"] for s in steps)
        total_tokens = sum(s["tokens_in"] for s in steps)
        waste = total_cost * (excess_tokens / total_tokens) if total_tokens > 0 else 0

        meta = task_meta[task_id]
        flag = WasteFlag(
            project_id=project_id,
            agent_name=meta["agent_name"],
            task_name=meta["task_name"],
            waste_type="context_bloat",
            estimated_waste_usd=round(waste, 6),
            suggestion=f"Context window grows from {token_sequence[0]:,} to {token_sequence[-1]:,} tokens "
                        f"across {len(steps)} steps in '{meta['task_name']}'. Consider summarizing context "
                        f"between steps. Estimated waste: ${waste:.2f}",
            details_json={
                "task_id": task_id,
                "step_count": len(steps),
                "first_tokens": token_sequence[0],
                "last_tokens": token_sequence[-1],
            },
        )
        flags.append(flag)
    return flags


async def run_waste_detection(db: AsyncSession, project_id: str) -> int:
    """Run all waste detectors and persist results. Returns number of flags created."""
    all_flags = []
    all_flags.extend(await detect_retry_loops(db, project_id))
    all_flags.extend(await detect_over_qualified_models(db, project_id))
    all_flags.extend(await detect_context_bloat(db, project_id))

    for flag in all_flags:
        db.add(flag)

    if all_flags:
        await db.commit()
        logger.info("Created %d waste flags for project %s", len(all_flags), project_id)

    return len(all_flags)
