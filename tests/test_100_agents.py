#!/usr/bin/env python3
"""
AgentLedger — 100 Agent Stress Test
====================================
Spins up the server, creates 100 agents with realistic traffic patterns,
then verifies every subsystem: ingestion, aggregation, waste detection,
routing recommendations, budgets, CLI, and dashboard.

Usage:
    python tests/test_100_agents.py
"""

from __future__ import annotations

import hashlib
import random
import subprocess
import sys

import httpx

BASE = "http://localhost:8100"
PROJECT = "stress-test-100"

# ---------------------------------------------------------------------------
# Agent definitions — 100 agents across 10 teams
# ---------------------------------------------------------------------------

TEAMS = [
    "research", "engineering", "finance", "sales", "marketing",
    "support", "legal", "data-science", "devops", "product",
]

TASKS_PER_TEAM = {
    "research": ["literature-review", "competitor-scan", "trend-analysis", "patent-search"],
    "engineering": ["code-review", "bug-triage", "refactor", "test-gen", "deploy-plan"],
    "finance": ["quarterly-report", "expense-audit", "forecast", "invoice-process"],
    "sales": ["lead-qualify", "proposal-draft", "crm-update", "follow-up"],
    "marketing": ["copy-write", "seo-audit", "campaign-plan", "social-post"],
    "support": ["ticket-classify", "knowledge-base", "escalation", "satisfaction-survey"],
    "legal": ["contract-review", "compliance-check", "risk-assess", "policy-draft"],
    "data-science": ["etl-pipeline", "model-train", "feature-engineer", "report-gen"],
    "devops": ["infra-audit", "cost-optimize", "incident-response", "capacity-plan"],
    "product": ["user-story", "roadmap-update", "spec-write", "feedback-analyze"],
}

MODELS_BY_TIER = {
    1: [
        ("gpt-4o-mini", 0.15, 0.60),
        ("claude-haiku-3.5", 0.80, 4.00),
        ("gemini-2.5-flash", 0.15, 0.60),
        ("deepseek-v3", 0.27, 1.10),
        ("mistral-small-latest", 0.10, 0.30),
    ],
    2: [
        ("gpt-4o", 2.50, 10.00),
        ("claude-sonnet-4-6", 3.00, 15.00),
        ("gemini-2.5-pro", 1.25, 10.00),
        ("mistral-large-latest", 2.00, 6.00),
    ],
    3: [
        ("claude-opus-4-6", 15.00, 75.00),
        ("gpt-4-turbo", 10.00, 30.00),
        ("o3", 10.00, 40.00),
    ],
}


def cost_for(model_name: str, tokens_in: int, tokens_out: int) -> float:
    for tier_models in MODELS_BY_TIER.values():
        for name, in_cost, out_cost in tier_models:
            if name == model_name:
                return round(tokens_in * in_cost / 1_000_000 + tokens_out * out_cost / 1_000_000, 6)
    return 0.001


def build_agents() -> list[dict]:
    """Generate 100 agent definitions with varying profiles."""
    agents = []
    agent_id = 0
    for team in TEAMS:
        tasks = TASKS_PER_TEAM[team]
        for i in range(10):  # 10 agents per team = 100 total
            agent_id += 1
            # Assign a cost profile
            if i < 3:
                profile = "heavy"      # tier-3 models, lots of tokens
            elif i < 6:
                profile = "medium"     # tier-2 models
            else:
                profile = "light"      # tier-1 models
            agents.append({
                "name": f"{team}-agent-{i+1:02d}",
                "team": team,
                "tasks": tasks,
                "profile": profile,
                "agent_id": agent_id,
            })
    return agents


