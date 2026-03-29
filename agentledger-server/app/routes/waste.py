"""GET /waste — All waste flags across project."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import WasteFlag
from app.models.schemas import WasteFlagOut

router = APIRouter()


@router.get("/waste", response_model=list[WasteFlagOut])
async def list_waste(
    project: str = Query("default"),
    waste_type: str | None = Query(None, description="Filter: retry_loop, over_qualified_model, context_bloat, idle_heartbeat"),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """All waste flags across project. Sorted by estimated waste USD."""
    query = (
        select(WasteFlag)
        .where(WasteFlag.project_id == project)
        .order_by(WasteFlag.estimated_waste_usd.desc())
        .limit(limit)
    )
    if waste_type:
        query = query.where(WasteFlag.waste_type == waste_type)

    result = await db.execute(query)
    flags = result.scalars().all()

    return [
        WasteFlagOut(
            id=str(f.id),
            agent_name=f.agent_name,
            task_name=f.task_name,
            waste_type=f.waste_type,
            estimated_waste_usd=round(f.estimated_waste_usd, 4),
            suggestion=f.suggestion,
            created_at=f.created_at,
        )
        for f in flags
    ]
