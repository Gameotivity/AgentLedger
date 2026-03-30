"""LiteLLM integration using their official CustomLogger callback interface.

This is the recommended way to integrate with LiteLLM. It works with both
the LiteLLM SDK and LiteLLM Proxy, and captures cost, tokens, latency,
and model info from every LLM call automatically.

Usage (SDK):
    import litellm
    from agentledger.integrations.litellm import AgentLedgerCallback

    litellm.callbacks = [AgentLedgerCallback()]

Usage (Proxy config.yaml):
    litellm_settings:
      callbacks: agentledger.integrations.litellm.callback_instance

Usage with agent tracking:
    from agentledger import track, ledger
    from agentledger.integrations.litellm import AgentLedgerCallback
    import litellm

    ledger.init(project="my-saas")
    litellm.callbacks = [AgentLedgerCallback()]

    @track(agent="research-agent", task="summarize")
    def run_research(query):
        return litellm.completion(
            model="claude-sonnet-4-6",
            messages=[{"role": "user", "content": query}],
            metadata={"agent": "research-agent"}  # optional: also passed to AgentLedger
        )
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

from agentledger.ledger import ledger
from agentledger.tracker import get_current_context

logger = logging.getLogger("agentledger.litellm")


def _safe_get(obj: Any, attr: str, default: Any = None) -> Any:
    """Safely get attribute from object or dict."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


class AgentLedgerCallback:
    """LiteLLM CustomLogger-compatible callback that records cost data to AgentLedger.

    Implements the interface from litellm.integrations.custom_logger.CustomLogger
    without requiring litellm as an import-time dependency. LiteLLM discovers
    methods by name, so duck-typing works.
    """

    def __init__(self, project: str | None = None) -> None:
        self._project = project

    # --- Sync hooks (called for non-streaming) ---

    def log_success_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Called synchronously after a successful LLM completion."""
        self._record_event(kwargs, response_obj, start_time, end_time, status="success")

    def log_failure_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Called synchronously after a failed LLM completion."""
        self._record_event(kwargs, response_obj, start_time, end_time, status="error")

    # --- Async hooks (preferred by LiteLLM for I/O) ---

    async def async_log_success_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Called asynchronously after a successful LLM completion."""
        self._record_event(kwargs, response_obj, start_time, end_time, status="success")

    async def async_log_failure_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Called asynchronously after a failed LLM completion."""
        self._record_event(kwargs, response_obj, start_time, end_time, status="error")

    # --- Stream hooks ---

    def log_stream_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Called after a streaming response completes."""
        self._record_event(kwargs, response_obj, start_time, end_time, status="success")

    async def async_log_stream_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Called asynchronously after a streaming response completes."""
        self._record_event(kwargs, response_obj, start_time, end_time, status="success")

    # --- Core recording logic ---

    def _record_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
        status: str,
    ) -> None:
        """Extract cost data from LiteLLM's callback payload and record to AgentLedger."""
        try:
            # Model
            model = kwargs.get("model", "unknown")

            # Cost — LiteLLM pre-calculates this
            cost_usd = kwargs.get("response_cost", 0.0) or 0.0

            # Tokens
            tokens_in = 0
            tokens_out = 0
            usage = _safe_get(response_obj, "usage")
            if usage:
                tokens_in = _safe_get(usage, "prompt_tokens", 0) or 0
                tokens_out = _safe_get(usage, "completion_tokens", 0) or 0

            # Latency
            latency_ms = 0.0
            if start_time and end_time:
                delta = end_time - start_time
                latency_ms = delta.total_seconds() * 1000

            # Prompt hash for retry detection
            prompt_hash = None
            messages = kwargs.get("messages", [])
            if messages:
                last_content = str(messages[-1].get("content", ""))[:500]
                prompt_hash = hashlib.md5(last_content.encode()).hexdigest()[:12]

            # Agent context from @track decorator (if active)
            ctx = get_current_context()
            agent_name = "unknown"
            task_name = None

            if ctx:
                agent_name = ctx.agent_name
                task_name = ctx.task_name
                ctx.record_call(
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    prompt_hash=prompt_hash,
                    status=status,
                )
            else:
                # No @track context — extract agent info from LiteLLM metadata
                metadata = kwargs.get("litellm_params", {}).get("metadata", {})
                if not metadata:
                    metadata = kwargs.get("metadata", {})
                agent_name = metadata.get("agent", metadata.get("agent_name", "unknown"))
                task_name = metadata.get("task", metadata.get("task_name", None))

                # Record directly to ledger (no decorator scope)
                ledger.record(
                    {
                        "type": "llm_call",
                        "agent_name": agent_name,
                        "task_name": task_name,
                        "model": model,
                        "tokens_in": tokens_in,
                        "tokens_out": tokens_out,
                        "cost_usd": round(cost_usd, 6),
                        "latency_ms": round(latency_ms, 2),
                        "prompt_hash": prompt_hash,
                        "status": status,
                    }
                )

            logger.debug(
                "Recorded LiteLLM call: model=%s tokens=%d+%d cost=$%.4f agent=%s",
                model, tokens_in, tokens_out, cost_usd, agent_name,
            )

        except Exception as exc:
            # Never break the LLM call because of a tracking error
            logger.warning("AgentLedger callback error (non-fatal): %s", exc)


# Pre-instantiated callback for LiteLLM proxy config.yaml usage:
#   litellm_settings:
#     callbacks: agentledger.integrations.litellm.callback_instance
callback_instance = AgentLedgerCallback()