def generate_events(agents: list[dict]) -> list[dict]:
    """Generate realistic events for all 100 agents."""
    events = []
    random.seed(42)  # reproducible

    for agent in agents:
        name = agent["name"]
        profile = agent["profile"]
        tasks = agent["tasks"]

        # How many calls per agent
        if profile == "heavy":
            num_calls = random.randint(15, 30)
        elif profile == "medium":
            num_calls = random.randint(8, 20)
        else:
            num_calls = random.randint(3, 12)

        for call_idx in range(num_calls):
            task = random.choice(tasks)

            # Pick model based on profile
            if profile == "heavy":
                tier = random.choice([3, 3, 3, 2])  # mostly tier 3
            elif profile == "medium":
                tier = random.choice([2, 2, 2, 1])
            else:
                tier = random.choice([1, 1, 1, 2])

            model_name, _, _ = random.choice(MODELS_BY_TIER[tier])

            # Token counts
            if profile == "heavy":
                tokens_in = random.randint(2000, 15000)
                tokens_out = random.randint(100, 4000)
            elif profile == "medium":
                tokens_in = random.randint(500, 5000)
                tokens_out = random.randint(50, 1500)
            else:
                tokens_in = random.randint(100, 2000)
                tokens_out = random.randint(20, 500)

            cost = cost_for(model_name, tokens_in, tokens_out)
            latency = random.uniform(200, 5000)

            event = {
                "type": "llm_call",
                "project": PROJECT,
                "agent_name": name,
                "task_name": task,
                "task_id": f"{name}-{task}-{call_idx // 5}",
                "step": (call_idx % 5) + 1,
                "model": model_name,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost,
                "latency_ms": round(latency, 2),
                "status": "success",
                "metadata": {"team": agent["team"]},
            }

            # --- WASTE PATTERN 1: Retry loops ---
            # For 15 agents, create duplicate prompt hashes (3+ repeats)
            if agent["agent_id"] <= 15 and call_idx < 9:
                # Every 3 calls share the same prompt hash
                group = call_idx // 3
                event["prompt_hash"] = hashlib.md5(
                    f"{name}-{task}-retry-{group}".encode()
                ).hexdigest()[:12]

            # --- WASTE PATTERN 2: Over-qualified models ---
            # For agents 16-30, use tier-3 models with tiny outputs (<500 tokens)
            if 16 <= agent["agent_id"] <= 30:
                model_name = random.choice(["claude-opus-4-6", "o3", "gpt-4-turbo"])
                event["model"] = model_name
                event["tokens_out"] = random.randint(50, 200)  # very short
                event["cost_usd"] = cost_for(model_name, event["tokens_in"], event["tokens_out"])

            # --- WASTE PATTERN 3: Context bloat ---
            # For agents 31-45, create multi-step tasks where tokens_in grows each step
            if 31 <= agent["agent_id"] <= 45 and call_idx < 5:
                event["step"] = call_idx + 1
                event["task_id"] = f"{name}-bloat-task-0"
                base_tokens = 1000
                # Each step grows input tokens significantly
                event["tokens_in"] = base_tokens * (2 ** call_idx)  # 1k, 2k, 4k, 8k, 16k
                event["cost_usd"] = cost_for(event["model"], event["tokens_in"], event["tokens_out"])

            events.append(event)

    return events


def ingest_events(client: httpx.Client, events: list[dict]) -> int:
    """Send events in batches of 50."""
    total_accepted = 0
    batch_size = 50
    for i in range(0, len(events), batch_size):
        batch = events[i:i + batch_size]
        resp = client.post(f"{BASE}/api/v1/events", json={"events": batch})
        resp.raise_for_status()
        data = resp.json()
        total_accepted += data["accepted"]
        print(f"  Batch {i // batch_size + 1}: {data['accepted']} accepted, {data['failed']} failed")
    return total_accepted


def create_budgets(client: httpx.Client):
    """Set up budgets for several teams."""
    budgets = [
        {"project_id": PROJECT, "agent_name": "research-agent-01", "period": "daily",
         "limit_usd": 5.00, "alert_threshold_pct": 0.8, "webhook_url": "https://httpbin.org/post"},
        {"project_id": PROJECT, "agent_name": "engineering-agent-01", "period": "weekly",
         "limit_usd": 50.00, "alert_threshold_pct": 0.9, "webhook_url": "https://httpbin.org/post"},
        {"project_id": PROJECT, "agent_name": "finance-agent-01", "period": "monthly",
         "limit_usd": 200.00, "alert_threshold_pct": 0.7, "webhook_url": "https://httpbin.org/post"},
        # Global project budget
        {"project_id": PROJECT, "period": "monthly",
         "limit_usd": 1000.00, "alert_threshold_pct": 0.5, "webhook_url": "https://httpbin.org/post"},
    ]
    for b in budgets:
        resp = client.post(f"{BASE}/api/v1/budgets", json=b)
        resp.raise_for_status()
        print(f"  Budget set: {b.get('agent_name', 'project-wide')} — ${b['limit_usd']}/{b['period']}")


