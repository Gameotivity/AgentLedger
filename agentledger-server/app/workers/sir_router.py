"""Shapley-Informed Routing (SIR) — Algorithm 1 from the paper.

Given Shapley attributions, SIR identifies which agents to downgrade
to cheaper models by computing a downgrade score:

    d_k = Sh_k(v) / (σ_k + δ)

Where:
  - Sh_k = Shapley cost attribution for agent k
  - σ_k = quality sensitivity (∂Q/∂q_k) — estimated via perturbation
  - δ = regularizer to avoid division by zero

Agents with high cost attribution but low quality sensitivity are
downgraded first, achieving near-optimal cost reduction in poly time.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Event
from app.workers.shapley_engine import (
    compute_shapley_attribution,
)

logger = logging.getLogger("agentledger.sir")

_PRICING_FILE = (
    Path(__file__).resolve().parent.parent.parent.parent / "pricing" / "models.json"
)


@dataclass
class ModelOption:
    name: str
    provider: str
    cin: float  # $/token input
    cout: float  # $/token output
    tier: int
    quality: float  # estimated quality score


@dataclass
class SIRRecommendation:
    agent_name: str
    current_model: str
    recommended_model: str
    shapley_value: float
    downgrade_score: float
    quality_sensitivity: float
    estimated_cost_before: float
    estimated_cost_after: float
    monthly_savings: float
    confidence: float
    reasoning: str


def _load_models() -> list[ModelOption]:
    """Load available models with quality estimates from pricing JSON."""
    if not _PRICING_FILE.exists():
        return []
    with _PRICING_FILE.open() as f:
        data = json.load(f)

    # Quality mapping by tier (from paper Table 1)
    tier_quality = {1: 0.62, 2: 0.78, 3: 0.91, 4: 0.95}

    models = []
    for entry in data.get("models", []):
        tier = entry.get("tier", 2)
        models.append(ModelOption(
            name=entry["model"],
            provider=entry.get("provider", "unknown"),
            cin=entry.get("input_cost_per_1m", 0) / 1_000_000,
            cout=entry.get("output_cost_per_1m", 0) / 1_000_000,
            tier=tier,
            quality=tier_quality.get(tier, 0.7),
        ))
    return models


def _estimate_quality_sensitivity(
    agent_name: str,
    avg_output_tokens: float,
    call_count: int,
    model_tier: int,
) -> float:
    """Estimate quality sensitivity σ_k via heuristic perturbation.

    Agents that produce long, complex outputs are more quality-sensitive.
    Agents with short outputs (classification, routing) are less sensitive.
    """
    # Base sensitivity from output complexity
    if avg_output_tokens > 2000:
        base = 0.9  # Complex reasoning — needs strong model
    elif avg_output_tokens > 1000:
        base = 0.7
    elif avg_output_tokens > 500:
        base = 0.5
    elif avg_output_tokens > 200:
        base = 0.3
    else:
        base = 0.1  # Short outputs — likely classification/routing

    # Scale by current tier (agents already on cheap models are less sensitive)
    tier_factor = {1: 0.5, 2: 0.8, 3: 1.0, 4: 1.0}
    return base * tier_factor.get(model_tier, 0.8)


async def compute_sir_routing(
    db: AsyncSession,
    project_id: str,
    quality_threshold: float = 0.75,
    topology: str | None = None,
) -> list[SIRRecommendation]:
    """Run Shapley-Informed Routing (Algorithm 1).

    1. Start with current model assignments
    2. Compute Shapley values for all agents
    3. Compute quality sensitivity σ_k for each agent
    4. Compute downgrade score d_k = Sh_k / (σ_k + δ)
    5. Sort by d_k descending (highest = best downgrade candidate)
    6. For each agent, try switching to cheaper models
    7. Accept if quality constraint Q(π') >= Q*
    """
    # Step 1: Get current model assignments per agent
    result = await db.execute(
        select(
            Event.agent_name,
            Event.model,
            func.count(Event.id).label("cnt"),
            func.sum(Event.cost_usd).label("total_cost"),
            func.avg(Event.tokens_in).label("avg_in"),
            func.avg(Event.tokens_out).label("avg_out"),
        )
        .where(
            Event.project_id == project_id,
            Event.event_type == "llm_call",
            Event.model.isnot(None),
        )
        .group_by(Event.agent_name, Event.model)
    )
    rows = result.all()
    if not rows:
        return []

    # Aggregate to find primary model per agent
    agent_data: dict[str, dict] = {}
    for row in rows:
        name = row.agent_name
        if name not in agent_data or row.cnt > agent_data[name]["cnt"]:
            agent_data[name] = {
                "model": row.model,
                "cnt": int(row.cnt),
                "total_cost": float(row.total_cost or 0),
                "avg_out": float(row.avg_out or 0),
                "avg_in": float(row.avg_in or 0),
            }

    # Step 2: Compute Shapley values
    shapley_results = await compute_shapley_attribution(
        db, project_id, topology_override=topology,
    )
    shapley_map = {r.agent_name: r for r in shapley_results}

    # Load model catalog
    models = _load_models()
    model_map = {m.name: m for m in models}
    models_by_cost = sorted(models, key=lambda m: m.cin + m.cout)

    delta = 0.01  # regularizer
    recommendations: list[SIRRecommendation] = []

    # Steps 3-4: Compute downgrade scores
    scored_agents = []
    for name, data in agent_data.items():
        sh = shapley_map.get(name)
        if not sh:
            continue
        current = model_map.get(data["model"])
        if not current:
            continue

        sigma = _estimate_quality_sensitivity(
            name, data["avg_out"], data["cnt"], current.tier,
        )
        d_score = sh.shapley_value / (sigma + delta)
        scored_agents.append((name, data, sh, current, sigma, d_score))

    # Step 5: Sort by downgrade score (highest first = best candidates)
    scored_agents.sort(key=lambda x: x[5], reverse=True)

    # Track overall quality
    current_qualities = []
    for _, data, _, current, _, _ in scored_agents:
        current_qualities.append(current.quality)
    if not current_qualities:
        return []

    # Steps 6-7: Try downgrading each agent
    assigned: dict[str, ModelOption] = {}
    for name, data, sh, current, sigma, d_score in scored_agents:
        assigned[name] = current

    for name, data, sh, current, sigma, d_score in scored_agents:
        # Try cheaper models from cheapest upward
        for candidate in models_by_cost:
            if candidate.name == current.name:
                continue
            if candidate.tier >= current.tier:
                continue  # only downgrade

            # Check quality constraint: would switching this agent
            # drop overall quality below threshold?
            test_qualities = [
                (candidate.quality if n == name else assigned[n].quality)
                for n, _, _, _, _, _ in scored_agents
            ]
            new_avg_quality = sum(test_qualities) / len(test_qualities)

            if new_avg_quality >= quality_threshold:
                # Accept downgrade
                old_cost_per_call = (
                    current.cin * data["avg_in"] + current.cout * data["avg_out"]
                )
                new_cost_per_call = (
                    candidate.cin * data["avg_in"] + candidate.cout * data["avg_out"]
                )
                monthly_calls = data["cnt"] * 30
                monthly_savings = (old_cost_per_call - new_cost_per_call) * monthly_calls

                if monthly_savings >= 0.50:  # Worth recommending
                    confidence = min(
                        0.95,
                        0.5 + (1 - sigma) * 0.3 + (d_score > 1) * 0.15,
                    )
                    recommendations.append(SIRRecommendation(
                        agent_name=name,
                        current_model=current.name,
                        recommended_model=candidate.name,
                        shapley_value=sh.shapley_value,
                        downgrade_score=round(d_score, 4),
                        quality_sensitivity=round(sigma, 4),
                        estimated_cost_before=round(
                            old_cost_per_call * monthly_calls, 2
                        ),
                        estimated_cost_after=round(
                            new_cost_per_call * monthly_calls, 2
                        ),
                        monthly_savings=round(monthly_savings, 2),
                        confidence=round(confidence, 2),
                        reasoning=(
                            f"Shapley attribution ${sh.shapley_value:.4f} "
                            f"(propagation: ${sh.propagation_cost:.4f}). "
                            f"Quality sensitivity {sigma:.2f} — "
                            f"{'low' if sigma < 0.4 else 'moderate' if sigma < 0.7 else 'high'}. "
                            f"Downgrade score {d_score:.2f}. "
                            f"Switch {current.name} → {candidate.name} "
                            f"saves ${monthly_savings:.2f}/mo."
                        ),
                    ))
                    assigned[name] = candidate
                break  # Accept first viable downgrade

    # Sort by savings
    recommendations.sort(key=lambda r: r.monthly_savings, reverse=True)

    logger.info(
        "SIR computed %d routing recommendations for project %s "
        "(total savings: $%.2f/mo)",
        len(recommendations),
        project_id,
        sum(r.monthly_savings for r in recommendations),
    )

    return recommendations
