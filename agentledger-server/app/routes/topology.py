"""POST /topology — Declare agent interaction graph for Shapley attribution."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import AgentEdge
from app.models.schemas import AgentEdgeOut

router = APIRouter()


@router.post("/topology")
async def declare_topology(
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """Declare or update agent interaction topology.

    Accepts a full topology declaration: project_id, topology type,
    agent list, and edges. Replaces any existing edges for the project.
    """
    project_id = payload.get("project_id", "default")
    topology = payload.get("topology", "pipeline")
    edges = payload.get("edges", [])
    supervisor = payload.get("supervisor")

    # Clear existing edges for this project
    existing = await db.execute(
        select(AgentEdge).where(AgentEdge.project_id == project_id)
    )
    for edge in existing.scalars().all():
        await db.delete(edge)

    # Insert new edges
    created = 0
    for e in edges:
        db.add(AgentEdge(
            project_id=project_id,
            source_agent=e["source_agent"],
            target_agent=e["target_agent"],
            topology=e.get("topology", topology),
            context_retention=e.get("context_retention", 1.0),
        ))
        created += 1

    await db.commit()

    return {
        "project_id": project_id,
        "topology": topology,
        "edges_created": created,
        "supervisor": supervisor,
    }


@router.get("/topology", response_model=list[AgentEdgeOut])
async def get_topology(
    project: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """Get the current agent topology for a project."""
    result = await db.execute(
        select(AgentEdge).where(AgentEdge.project_id == project)
    )
    edges = result.scalars().all()
    return [
        AgentEdgeOut(
            source_agent=e.source_agent,
            target_agent=e.target_agent,
            topology=e.topology,
            context_retention=e.context_retention,
        )
        for e in edges
    ]
