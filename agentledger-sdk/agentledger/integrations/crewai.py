"""CrewAI callback handler for AgentLedger cost tracking."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from agentledger.pricing import calculate_cost
from agentledger.tracker import get_current_context


def crewai_callback(**kwargs: Any):
    """Create a CrewAI-compatible callback handler.

    Usage:
        from agentledger.integrations import crewai_callback
        crew = Crew(agents=[...], callbacks=[crewai_callback()])
    """
    try:
        from crewai.utilities.callbacks import BaseCallback  # noqa: F401
    except ImportError:
        # CrewAI callback interface varies by version — fall back to dict-based
        pass

    class AgentLedgerCrewAIHandler:
        """Intercepts CrewAI task/step events and records cost data."""

        name = "agentledger"

        def __init__(self) -> None:
            self._step_starts: dict[str, float] = {}

        def on_task_start(self, task: Any) -> None:
            task_key = getattr(task, "id", str(id(task)))
            self._step_starts[task_key] = time.perf_counter()

        def on_task_end(self, task: Any, output: Any) -> None:
            task_key = getattr(task, "id", str(id(task)))
            start = self._step_starts.pop(task_key, None)
            latency_ms = (time.perf_counter() - start) * 1000 if start else 0

            ctx = get_current_context()
            if ctx is None:
                return

            # Extract token usage from CrewAI output if available
            tokens_in = 0
            tokens_out = 0
            model = "unknown"

            if hasattr(output, "token_usage"):
                usage = output.token_usage
                tokens_in = getattr(usage, "prompt_tokens", 0)
                tokens_out = getattr(usage, "completion_tokens", 0)
            if hasattr(output, "model"):
                model = output.model

            cost = calculate_cost(model, tokens_in, tokens_out)
            prompt_hash = None
            if hasattr(task, "description"):
                prompt_hash = hashlib.md5(task.description.encode()).hexdigest()[:12]

            ctx.record_call(
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=latency_ms,
                prompt_hash=prompt_hash,
            )

        def on_step_start(self, step: Any) -> None:
            step_key = str(id(step))
            self._step_starts[step_key] = time.perf_counter()

        def on_step_end(self, step: Any, output: Any) -> None:
            step_key = str(id(step))
            start = self._step_starts.pop(step_key, None)
            latency_ms = (time.perf_counter() - start) * 1000 if start else 0

            ctx = get_current_context()
            if ctx is None:
                return

            model = "unknown"
            tokens_in = 0
            tokens_out = 0

            if isinstance(output, dict):
                model = output.get("model", "unknown")
                tokens_in = output.get("prompt_tokens", 0)
                tokens_out = output.get("completion_tokens", 0)

            cost = calculate_cost(model, tokens_in, tokens_out)
            ctx.record_call(
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=latency_ms,
            )

    return AgentLedgerCrewAIHandler()
