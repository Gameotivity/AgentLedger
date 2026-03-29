"""Background task scheduler — runs waste detection, routing analysis, and budget checks."""

from __future__ import annotations

import asyncio
import logging

from app.database import async_session
from app.workers.waste_detector import run_waste_detection
from app.workers.routing_advisor import generate_recommendations
from app.workers.budget_monitor import check_budgets

logger = logging.getLogger("agentledger.scheduler")


async def run_hourly_jobs(project_id: str = "default") -> None:
    """Run all hourly background jobs."""
    async with async_session() as db:
        logger.info("Running hourly jobs for project: %s", project_id)

        waste_count = await run_waste_detection(db, project_id)
        logger.info("Waste detection: %d flags", waste_count)

        rec_count = await generate_recommendations(db, project_id)
        logger.info("Routing advisor: %d recommendations", rec_count)

        alert_count = await check_budgets(db)
        logger.info("Budget monitor: %d alerts", alert_count)


async def scheduler_loop(interval_seconds: int = 3600) -> None:
    """Main scheduler loop — runs jobs at the configured interval."""
    logger.info("Scheduler started (interval: %ds)", interval_seconds)
    while True:
        try:
            await run_hourly_jobs()
        except Exception as exc:
            logger.error("Scheduler error: %s", exc, exc_info=True)
        await asyncio.sleep(interval_seconds)
