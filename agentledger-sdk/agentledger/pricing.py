"""Model pricing lookup — loads from the community-maintained pricing JSON."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("agentledger")

_PRICING_FILE = Path(__file__).resolve().parent.parent.parent / "pricing" / "models.json"
_pricing_cache: dict[str, dict[str, float]] | None = None


def load_pricing(path: str | Path | None = None) -> dict[str, dict[str, float]]:
    """Load model pricing from JSON. Returns {model: {input/output cost per 1M}}."""
    global _pricing_cache
    if _pricing_cache is not None:
        return _pricing_cache

    pricing_path = Path(path) if path else _PRICING_FILE
    if not pricing_path.exists():
        logger.warning("Pricing file not found at %s, using empty pricing", pricing_path)
        _pricing_cache = {}
        return _pricing_cache

    with pricing_path.open() as f:
        data = json.load(f)

    _pricing_cache = {}
    for entry in data.get("models", []):
        key = entry.get("model") or (
            f"{entry.get('provider', 'unknown')}/{entry.get('name', 'unknown')}"
        )
        _pricing_cache[key] = {
            "input_cost_per_1m": entry.get("input_cost_per_1m", 0.0),
            "output_cost_per_1m": entry.get("output_cost_per_1m", 0.0),
        }

    logger.info("Loaded pricing for %d models", len(_pricing_cache))
    return _pricing_cache


def calculate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Calculate cost in USD for a given model and token counts."""
    pricing = load_pricing()
    rates = pricing.get(model)
    if not rates:
        # Try fuzzy match — strip provider prefix
        short_name = model.split("/")[-1] if "/" in model else model
        for key, val in pricing.items():
            if key.endswith(short_name) or short_name in key:
                rates = val
                break

    if not rates:
        logger.debug("No pricing found for model '%s', returning 0 cost", model)
        return 0.0

    input_cost = (tokens_in / 1_000_000) * rates["input_cost_per_1m"]
    output_cost = (tokens_out / 1_000_000) * rates["output_cost_per_1m"]
    return input_cost + output_cost


def clear_cache() -> None:
    """Clear the cached pricing data (useful for testing)."""
    global _pricing_cache
    _pricing_cache = None
