"""AgentLedger API server entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine
from app.models import Base
from app.routes import events, agents, waste, recommendations, budgets, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="AgentLedger",
    description="Agent-aware cost intelligence for AI. Know exactly where your agent money goes.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(events.router, prefix="/api/v1", tags=["events"])
app.include_router(agents.router, prefix="/api/v1", tags=["agents"])
app.include_router(waste.router, prefix="/api/v1", tags=["waste"])
app.include_router(recommendations.router, prefix="/api/v1", tags=["recommendations"])
app.include_router(budgets.router, prefix="/api/v1", tags=["budgets"])
app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "agentledger"}
