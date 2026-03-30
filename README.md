# AgentLedger

**Your agents are burning money. AgentLedger shows you exactly where.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![CI](https://github.com/Gameotivity/AgentLedger/actions/workflows/ci.yml/badge.svg)](https://github.com/Gameotivity/AgentLedger/actions)
[![PyPI](https://img.shields.io/pypi/v/agentledger.svg)](https://pypi.org/project/agentledger/)

---

**LiteLLM tells you how much you spent. AgentLedger tells you *why*.**

Per-agent. Per-task. With waste detection and savings recommendations.

---

## Table of Contents

- [The Problem](#the-problem)
- [How AgentLedger Works](#how-agentledger-works)
- [Setup](#setup)
- [Integration Path 1: @track Decorator (Any Framework)](#integration-path-1-track-decorator-any-framework)
- [Integration Path 2: LiteLLM Callback (Recommended for Teams)](#integration-path-2-litellm-callback-recommended-for-teams)
- [Integration Path 3: LangGraph](#integration-path-3-langgraph)
- [Integration Path 4: CrewAI](#integration-path-4-crewai)
- [Integration Path 5: Google ADK](#integration-path-5-google-adk)
- [Integration Path 6: Direct HTTP API (Any Language)](#integration-path-6-direct-http-api-any-language)
- [Features](#features)
- [Budget Guardrails](#budget-guardrails)
- [Waste Detection Deep Dive](#waste-detection-deep-dive)
- [CLI Reference](#cli-reference)
- [API Reference](#api-reference)
- [Production Deployment](#production-deployment)
- [Architecture Deep Dive](#architecture-deep-dive)
- [Model Pricing Database](#model-pricing-database)
- [Security & Privacy](#security--privacy)
- [Contributing](#contributing)

---

## The Problem

A typical unoptimized multi-agent system processes 10-50x more tokens than it needs to. Developers discover $180/month bills with zero visibility into which agent, which task, or which model drove those costs.

Existing tools (LiteLLM, Helicone, Langfuse) work at the API call level. They see individual requests. **They don't understand agents.**

| What LiteLLM Sees | What You Need |
|---|---|
| `POST /v1/chat`, model=claude-sonnet, 4200 tokens, $0.03 | `research-agent > competitor-analysis > step 3 of 7`, $0.03 |
| Total spend: $487/month | research-agent: $210, writer-agent: $89, code-agent: $188. Retries: $74 wasted |
| Avg cost per request: $0.04 | This task used Opus but Haiku would work. Savings: $540/month |

---

## How AgentLedger Works

```
Your Agent Code                AgentLedger SDK              AgentLedger Server
┌─────────────────┐           ┌───────────────┐            ┌──────────────────┐
│                 │  @track   │               │  HTTP POST │                  │
│ research-agent  │──────────>│ Event Buffer  │───────────>│ /api/v1/events   │
│   task: search  │           │ (batch of 50) │            │                  │
│   model: sonnet │           │               │            │ PostgreSQL/SQLite│
│   tokens: 4200  │           │ Falls back to │            │                  │
│   cost: $0.03   │           │ local .jsonl  │            │ Waste Detector   │
│                 │           │ if server is  │            │ Routing Advisor  │
│ writer-agent    │──────────>│ unreachable   │            │ Budget Monitor   │
│   task: draft   │           │               │            │                  │
│   model: opus   │           └───────────────┘            └──────────────────┘
│   cost: $0.21   │                                               │
└─────────────────┘                                               v
                                                          CLI / Dashboard / API
```

**Key concepts:**

- **Event** — A single LLM API call (model, tokens, cost, latency)
- **Task span** — A group of LLM calls under one `@track` scope
- **Agent** — The logical entity making the calls (research-agent, writer-agent, etc.)
- **Tracking context** — A thread-local stack that associates LLM calls with their agent/task

The SDK buffers events in memory and ships them in batches (default: every 50 events or 5 seconds). If the server is unreachable, events are written to a local `.jsonl` file as fallback.

---

## Setup

### Install the SDK

```bash
pip install agentledger
```

### Start the server (pick one)

**Option A: Local dev (SQLite, zero dependencies)**
```bash
cd agentledger-server
pip install fastapi uvicorn sqlalchemy aiosqlite pydantic pydantic-settings greenlet
PYTHONPATH=. uvicorn app.main:app --port 8100
```

**Option B: Docker Compose (PostgreSQL + Redis)**
```bash
docker compose up
```

**Option C: Skip the server entirely**

The SDK works standalone — events are written to `agentledger_events.jsonl` as fallback. Useful for local development.

### Install the CLI (optional)

```bash
pip install agentledger-cli
```

### Verify

```bash
curl http://localhost:8100/health
# {"status":"ok","service":"agentledger"}

agentledger status
```

---

## Integration Path 1: @track Decorator (Any Framework)

**Best for:** Custom agent code, any framework, quick starts.

The simplest integration. Wrap your agent functions with `@track` and record LLM calls.

### Initialize

```python
from agentledger import track, ledger

ledger.init(
    project="my-saas",                      # Groups agents under one project
    server_url="http://localhost:8100",      # Your AgentLedger server
    # api_key="al_xxx",                     # Optional: auth key
    # fallback_path="events.jsonl",         # Optional: custom fallback path
    # batch_size=50,                        # Ship every N events
    # flush_interval=5.0,                   # Or every N seconds
)
```

### Decorate your agent functions

```python
@track(agent="research-agent", task="competitor-analysis")
def run_research(query: str) -> str:
    """Everything inside this function is attributed to research-agent."""

    # Your existing code — call any LLM however you want
    response = call_my_llm(query)

    # Manually record the call
    from agentledger.tracker import get_current_context
    ctx = get_current_context()
    ctx.record_call(
        model="claude-sonnet-4-6",
        tokens_in=1500,
        tokens_out=800,
        cost_usd=0.0165,       # Or let AgentLedger compute from pricing DB
        latency_ms=450.0,
        prompt_hash="abc123",  # Optional: enables retry detection
        status="success",      # or "error"
    )

    return response
```

### Use the pricing engine (optional)

Instead of calculating cost yourself:

```python
from agentledger.pricing import calculate_cost

cost = calculate_cost("claude-sonnet-4-6", tokens_in=1500, tokens_out=800)
# Returns: 0.0165 (based on pricing/models.json)
```

### Context manager (alternative to decorator)

For more granular control:

```python
from agentledger import track_context

def run_pipeline():
    with track_context(agent="research-agent", task="search") as ctx:
        response = llm.call(...)
        ctx.record_call(model="gpt-4o", tokens_in=500, tokens_out=200, cost_usd=0.003, latency_ms=300)

    with track_context(agent="writer-agent", task="draft") as ctx:
        response = llm.call(...)
        ctx.record_call(model="claude-opus-4-6", tokens_in=2000, tokens_out=1000, cost_usd=0.105, latency_ms=800)
```

### Flush on shutdown

```python
# At app shutdown — ships any remaining buffered events
ledger.flush()
```

---

## Integration Path 2: LiteLLM Callback (Recommended for Teams)

**Best for:** Teams already using LiteLLM. Zero manual recording needed.

This is the **recommended integration for businesses**. If you use `litellm.completion()`, the callback automatically captures every call's model, tokens, cost, and latency — no manual `record_call()` needed.

### Option A: LiteLLM SDK

```python
import litellm
from agentledger import track, ledger
from agentledger.integrations.litellm import AgentLedgerCallback

# Initialize
ledger.init(project="my-saas")
litellm.callbacks = [AgentLedgerCallback()]  # <-- one line, captures everything

# With @track — agent context comes from the decorator
@track(agent="research-agent", task="competitor-analysis")
def run_research(query: str) -> str:
    # Every litellm.completion() call inside here is auto-tracked
    response = litellm.completion(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": query}],
    )
    return response.choices[0].message.content

# Without @track — pass agent context via metadata
def run_standalone():
    response = litellm.completion(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Summarize revenue"}],
        metadata={"agent": "finance-agent", "task": "quarterly-report"},
    )
    return response.choices[0].message.content
```

**How it works under the hood:**
1. LiteLLM calls `async_log_success_event` after every completion
2. The callback reads `kwargs["response_cost"]` (LiteLLM pre-calculates this)
3. It reads `response_obj.usage.prompt_tokens` and `completion_tokens`
4. If a `@track` context is active, it records to that context
5. If not, it reads agent/task from `metadata` and records directly to the ledger

### Option B: LiteLLM Proxy (Team Gateway)

If your team shares a LiteLLM Proxy, add AgentLedger to `config.yaml`:

```yaml
# litellm_config.yaml
model_list:
  - model_name: claude-sonnet
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY
  - model_name: gpt-4o
    litellm_params:
      model: openai/gpt-4o
      api_key: os.environ/OPENAI_API_KEY

litellm_settings:
  callbacks: agentledger.integrations.litellm.callback_instance
```

Start the proxy:
```bash
pip install litellm agentledger
litellm --config litellm_config.yaml
```

Every request through the proxy is now tracked. Developers tag their agents:

```python
# Any team member's code
response = litellm.completion(
    model="claude-sonnet",
    messages=[...],
    metadata={"agent": "my-agent", "task": "my-task"},
    api_base="http://your-proxy:4000",
)
```

---

## Integration Path 3: LangGraph

**Best for:** LangGraph / LangChain workflows.

```python
from agentledger import track, ledger
from agentledger.integrations import langgraph_callback

ledger.init(project="my-saas")
callback = langgraph_callback()

# Compile your graph with the callback
app = workflow.compile(callbacks=[callback])

@track(agent="research-agent", task="web-search")
def run_agent(query: str):
    return app.invoke({"query": query})

result = run_agent("Latest AI frameworks")
ledger.flush()
```

The callback intercepts `on_llm_start`, `on_chat_model_start`, `on_llm_end`, and `on_llm_error` from LangChain's callback system and extracts model, tokens, cost, and latency automatically.

---

## Integration Path 4: CrewAI

**Best for:** CrewAI multi-agent setups.

```python
from crewai import Agent, Task, Crew
from agentledger import track, ledger
from agentledger.integrations import crewai_callback

ledger.init(project="my-saas")

researcher = Agent(role="Researcher", goal="Find data", ...)
writer = Agent(role="Writer", goal="Write reports", ...)

@track(agent="crew-pipeline", task="research-and-write")
def run_crew():
    crew = Crew(
        agents=[researcher, writer],
        tasks=[...],
        callbacks=[crewai_callback()],
    )
    return crew.kickoff()

result = run_crew()
ledger.flush()
```

---

## Integration Path 5: Google ADK

**Best for:** Google Agent Development Kit.

```python
from agentledger import track, ledger
from agentledger.integrations import adk_callback

ledger.init(project="my-saas")

@track(agent="search-agent", task="web-search")
def run_adk_agent(query: str):
    agent = Agent(
        model="gemini-2.5-pro",
        callbacks=[adk_callback()],
    )
    return agent.run(query)
```

---

## Integration Path 6: Direct HTTP API (Any Language)

**Best for:** Non-Python apps (Node.js, Go, Rust, etc.), or when you want full control.

Skip the SDK entirely and POST events directly.

### Ingest events

```bash
curl -X POST http://localhost:8100/api/v1/events \
  -H "Content-Type: application/json" \
  -d '{
    "events": [
      {
        "project": "my-saas",
        "type": "llm_call",
        "agent_name": "research-agent",
        "task_name": "competitor-analysis",
        "task_id": "task-001",
        "step": 1,
        "model": "claude-sonnet-4-6",
        "tokens_in": 1500,
        "tokens_out": 800,
        "cost_usd": 0.0165,
        "latency_ms": 450,
        "prompt_hash": "a1b2c3d4",
        "status": "success"
      }
    ]
  }'
```

### Query results

```bash
# List agents with cost summaries
curl "http://localhost:8100/api/v1/agents?project=my-saas"

# Agent P&L (cost by task, model, and day)
curl "http://localhost:8100/api/v1/agents/research-agent/costs?project=my-saas"

# Waste flags
curl "http://localhost:8100/api/v1/waste?project=my-saas"

# Routing recommendations
curl "http://localhost:8100/api/v1/recommendations?project=my-saas"

# Full dashboard
curl "http://localhost:8100/api/v1/dashboard?project=my-saas"
```

### Event schema reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project` | string | No (default: "default") | Project identifier |
| `type` | string | No (default: "llm_call") | `llm_call` or `task_span` |
| `agent_name` | string | **Yes** | Which agent made this call |
| `task_name` | string | No | What task this is part of |
| `task_id` | string | No | Groups calls within a task |
| `step` | int | No | Step number within a task |
| `model` | string | No | LLM model used |
| `tokens_in` | int | No (default: 0) | Input/prompt tokens |
| `tokens_out` | int | No (default: 0) | Output/completion tokens |
| `cost_usd` | float | No (default: 0) | Cost in USD (server computes from pricing DB if 0) |
| `latency_ms` | float | No (default: 0) | Response time in milliseconds |
| `prompt_hash` | string | No | Hash of prompt (for retry detection) |
| `status` | string | No (default: "success") | `success`, `error`, `retry` |
| `error` | string | No | Error message if failed |
| `metadata` | object | No | Any additional key-value pairs |

---

## Features

### Per-Agent Cost Attribution
Every LLM call tagged to a specific agent and task. No more guessing which part of your pipeline is expensive.

### Waste Detection
Automatically flags waste patterns — [see deep dive below](#waste-detection-deep-dive).

### Routing Recommendations
Analyzes your actual usage patterns and tells you exactly which tasks can use cheaper models — with estimated monthly savings.

### Budget Guardrails
Set per-project or per-agent spending limits with webhook alerts — [see setup below](#budget-guardrails).

### Works With Your Stack
Not another gateway. AgentLedger is a **cost intelligence layer** that works WITH whatever you already use:
- **LiteLLM** — official `CustomLogger` callback (SDK + Proxy)
- **LangGraph / LangChain** — native callback handler
- **CrewAI** — task/step callback
- **Google ADK** — request/response hooks
- **Any custom framework** — `@track` decorator + context manager
- **Any language** — direct HTTP API

### Self-Hostable
`docker compose up` and you own your data. No vendor lock-in. No usage-based pricing on your observability.

---

## Budget Guardrails

### Create a budget

```bash
# Project-wide: $100/month, alert at 80%
curl -X POST http://localhost:8100/api/v1/budgets \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "my-saas",
    "limit_usd": 100,
    "period": "monthly",
    "alert_threshold_pct": 0.8,
    "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  }'

# Per-agent: research-agent gets $30/month
curl -X POST http://localhost:8100/api/v1/budgets \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "my-saas",
    "agent_name": "research-agent",
    "limit_usd": 30,
    "period": "monthly",
    "alert_threshold_pct": 0.8,
    "webhook_url": "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
  }'
```

### How alerts work

The budget monitor runs hourly and checks each budget:
1. Calculates current spend for the period (daily/weekly/monthly)
2. If spend >= `alert_threshold_pct` of `limit_usd`, fires a webhook

**Webhook payload (works with Slack, PagerDuty, Opsgenie, or any HTTP endpoint):**
```json
{
  "text": "AgentLedger Budget Alert: research-agent in project 'my-saas' has used 85% of its monthly budget ($25.50 / $30.00)",
  "project": "my-saas",
  "agent": "research-agent",
  "current_spend": 25.50,
  "limit": 30.0,
  "period": "monthly",
  "pct_used": 85.0
}
```

---

## Waste Detection Deep Dive

The waste detector runs hourly and flags three patterns:

### 1. Retry Loops (`retry_loop`)
- Same `prompt_hash` appears 3+ times within a single task
- **Waste** = cost of all calls beyond the first one
- **Fix:** add error handling, caching, or circuit breakers

### 2. Over-Qualified Models (`over_qualified_model`)
- Tier-3 model (Opus, GPT-4 Turbo, o3) used but average output < 500 tokens
- Short outputs suggest the task doesn't need heavy reasoning
- **Fix:** switch to a tier-1 model (Haiku, GPT-4o Mini, Flash)

### 3. Context Bloat (`context_bloat`)
- Input tokens grow consistently across steps (70%+ of steps show growth)
- Context window is being stuffed with accumulated history
- **Fix:** summarize context between steps, or use a sliding window

### Model Tiers

| Tier | Cost Range | Models | Use For |
|------|-----------|--------|---------|
| 1 (cheap) | $0.10-$1/M | Haiku, GPT-4o Mini, Gemini Flash, DeepSeek | Classification, extraction, simple Q&A |
| 2 (mid) | $1-$5/M | Sonnet, GPT-4o, Gemini Pro | General tasks, summarization, coding |
| 3 (expensive) | $10-$75/M | Opus, GPT-4 Turbo, o3 | Complex reasoning, analysis, creative work |

### Trigger waste detection manually

```python
import asyncio
from app.database import async_session
from app.workers.waste_detector import run_waste_detection
from app.workers.routing_advisor import generate_recommendations

async def run_analysis():
    async with async_session() as db:
        waste_count = await run_waste_detection(db, "my-saas")
        print(f"Found {waste_count} waste flags")

        rec_count = await generate_recommendations(db, "my-saas")
        print(f"Generated {rec_count} routing recommendations")

asyncio.run(run_analysis())
```

---

## CLI Reference

```bash
agentledger --project my-saas status      # Dashboard overview
agentledger --project my-saas agents      # Per-agent cost table
agentledger --project my-saas waste       # Waste flags sorted by $ impact
agentledger --project my-saas recommend   # Routing recommendations

# Override server URL
agentledger --server http://prod:8100 --project my-saas status

# Environment variables work too
export AGENTLEDGER_SERVER=http://prod:8100
export AGENTLEDGER_PROJECT=my-saas
agentledger status
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/events` | Batch ingest events from SDK |
| `GET` | `/api/v1/agents` | List agents with cost summaries |
| `GET` | `/api/v1/agents/{name}/costs` | Per-agent P&L by task, model, and time |
| `GET` | `/api/v1/waste` | Waste flags sorted by $ impact |
| `GET` | `/api/v1/recommendations` | Model routing recommendations with savings |
| `POST` | `/api/v1/budgets` | Create/update budget guardrails |
| `GET` | `/api/v1/budgets` | List budgets with current spend |
| `GET` | `/api/v1/dashboard` | Full dashboard: spend, agents, waste, trends |
| `GET` | `/health` | Health check |

Interactive Swagger UI at `http://localhost:8100/docs`.

---

## Production Deployment

### Docker Compose (recommended)

```bash
export AGENTLEDGER_API_KEY="your-secret-key"
export AGENTLEDGER_DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/agentledger"
docker compose up -d
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENTLEDGER_DATABASE_URL` | `sqlite+aiosqlite:///./agentledger.db` | Database connection string |
| `AGENTLEDGER_REDIS_URL` | `redis://localhost:6379/0` | Redis for event queuing |
| `AGENTLEDGER_API_KEY` | None | Require auth on all API requests |
| `AGENTLEDGER_CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed CORS origins |
| `AGENTLEDGER_BATCH_MAX_SIZE` | 1000 | Max events per batch POST |
| `AGENTLEDGER_LOG_LEVEL` | INFO | Logging level |

### SDK Production Config

```python
ledger.init(
    project="my-saas",
    server_url="https://agentledger.internal.company.com",
    api_key="al_production_key_here",
    batch_size=100,          # Larger batches = fewer HTTP calls
    flush_interval=10.0,     # Ship every 10 seconds
    fallback_path="/var/log/agentledger_fallback.jsonl",
)
```

---

## Architecture Deep Dive

### Data Flow

```
 1. Your code calls @track(agent="x", task="y")
 2. SDK creates a _TrackingContext on a thread-local stack
 3. Inside the function, LLM calls are intercepted by framework callbacks
 4. Each call → ctx.record_call() → ledger.record() → buffer
 5. Buffer fills to batch_size OR flush_interval fires
 6. SDK POSTs batch to /api/v1/events
 7. Server computes cost (if not provided) from pricing DB
 8. Server writes events to PostgreSQL/SQLite
 9. Hourly workers analyze events:
    - Waste detector flags retry loops, over-qualified models, context bloat
    - Routing advisor finds cheaper model alternatives
    - Budget monitor checks spend vs limits, fires webhooks
10. Results available via API, CLI, or dashboard
```

### Database Tables

| Table | Purpose |
|-------|---------|
| `events` | Raw event log (immutable, append-only) |
| `agent_summaries` | Pre-aggregated cost/token summaries per agent per period |
| `waste_flags` | Waste detection results with $ estimates and fix suggestions |
| `routing_recommendations` | Model swap recommendations with monthly savings |
| `budgets` | Spending limits with webhook alert config |
| `model_pricing` | Per-model cost rates (synced from pricing/models.json) |

### Thread Safety & Nested Tracking

The tracking context uses `threading.local()` for thread-safe nested scoping:

```python
@track(agent="orchestrator", task="pipeline")
def run_pipeline():
    research = run_research("query")   # inner @track → research-agent
    report = write_report(research)    # inner @track → writer-agent
```

Each call is attributed to the innermost active context.

### Fallback Behavior

If the server is unreachable, events are appended to a local JSON-lines file:

```
{"type":"llm_call","agent_name":"research-agent","model":"claude-sonnet-4-6","cost_usd":0.0165,...}
```

Replay later:
```bash
cat agentledger_events.jsonl | while read line; do
  echo "{\"events\":[$line]}" | curl -X POST http://localhost:8100/api/v1/events \
    -H "Content-Type: application/json" -d @-
done
```

### Project Structure

```
AgentLedger/
  agentledger-sdk/           # Python SDK (PyPI: agentledger)
    agentledger/
      integrations/          # LangGraph, CrewAI, ADK, LiteLLM callbacks
      tracker.py             # @track decorator + context manager
      ledger.py              # Event buffering + async shipping
      pricing.py             # Model cost calculator
  agentledger-server/        # FastAPI backend
    app/
      routes/                # API endpoints
      workers/               # Waste detector, routing advisor, budget monitor
      models/                # SQLAlchemy models + Pydantic schemas
  agentledger-cli/           # Terminal dashboard (rich tables)
  pricing/                   # Community-maintained model pricing DB (25+ models)
  examples/                  # Integration examples (basic, LangGraph, LiteLLM)
  docker-compose.yml         # One-command setup (Postgres + Redis + API)
```

---

## Model Pricing Database

Community-maintained pricing in `pricing/models.json` covering 25+ models across 6 providers:

| Provider | Models |
|----------|--------|
| Anthropic | Claude Opus 4.6, Sonnet 4.6, Haiku 4.5 |
| OpenAI | GPT-4o, GPT-4.1, o3, o4-mini |
| Google | Gemini 2.5 Pro/Flash, 2.0 Flash |
| DeepSeek | V3, R1 |
| Meta | Llama 3.3, Llama 4 Maverick |
| Mistral | Large, Small |

PRs to update pricing are always welcome. Costs change frequently.

---

## Security & Privacy

AgentLedger tracks **cost metadata only**. It does NOT store prompts, completions, or any LLM content. The `prompt_hash` is a truncated MD5 used solely for retry detection — the original prompt cannot be reconstructed. See [SECURITY.md](SECURITY.md) for details.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). High-impact areas:

1. **Update pricing** — keep `pricing/models.json` current
2. **Add integrations** — AutoGen, Semantic Kernel, Haystack
3. **Improve waste detection** — new patterns and heuristics
4. **Build the React dashboard** — highest-impact frontend work

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

**Stop guessing. Start measuring.**
