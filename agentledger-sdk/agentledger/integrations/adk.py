"""Google ADK (Agent Development Kit) callback for AgentLedger cost tracking."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from agentledger.pricing import calculate_cost
from agentledger.tracker import get_current_context


def adk_callback(**kwargs: Any):
    """Create a Google ADK-compatible callback handler.

    Usage:
        from agentledger.integrations import adk_callback
        agent = Agent(callbacks=[adk_callback()])
    """

    class AgentLedgerADKHandler:
        """Intercepts Google ADK LLM calls and records cost data."""

        name = "agentledger"

        def __init__(self) -> None:
            self._call_starts: dict[str, float] = {}

        def on_llm_request(self, request: Any, *, call_id: str = "", **kw: Any) -> None:
            self._call_starts[call_id] = time.perf_counter()

        def on_llm_response(self, response: Any, *, call_id: str = "", **kw: Any) -> None:
            start = self._call_starts.pop(call_id, None)
            latency_ms = (time.perf_counter() - start) * 1000 if start else 0

            ctx = get_current_context()
            if ctx is None:
                return

            model = "unknown"
            tokens_in = 0
            tokens_out = 0

            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                tokens_in = getattr(usage, "prompt_token_count", 0)
                tokens_out = getattr(usage, "candidates_token_count", 0)
            if hasattr(response, "model"):
                model = response.model

            cost = calculate_cost(model, tokens_in, tokens_out)
            prompt_hash = None
            if hasattr(response, "text"):
                prompt_hash = hashlib.md5(response.text[:500].encode()).hexdigest()[:12]

            ctx.record_call(
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=latency_ms,
                prompt_hash=prompt_hash,
            )

    return AgentLedgerADKHandler()
