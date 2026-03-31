"""GET/POST /shapley — Shapley cost attribution endpoints."""

from __future__ import annotations


from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.schemas import ShapleyOut, ShapleyReport
from app.models.tables import ShapleyAttribution
from app.workers.shapley_engine import compute_shapley_attribution
from app.workers.sir_router import compute_sir_routing

router = APIRouter()


@router.post("/shapley", response_model=ShapleyReport)
async def compute_shapley(
    project: str = Query("default"),
    topology: str | None = Query(None, description="Override: pipeline|tree|debate"),
    supervisor: str | None = Query(None, description="Supervisor agent for tree topology"),
    quality_threshold: float = Query(0.75, description="Min quality for SIR routing"),
    db: AsyncSession = Depends(get_db),
):
    """Compute Shapley cost attribution and SIR routing recommendations.

    Runs the full attribution pipeline:
    1. Loads agent stats from events
    2. Loads topology from agent_edges (or uses override)
    3. Computes Shapley values using closed-form formulas
    4. Runs SIR routing to find optimal model assignments
    """
    results = await compute_shapley_attribution(
        db, project, topology_override=topology, supervisor=supervisor,
    )

    # Run SIR routing
    sir_results = await compute_sir_routing(
        db, project, quality_threshold=quality_threshold, topology=topology,
    )

    total_cost = sum(r.shapley_value for r in results)

    return ShapleyReport(
        project_id=project,
        topology=topology or "auto",
        total_cost=round(total_cost, 6),
        agents=[
            ShapleyOut(
                agent_name=r.agent_name,
                topology=r.details.get("method", topology or "pipeline")
                if r.details else (topology or "pipeline"),
                direct_cost=r.direct_cost,
                propagation_cost=r.propagation_cost,
                shapley_value=r.shapley_value,
                shapley_pct=r.shapley_pct,
                details=r.details,
            )
            for r in results
        ],
        sir_recommendations=[
            {
                "agent_name": s.agent_name,
                "current_model": s.current_model,
                "recommended_model": s.recommended_model,
                "shapley_value": s.shapley_value,
                "downgrade_score": s.downgrade_score,
                "quality_sensitivity": s.quality_sensitivity,
                "monthly_savings": s.monthly_savings,
                "confidence": s.confidence,
                "reasoning": s.reasoning,
            }
            for s in sir_results
        ],
    )


@router.get("/shapley", response_model=list[ShapleyOut])
async def get_shapley(
    project: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Get cached Shapley attributions (from last computation)."""
    result = await db.execute(
        select(ShapleyAttribution)
        .where(ShapleyAttribution.project_id == project)
        .order_by(ShapleyAttribution.shapley_value.desc())
    )
    rows = result.scalars().all()

    return [
        ShapleyOut(
            agent_name=r.agent_name,
            topology=r.topology,
            direct_cost=r.direct_cost,
            propagation_cost=r.propagation_cost,
            shapley_value=r.shapley_value,
            shapley_pct=r.shapley_pct,
            details=r.details_json,
        )
        for r in rows
    ]
