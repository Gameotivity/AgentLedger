# AgentLedger

**Your agents are burning money. AgentLedger shows you exactly where.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![CI](https://github.com/Gameotivity/AgentLedger/actions/workflows/ci.yml/badge.svg)](https://github.com/Gameotivity/AgentLedger/actions)
[![PyPI](https://img.shields.io/pypi/v/agentledger.svg)](https://pypi.org/project/agentledger/)

---

**LiteLLM tells you how much you spent. AgentLedger tells you *why*.**

Per-agent. Per-task. With waste detection and savings recommendations.

## The Problem

A typical unoptimized multi-agent system processes 10-50x more tokens than it needs to. Developers discover $180/month bills with zero visibility into which agent, which task, or which model drove those costs.

Existing tools (LiteLLM, Helicone, Langfuse) work at the API call level. They see individual requests. **They don't understand agents.**

| What LiteLLM Sees | What You Need |
|---|---|
| `POST /v1/chat`, model=claude-sonnet, 4200 tokens, $0.03 | `research-agent > competitor-analysis > step 3 of 7`, $0.03 |
| Total spend: $487/month | research-agent: $210, writer-agent: $89, code-agent: $188. Retries: $74 wasted |
| Avg cost per request: $0.04 | This task used Opus but Haiku would work. Savings: $540/month |

## Quick Start

### 1. Install

```bash
pip install agentledger
```

### 2. Track your agents (2 lines of code)

```python
from agentledger import track, ledger

ledger.init(project="my-saas")  # or point to your self-hosted server

@track(agent="research-agent", task="competitor-analysis")
def run_research(query):
    # your existing agent code — LangGraph, CrewAI, custom, whatever
    result = agent.invoke(query)
    return result

# That's it. You now get per-agent, per-task cost tracking.
```

### 3. Framework integrations

```python
# LangGraph
from agentledger.integrations import langgraph_callback
app = workflow.compile(callbacks=[langgraph_callback()])

# CrewAI
from agentledger.integrations import crewai_callback
crew = Crew(agents=[...], callbacks=[crewai_callback()])

# Google ADK
from agentledger.integrations import adk_callback
agent = Agent(callbacks=[adk_callback()])
```

### 4. Start the server

```bash
# With Docker
docker compose up

# Or locally (zero dependencies — uses SQLite)
cd agentledger-server
pip install fastapi uvicorn sqlalchemy aiosqlite pydantic pydantic-settings greenlet
PYTHONPATH=. uvicorn app.main:app --port 8100
```

### 5. See where your money goes

```bash
agentledger status          # dashboard overview
agentledger agents          # per-agent cost breakdown
agentledger waste           # detected waste flags
agentledger recommend       # model routing recommendations
```

## LiteLLM Integration

AgentLedger is designed to work **with** LiteLLM, not against it. If you're already using LiteLLM as your gateway, adding AgentLedger takes one line:

### SDK Integration

```python
import litellm
from agentledger import track, ledger
from agentledger.integrations.litellm import AgentLedgerCallback

ledger.init(project="my-saas")
litellm.callbacks = [AgentLedgerCallback()]  # <-- one line

@track(agent="research-agent", task="summarize")
def run_research(query):
    # AgentLedger auto-captures model, tokens, cost, latency
    return litellm.completion(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": query}],
    )
```

### LiteLLM Proxy Integration

If your team uses the LiteLLM Proxy as a shared gateway, add AgentLedger to `config.yaml`:

```yaml
litellm_settings:
  callbacks: agentledger.integrations.litellm.callback_instance
```

Your team passes agent context via metadata:

```python
response = litellm.completion(
    model="claude-sonnet",
    messages=[...],
    metadata={"agent": "research-agent", "task": "summarize"}
)
```

AgentLedger extracts agent/task automatically and gives you per-agent cost attribution across your entire team's usage.

### Works Without @track Too

For calls outside a `@track` scope, pass agent info in LiteLLM metadata:

```python
litellm.completion(
    model="gpt-4o",
    messages=[...],
    metadata={"agent": "finance-agent", "task": "quarterly-report"}
)
# AgentLedger reads the metadata and attributes the cost correctly
```

## Features

### Per-Agent Cost Attribution
Every LLM call tagged to a specific agent and task. No more guessing which part of your pipeline is expensive.

### Waste Detection
Automatically flags:
- **Retry loops** — same prompt repeated 3+ times
- **Over-qualified models** — Opus used where Haiku would work
- **Context bloat** — input tokens growing linearly across steps
- **Idle heartbeats** — background agents burning tokens doing nothing

### Routing Recommendations
Analyzes your actual usage patterns and tells you exactly which tasks can use cheaper models — with estimated monthly savings.

### Budget Guardrails
Set per-project or per-agent spending limits. Get alerts via Slack, email, or PagerDuty before you blow your budget.

```bash
curl -X POST http://localhost:8100/api/v1/budgets \
  -H "Content-Type: application/json" \
  -d '{"project_id": "my-saas", "agent_name": "research-agent", "limit_usd": 50, "period": "monthly", "webhook_url": "https://hooks.slack.com/..."}'
```

### Works With Your Stack
Not another gateway. AgentLedger is a **cost intelligence layer** that works WITH whatever you already use:
- **LiteLLM** — official `CustomLogger` callback (SDK + Proxy)
- **LangGraph / LangChain** — native callback handler
- **CrewAI** — task/step callback
- **Google ADK** — request/response hooks
- **Any custom framework** — `@track` decorator + context manager

### Self-Hostable
`docker compose up` and you own your data. No vendor lock-in. No usage-based pricing on your observability.

## Architecture

```
SDK (@track decorator)  -->  FastAPI Server  -->  PostgreSQL / SQLite
     |                            |
     |-- LangGraph callback       |-- Waste Detector (hourly)
     |-- CrewAI callback          |-- Routing Advisor (hourly)
     |-- ADK callback             |-- Budget Monitor (hourly)
     |-- LiteLLM callback         |
                                  v
                           Web Dashboard / CLI / API
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/events` | Batch ingest events from SDK |
| `GET` | `/api/v1/agents` | List agents with cost summaries |
| `GET` | `/api/v1/agents/{name}/costs` | Per-agent P&L breakdown by task, model, and time |
| `GET` | `/api/v1/waste` | Waste flags sorted by $ impact |
| `GET` | `/api/v1/recommendations` | Model routing recommendations with savings estimates |
| `POST` | `/api/v1/budgets` | Create/update budget guardrails with webhook alerts |
| `GET` | `/api/v1/dashboard` | Full dashboard: spend, agents, waste, savings, trends |
| `GET` | `/health` | Health check |

Interactive API docs at `http://localhost:8100/docs` (Swagger UI).

## Project Structure

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

## Model Pricing Database

AgentLedger includes a community-maintained pricing database (`pricing/models.json`) covering 25+ models across 6 providers:

| Provider | Models |
|----------|--------|
| Anthropic | Claude Opus 4.6, Sonnet 4.6, Haiku 4.5 |
| OpenAI | GPT-4o, GPT-4.1, o3, o4-mini |
| Google | Gemini 2.5 Pro/Flash, 2.0 Flash |
| DeepSeek | V3, R1 |
| Meta | Llama 3.3, Llama 4 Maverick |
| Mistral | Large, Small |

PRs to update pricing are always welcome. Costs change frequently.

## Developer Guide

See **[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)** for the full implementation walkthrough:

- 6 integration paths (decorator, LiteLLM, LangGraph, CrewAI, ADK, raw API)
- Event schema reference
- Budget guardrails setup
- Waste detection deep dive
- Production deployment config
- Architecture and data flow

## Security & Privacy

AgentLedger tracks **cost metadata only**. It does NOT store prompts, completions, or any LLM content. See [SECURITY.md](SECURITY.md) for details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). High-impact areas:

1. **Update pricing** — keep `pricing/models.json` current
2. **Add integrations** — AutoGen, Semantic Kernel, Haystack
3. **Improve waste detection** — new patterns and heuristics
4. **Build the React dashboard** — highest-impact frontend work

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

**Stop guessing. Start measuring.**
