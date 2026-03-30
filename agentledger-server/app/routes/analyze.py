"""POST /analyze — Manually trigger waste detection and routing analysis."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.workers.waste_detector import run_waste_detection
from app.workers.routing_advisor import generate_recommendations
from app.workers.budget_monitor import check_budgets

router = APIRouter()


@router.post("/analyze")
async def run_analysis(
    project: str = Query("default"),
    db: AsyncSession = Depends(get_db),
):
    """Run waste detection, routing analysis, and budget checks on demand."""
    waste_count = await run_waste_detection(db, project)
    rec_count = await generate_recommendations(db, project)
    alert_count = await check_budgets(db)

    return {
        "waste_flags": waste_count,
        "recommendations": rec_count,
        "budget_alerts": alert_count,
    }
