# Security & Privacy

## What AgentLedger Collects

AgentLedger tracks **cost metadata** about your LLM calls. It does NOT store prompts, completions, or any LLM input/output content.

### Data collected per event:
| Field | Example | Purpose |
|-------|---------|---------|
| `agent_name` | "research-agent" | Cost attribution |
| `task_name` | "summarize" | Task-level breakdown |
| `model` | "claude-sonnet-4-6" | Pricing lookup |
| `tokens_in` / `tokens_out` | 1500 / 800 | Cost calculation |
| `cost_usd` | 0.0165 | The actual cost |
| `latency_ms` | 450 | Performance tracking |
| `prompt_hash` | "a1b2c3d4e5f6" | Retry detection (NOT the prompt itself) |
| `status` | "success" | Error tracking |

### Data NOT collected:
- Prompt content
- Completion content
- API keys
- User PII
- File contents

The `prompt_hash` is a truncated MD5 of the first 500 characters of the prompt. It's used solely for detecting retry loops (same prompt sent repeatedly). The original prompt cannot be reconstructed from the hash.

## Self-Hosting

AgentLedger is designed to be self-hosted. When you run `docker compose up`, all data stays on your infrastructure. No data is sent to any external service unless you explicitly configure webhook URLs for budget alerts.

## API Authentication

Set the `AGENTLEDGER_API_KEY` environment variable on the server to require authentication. All SDK requests must then include this key in the `Authorization: Bearer <key>` header.

## Reporting Security Issues

If you discover a security vulnerability, please email security concerns directly rather than opening a public issue. Include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact

We will respond within 48 hours and work with you on a fix before any public disclosure.

## Dependencies

AgentLedger uses well-maintained dependencies:
- **FastAPI** — web framework
- **SQLAlchemy** — database ORM
- **httpx** — HTTP client
- **PostgreSQL / SQLite** — data storage

We monitor dependencies for known vulnerabilities and update promptly.
