"""AgentLedger + LiteLLM SDK integration.

This is the recommended way for businesses to track agent costs
when using LiteLLM as their LLM gateway.

Setup:
    pip install agentledger litellm
"""

import litellm
from agentledger import track, ledger
from agentledger.integrations.litellm import AgentLedgerCallback

# 1. Initialize AgentLedger
ledger.init(project="my-saas", server_url="http://localhost:8100")

# 2. Register the callback — this auto-captures ALL LiteLLM calls
litellm.callbacks = [AgentLedgerCallback()]


# 3. Use @track to tag which agent is making calls
@track(agent="research-agent", task="competitor-analysis")
def run_research(query: str) -> str:
    """Every litellm.completion() inside here is automatically tracked."""
    response = litellm.completion(
        model="claude-sonnet-4-6",
        messages=[{"role": "user", "content": query}],
    )
    return response.choices[0].message.content


# 4. Works without @track too — pass agent info via metadata
def run_standalone_call():
    """For calls outside a @track scope, pass agent info in metadata."""
    response = litellm.completion(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Summarize this quarter's revenue"}],
        metadata={
            "agent": "finance-agent",
            "task": "quarterly-summary",
        },
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    # Run both patterns
    result = run_research("Top AI cost tracking tools 2026")
    print(f"Research: {result[:100]}...")

    result2 = run_standalone_call()
    print(f"Standalone: {result2[:100]}...")

    ledger.flush()
    print("\nDone! Check: agentledger --project my-saas status")
