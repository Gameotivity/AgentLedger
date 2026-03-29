"""POST /events — Batch event ingestion from SDK."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.tables import Event, ModelPricing
from app.models.schemas import EventBatchIn, BatchResult

logger = logging.getLogger("agentledger.events")
router = APIRouter()

# Load pricing from bundled JSON as fallback
_PRICING_FILE = Path(__file__).resolve().parent.parent.parent.parent / "pricing" / "models.json"
_pricing_cache: dict[str, dict[str, float]] | None = None


def _get_pricing() -> dict[str, dict[str, float]]:
    global _pricing_cache
    if _pricing_cache is not None:
        return _pricing_cache
    if _PRICING_FILE.exists():
        with _PRICING_FILE.open() as f:
            data = json.load(f)
        _pricing_cache = {}
        for entry in data.get("models", []):
            key = entry.get("model", "")
            _pricing_cache[key] = {
                "input": entry.get("input_cost_per_1m", 0.0),
                "output": entry.get("output_cost_per_1m", 0.0),
            }
        return _pricing_cache
    _pricing_cache = {}
    return _pricing_cache


def _compute_cost(model: str | None, tokens_in: int, tokens_out: int) -> float:
    if not model:
        return 0.0
    pricing = _get_pricing()
    rates = pricing.get(model)
    if not rates:
        short = model.split("/")[-1] if "/" in model else model
        for k, v in pricing.items():
            if short in k:
                rates = v
                break
    if not rates:
        return 0.0
    return (tokens_in / 1_000_000) * rates["input"] + (tokens_out / 1_000_000) * rates["output"]


@router.post("/events", response_model=BatchResult)
async def ingest_events(batch: EventBatchIn, db: AsyncSession = Depends(get_db)):
    """Batch ingest events from SDK. Accepts array of call records. Async processing."""
    if len(batch.events) > settings.batch_max_size:
        raise HTTPException(400, f"Batch too large. Max {settings.batch_max_size} events.")

    accepted = 0
    for ev in batch.events:
        cost = ev.cost_usd if ev.cost_usd > 0 else _compute_cost(ev.model, ev.tokens_in, ev.tokens_out)
        event = Event(
            project_id=ev.project,
            event_type=ev.type,
            agent_name=ev.agent_name,
            task_name=ev.task_name,
            task_id=ev.task_id,
            step=ev.step,
            model=ev.model,
            tokens_in=ev.tokens_in,
            tokens_out=ev.tokens_out,
            cost_usd=cost,
            latency_ms=ev.latency_ms,
            prompt_hash=ev.prompt_hash,
            status=ev.status,
            error=ev.error,
            metadata_json=ev.metadata,
        )
        db.add(event)
        accepted += 1

    await db.commit()
    logger.info("Ingested %d events", accepted)
    return BatchResult(accepted=accepted)
