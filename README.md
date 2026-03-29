# AgentLedger

**Your agents are burning money. AgentLedger shows you exactly where.**

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
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

### 3. Framework-native integration

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
docker compose up
```

### 5. See where your money goes

```bash
agentledger status          # dashboard overview
agentledger agents          # per-agent cost breakdown
agentledger waste           # detected waste flags
agentledger recommend       # model routing recommendations
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

### Works With Your Stack
Not another gateway. AgentLedger is a **cost intelligence layer** that works WITH whatever you already use:
- LangGraph / LangChain
- CrewAI
- Google ADK
- LiteLLM (ingest logs directly)
- Any custom agent framework

### Self-Hostable
`docker compose up` and you own your data. No vendor lock-in. No usage-based pricing on your observability.

## Architecture

```
SDK (@track decorator)  -->  FastAPI Server  -->  PostgreSQL
     |                            |
     |-- LangGraph callback       |-- Waste Detector (hourly)
     |-- CrewAI callback          |-- Routing Advisor (hourly)
     |-- ADK callback             |-- Budget Monitor (hourly)
     |-- LiteLLM patch            |
                                  v
                           Web Dashboard / CLI / API
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/events` | Batch ingest events from SDK |
| `GET` | `/api/v1/agents` | List agents with cost summaries |
| `GET` | `/api/v1/agents/{name}/costs` | Per-agent P&L breakdown |
| `GET` | `/api/v1/waste` | Waste flags sorted by $ impact |
| `GET` | `/api/v1/recommendations` | Model routing recommendations |
| `POST` | `/api/v1/budgets` | Create budget guardrails |
| `GET` | `/api/v1/dashboard` | Full dashboard data |

## Project Structure

```
agentledger/
  agentledger-sdk/           # Python SDK (PyPI: agentledger)
  agentledger-server/        # FastAPI backend + workers
  agentledger-cli/           # Terminal dashboard
  agentledger-dashboard/     # React web UI (coming soon)
  pricing/                   # Community-maintained model pricing DB
  examples/                  # Integration examples
  docker-compose.yml         # One-command setup
```

## Model Pricing Database

AgentLedger includes a community-maintained pricing database (`pricing/models.json`) covering 25+ models from Anthropic, OpenAI, Google, DeepSeek, Meta, and Mistral. PRs welcome to keep it current.

## Contributing

We'd love your help. Here's how:

1. **Update pricing** — model costs change constantly. Keep `pricing/models.json` current.
2. **Add integrations** — new framework callbacks (AutoGen, Semantic Kernel, etc.)
3. **Improve waste detection** — new waste patterns, better heuristics
4. **Build the dashboard** — React UI for the web dashboard

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

**Stop guessing. Start measuring.**
