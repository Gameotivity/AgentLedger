"""LangGraph callback handler for AgentLedger cost tracking."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from agentledger.pricing import calculate_cost
from agentledger.tracker import get_current_context


def langgraph_callback(**kwargs: Any):
    """Create a LangGraph-compatible callback handler.

    Usage:
        from agentledger.integrations import langgraph_callback
        app = workflow.compile(callbacks=[langgraph_callback()])
    """
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except ImportError:
        raise ImportError(
            "langgraph integration requires langchain-core. "
            "Install with: pip install agentledger[langgraph]"
        )

    class AgentLedgerLangGraphHandler(BaseCallbackHandler):
        """Intercepts LLM calls from LangGraph workflows and records cost data."""

        name = "agentledger"

        def __init__(self) -> None:
            self._call_starts: dict[str, float] = {}
            self._call_prompts: dict[str, str] = {}

        def on_llm_start(self, serialized: dict, prompts: list[str], *, run_id, **kw: Any) -> None:
            self._call_starts[str(run_id)] = time.perf_counter()
            if prompts:
                self._call_prompts[str(run_id)] = prompts[0][:500]

        def on_chat_model_start(
            self, serialized: dict, messages: list, *, run_id, **kw: Any,
        ) -> None:
            self._call_starts[str(run_id)] = time.perf_counter()
            if messages and messages[0]:
                msg = messages[0][0]
                content = str(msg.content)[:500] if hasattr(msg, "content") else ""
                self._call_prompts[str(run_id)] = content

        def on_llm_end(self, response, *, run_id, **kw: Any) -> None:
            run_key = str(run_id)
            start = self._call_starts.pop(run_key, None)
            prompt_text = self._call_prompts.pop(run_key, "")
            latency_ms = (time.perf_counter() - start) * 1000 if start else 0

            ctx = get_current_context()
            if ctx is None:
                return

            model = _extract_model(response)
            tokens_in, tokens_out = _extract_tokens(response)
            cost = calculate_cost(model, tokens_in, tokens_out)
            prompt_hash = (
                hashlib.md5(prompt_text.encode()).hexdigest()[:12] if prompt_text else None
            )

            ctx.record_call(
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=latency_ms,
                prompt_hash=prompt_hash,
            )

        def on_llm_error(self, error: BaseException, *, run_id, **kw: Any) -> None:
            run_key = str(run_id)
            start = self._call_starts.pop(run_key, None)
            self._call_prompts.pop(run_key, "")
            latency_ms = (time.perf_counter() - start) * 1000 if start else 0

            ctx = get_current_context()
            if ctx is None:
                return

            ctx.record_call(
                model="unknown",
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                latency_ms=latency_ms,
                status="error",
            )

    return AgentLedgerLangGraphHandler()


def _extract_model(response: Any) -> str:
    if hasattr(response, "llm_output") and response.llm_output:
        return response.llm_output.get("model_name", response.llm_output.get("model", "unknown"))
    if response.generations and response.generations[0]:
        gen = response.generations[0][0]
        if hasattr(gen, "generation_info") and gen.generation_info:
            return gen.generation_info.get("model", "unknown")
    return "unknown"


def _extract_tokens(response: Any) -> tuple[int, int]:
    if hasattr(response, "llm_output") and response.llm_output:
        usage = response.llm_output.get("token_usage", response.llm_output.get("usage", {}))
        if usage:
            return (
                usage.get("prompt_tokens", usage.get("input_tokens", 0)),
                usage.get("completion_tokens", usage.get("output_tokens", 0)),
            )
    return 0, 0
