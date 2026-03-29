"""AgentLedger Quickstart — track agent costs in 4 lines of code."""

from agentledger import track, ledger

# 1. Initialize (points to your self-hosted server, or use the local JSON fallback)
ledger.init(project="my-saas", server_url="http://localhost:8100")


# 2. Decorate your agent functions
@track(agent="research-agent", task="competitor-analysis")
def run_research(query: str) -> str:
    """Your existing agent code goes here. AgentLedger tracks every LLM call inside."""
    # Simulate an LLM call — in reality, this is your LangGraph/CrewAI/custom agent
    import time
    time.sleep(0.1)

    # If you want manual control, grab the context and record calls yourself:
    from agentledger.tracker import get_current_context
    ctx = get_current_context()
    if ctx:
        ctx.record_call(
            model="claude-sonnet-4-6",
            tokens_in=1500,
            tokens_out=800,
            cost_usd=0.0165,  # or let AgentLedger compute from pricing DB
            latency_ms=450.0,
        )
        ctx.record_call(
            model="claude-sonnet-4-6",
            tokens_in=2200,
            tokens_out=350,
            cost_usd=0.0119,
            latency_ms=320.0,
        )

    return f"Research results for: {query}"


@track(agent="writer-agent", task="draft-report")
def write_report(research: str) -> str:
    from agentledger.tracker import get_current_context
    ctx = get_current_context()
    if ctx:
        ctx.record_call(
            model="claude-opus-4-6",
            tokens_in=4000,
            tokens_out=2000,
            cost_usd=0.21,
            latency_ms=1200.0,
        )
    return f"Report based on: {research[:50]}..."


# 3. Run your agents as normal
if __name__ == "__main__":
    research = run_research("AI cost tracking tools 2026")
    report = write_report(research)

    # 4. Flush to ensure all events are shipped
    ledger.flush()

    print("Done! Check your AgentLedger dashboard at http://localhost:8100/api/v1/dashboard")
    print(f"Or run: agentledger status")