def run_tests(client: httpx.Client, total_events: int, num_agents: int):
    """Run all verification checks."""
    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
        else:
            failed += 1
            print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))

    # --- Test 1: Health ---
    print("\n[1/8] Health Check")
    resp = client.get(f"{BASE}/health")
    check("Server health", resp.status_code == 200 and resp.json()["status"] == "ok")

    # --- Test 2: Agents endpoint ---
    print("\n[2/8] Agents Endpoint")
    resp = client.get(f"{BASE}/api/v1/agents", params={"project": PROJECT})
    agents_data = resp.json()
    check("Agents returned", len(agents_data) == num_agents,
          f"expected {num_agents}, got {len(agents_data)}")

    total_cost = sum(a["total_cost"] for a in agents_data)
    check("Total cost > $0", total_cost > 0, f"${total_cost:.4f}")

    total_calls = sum(a["call_count"] for a in agents_data)
    check("Total calls match", total_calls == total_events,
          f"expected {total_events}, got {total_calls}")

    # Check each agent has required fields
    sample = agents_data[0]
    required_fields = ["agent_name", "total_cost", "total_tokens", "call_count",
                       "avg_latency", "waste_cost", "waste_pct", "top_model"]
    check("Agent schema complete",
          all(f in sample for f in required_fields),
          f"fields: {list(sample.keys())}")

    # --- Test 3: Dashboard ---
    print("\n[3/8] Dashboard Endpoint")
    resp = client.get(f"{BASE}/api/v1/dashboard", params={"project": PROJECT})
    dash = resp.json()
    check("Dashboard total_spend", dash["total_spend"] > 0, f"${dash['total_spend']:.4f}")
    check("Dashboard total_calls", dash["total_calls"] == total_events,
          f"expected {total_events}, got {dash['total_calls']}")
    check("Dashboard top_agents populated", len(dash["top_agents"]) > 0,
          f"{len(dash['top_agents'])} agents")
    check("Dashboard spend_trend", len(dash["spend_trend"]) > 0,
          f"{len(dash['spend_trend'])} data points")

    # --- Test 4: Agent cost detail ---
    print("\n[4/8] Agent Cost Detail")
    test_agent = agents_data[0]["agent_name"]
    resp = client.get(f"{BASE}/api/v1/agents/{test_agent}/costs",
                      params={"project": PROJECT})
    costs = resp.json()
    check("Agent costs endpoint works", resp.status_code == 200,
          f"{test_agent}: {len(costs)} records")

    # --- Test 5: Waste detection ---
    print("\n[5/8] Waste Detection")
    resp = client.get(f"{BASE}/api/v1/waste", params={"project": PROJECT})
    waste_data = resp.json()
    check("Waste flags detected", len(waste_data) > 0, f"{len(waste_data)} flags")

    # Check for specific waste types
    waste_types = {w["waste_type"] for w in waste_data}
    check("Retry loop waste found", "retry_loop" in waste_types,
          f"types: {waste_types}")
    check("Over-qualified model waste found", "over_qualified_model" in waste_types,
          f"types: {waste_types}")
    check("Context bloat waste found", "context_bloat" in waste_types,
          f"types: {waste_types}")

    total_waste = sum(w.get("estimated_waste_usd", 0) for w in waste_data)
    check("Waste cost > $0", total_waste > 0, f"${total_waste:.4f}")

    # --- Test 6: Routing recommendations ---
    print("\n[6/8] Routing Recommendations")
    resp = client.get(f"{BASE}/api/v1/recommendations", params={"project": PROJECT})
    recs = resp.json()
    check("Recommendations generated", len(recs) > 0, f"{len(recs)} recommendations")

    if recs:
        sample_rec = recs[0]
        check("Recommendation has savings",
              sample_rec.get("estimated_monthly_savings", 0) > 0,
              f"${sample_rec.get('estimated_monthly_savings', 0):.2f}/mo")
        check("Recommendation has alternative model",
              "recommended_model" in sample_rec,
              f"{sample_rec.get('current_model')} → {sample_rec.get('recommended_model')}")

    # --- Test 7: Budgets ---
    print("\n[7/8] Budget Guardrails")
    resp = client.get(f"{BASE}/api/v1/budgets", params={"project": PROJECT})
    budgets = resp.json()
    check("Budgets created", len(budgets) >= 4, f"{len(budgets)} budgets")

    # --- Test 8: Data integrity ---
    print("\n[8/8] Data Integrity")
    # Every team should have agents
    teams_found = set()
    for a in agents_data:
        team = a["agent_name"].rsplit("-agent-", 1)[0]
        teams_found.add(team)
    check("All 10 teams represented", len(teams_found) == 10,
          f"teams: {sorted(teams_found)}")

    # Cost distribution — heaviest agents should cost more
    sorted_agents = sorted(agents_data, key=lambda a: a["total_cost"], reverse=True)
    top5_cost = sum(a["total_cost"] for a in sorted_agents[:5])
    bottom5_cost = sum(a["total_cost"] for a in sorted_agents[-5:])
    check("Cost distribution realistic", top5_cost > bottom5_cost * 3,
          f"top5=${top5_cost:.4f} vs bottom5=${bottom5_cost:.4f}")

    # Models are being tracked
    models_used = {a["top_model"] for a in agents_data if a["top_model"]}
    check("Multiple models tracked", len(models_used) >= 3,
          f"{len(models_used)} models: {sorted(models_used)}")

    return passed, failed


