"""AgentLedger + LangGraph integration example."""

from agentledger import track, ledger
from agentledger.integrations import langgraph_callback

ledger.init(project="my-saas")

# The callback auto-captures all LLM calls made by LangGraph
callback = langgraph_callback()


@track(agent="research-agent", task="web-search")
def run_langgraph_agent(query: str):
    """
    In a real setup, you'd do:

        from langgraph.graph import StateGraph
        workflow = StateGraph(...)
        # ... define your graph ...
        app = workflow.compile(callbacks=[callback])
        result = app.invoke({"query": query})
    """
    # The callback handler automatically records token usage,
    # model info, and cost for every LLM call in the graph.
    pass


if __name__ == "__main__":
    run_langgraph_agent("Latest AI agent frameworks")
    ledger.flush()
