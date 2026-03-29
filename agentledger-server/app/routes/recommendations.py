"""GET /recommendations — Model routing recommendations with estimated savings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import RoutingRecommendation
from app.models.schemas import RecommendationOut

router = APIRouter()


@router.get("/recommendations", response_model=list[RecommendationOut])
async def list_recommendations(
    project: str = Query("default"),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Model routing recommendations with estimated savings."""
    result = await db.execute(
        select(RoutingRecommendation)
        .where(RoutingRecommendation.project_id == project)
        .order_by(RoutingRecommendation.estimated_monthly_savings.desc())
        .limit(limit)
    )
    recs = result.scalars().all()

    return [
        RecommendationOut(
            agent_name=r.agent_name,
            task_pattern=r.task_pattern,
            current_model=r.current_model,
            recommended_model=r.recommended_model,
            estimated_monthly_savings=round(r.estimated_monthly_savings, 2),
            confidence=round(r.confidence, 2),
            reasoning=r.reasoning,
        )
        for r in recs
    ]