def run_cli_tests() -> tuple[int, int]:
    """Test the CLI commands."""
    print("\n[CLI] Command Tests")
    passed = 0
    failed = 0

    def check(name: str, condition: bool, detail: str = ""):
        nonlocal passed, failed
        if condition:
            passed += 1
            print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
        else:
            failed += 1
            print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))

    for cmd_name, cmd_args in [
        ("status", ["agentledger", "--project", PROJECT, "status"]),
        ("agents", ["agentledger", "--project", PROJECT, "agents"]),
        ("waste", ["agentledger", "--project", PROJECT, "waste"]),
        ("recommend", ["agentledger", "--project", PROJECT, "recommend"]),
    ]:
        try:
            result = subprocess.run(cmd_args, capture_output=True, text=True, timeout=15)
            check(f"CLI {cmd_name}", result.returncode == 0,
                  f"{len(result.stdout)} chars output")
            if result.returncode != 0:
                print(f"         stderr: {result.stderr[:200]}")
        except FileNotFoundError:
            check(f"CLI {cmd_name}", False, "agentledger command not found")
        except subprocess.TimeoutExpired:
            check(f"CLI {cmd_name}", False, "timed out")

    return passed, failed


def main():
    print("=" * 65)
    print("  AgentLedger — 100 Agent Stress Test")
    print("=" * 65)

    # Step 1: Build agent definitions
    print("\n▸ Building 100 agent definitions...")
    agents = build_agents()
    print(f"  Created {len(agents)} agents across {len(TEAMS)} teams")
    for team in TEAMS:
        team_agents = [a for a in agents if a["team"] == team]
        profiles = [a["profile"] for a in team_agents]
        print(f"    {team}: {len(team_agents)} agents "
              f"(heavy={profiles.count('heavy')}, "
              f"medium={profiles.count('medium')}, "
              f"light={profiles.count('light')})")

    # Step 2: Generate events
    print("\n▸ Generating events with waste patterns...")
    events = generate_events(agents)
    print(f"  Generated {len(events)} events")

    # Count waste pattern events
    retry_events = sum(1 for e in events if e.get("prompt_hash"))
    overqual_agents = {e["agent_name"] for e in events if e.get("tokens_out", 999) <= 200
                       and e["model"] in ("claude-opus-4-6", "o3", "gpt-4-turbo")}
    bloat_events = sum(1 for e in events if "bloat-task" in (e.get("task_id") or ""))
    print(f"    Retry loop events: {retry_events}")
    print(f"    Over-qualified agents: {len(overqual_agents)}")
    print(f"    Context bloat events: {bloat_events}")

    # Unique agents in events
    unique_agents = {e["agent_name"] for e in events}
    print(f"    Unique agents in events: {len(unique_agents)}")

    # Step 3: Connect and ingest
    print("\n▸ Ingesting events into server...")
    client = httpx.Client(timeout=30)

    try:
        client.get(f"{BASE}/health").raise_for_status()
    except Exception:
        print("  ERROR: Server not running at", BASE)
        print("  Start it with: cd agentledger-server && uvicorn app.main:app --port 8100")
        sys.exit(1)

    total_accepted = ingest_events(client, events)
    print(f"  Total ingested: {total_accepted} events")

    # Step 4: Create budgets
    print("\n▸ Setting up budget guardrails...")
    create_budgets(client)

    # Step 5: Trigger analysis (waste detection + routing advisor)
    print("\n▸ Triggering waste detection & routing analysis...")
    resp = client.post(f"{BASE}/api/v1/analyze", params={"project": PROJECT})
    resp.raise_for_status()
    analysis = resp.json()
    print(f"  Waste flags: {analysis['waste_flags']}")
    print(f"  Recommendations: {analysis['recommendations']}")
    print(f"  Budget alerts: {analysis['budget_alerts']}")

    # Step 6: Run all verification tests
    print("\n" + "=" * 65)
    print("  VERIFICATION")
    print("=" * 65)

    api_passed, api_failed = run_tests(client, total_accepted, len(unique_agents))
    cli_passed, cli_failed = run_cli_tests()

    total_passed = api_passed + cli_passed
    total_failed = api_failed + cli_failed

    # Summary
    print("\n" + "=" * 65)
    print("  RESULTS")
    print("=" * 65)
    print(f"\n  Events generated:  {len(events)}")
    print(f"  Events ingested:   {total_accepted}")
    print(f"  Unique agents:     {len(unique_agents)}")
    print(f"\n  Tests passed:      {total_passed}")
    print(f"  Tests failed:      {total_failed}")
    print(f"  Total:             {total_passed + total_failed}")
    print()

    if total_failed == 0:
        print("  ALL TESTS PASSED")
    else:
        print(f"  {total_failed} TEST(S) FAILED")

    print("=" * 65)
    client.close()
    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
