"""@track decorator and track_context context manager for agent cost tracking."""

from __future__ import annotations

import functools
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable

from agentledger.ledger import ledger


def track(
    agent: str,
    task: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Callable:
    """Decorator that tracks an agent function's LLM calls and cost.

    Usage:
        @track(agent="research-agent", task="competitor-analysis")
        def run_research(query):
            ...
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            task_id = str(uuid.uuid4())
            _ctx = _TrackingContext(
                agent_name=agent,
                task_name=task or fn.__name__,
                task_id=task_id,
                metadata=metadata or {},
            )
            _push_context(_ctx)
            start = time.perf_counter()
            error: Exception | None = None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:
                error = exc
                raise
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                _pop_context()
                ledger.record(
                    {
                        "type": "task_span",
                        "agent_name": agent,
                        "task_name": _ctx.task_name,
                        "task_id": task_id,
                        "duration_ms": round(elapsed_ms, 2),
                        "status": "error" if error else "success",
                        "error": str(error) if error else None,
                        "call_count": _ctx.call_count,
                        "total_tokens_in": _ctx.total_tokens_in,
                        "total_tokens_out": _ctx.total_tokens_out,
                        "total_cost_usd": round(_ctx.total_cost_usd, 6),
                        "metadata": _ctx.metadata,
                    }
                )

        wrapper._agentledger_tracked = True
        return wrapper

    return decorator


@contextmanager
def track_context(
    agent: str,
    task: str | None = None,
    metadata: dict[str, Any] | None = None,
):
    """Context manager for tracking a block of agent work.

    Usage:
        with track_context(agent="research-agent", task="summarize"):
            result = llm.invoke(...)
    """
    task_id = str(uuid.uuid4())
    ctx = _TrackingContext(
        agent_name=agent,
        task_name=task or "unnamed",
        task_id=task_id,
        metadata=metadata or {},
    )
    _push_context(ctx)
    start = time.perf_counter()
    error: Exception | None = None
    try:
        yield ctx
    except Exception as exc:
        error = exc
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        _pop_context()
        ledger.record(
            {
                "type": "task_span",
                "agent_name": agent,
                "task_name": ctx.task_name,
                "task_id": task_id,
                "duration_ms": round(elapsed_ms, 2),
                "status": "error" if error else "success",
                "error": str(error) if error else None,
                "call_count": ctx.call_count,
                "total_tokens_in": ctx.total_tokens_in,
                "total_tokens_out": ctx.total_tokens_out,
                "total_cost_usd": round(ctx.total_cost_usd, 6),
                "metadata": ctx.metadata,
            }
        )


class _TrackingContext:
    """Accumulates LLM call data within a tracked scope."""

    def __init__(
        self,
        agent_name: str,
        task_name: str,
        task_id: str,
        metadata: dict[str, Any],
    ) -> None:
        self.agent_name = agent_name
        self.task_name = task_name
        self.task_id = task_id
        self.metadata = metadata
        self.call_count = 0
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.total_cost_usd = 0.0
        self.calls: list[dict[str, Any]] = []

    def record_call(
        self,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        latency_ms: float,
        prompt_hash: str | None = None,
        status: str = "success",
    ) -> None:
        """Record a single LLM call within this tracking scope."""
        self.call_count += 1
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self.total_cost_usd += cost_usd

        call_event = {
            "type": "llm_call",
            "agent_name": self.agent_name,
            "task_name": self.task_name,
            "task_id": self.task_id,
            "step": self.call_count,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost_usd, 6),
            "latency_ms": round(latency_ms, 2),
            "prompt_hash": prompt_hash,
            "status": status,
        }
        self.calls.append(call_event)
        ledger.record(call_event)


# Thread-local context stack for nested tracking
_context_stack = threading.local()


def _push_context(ctx: _TrackingContext) -> None:
    if not hasattr(_context_stack, "stack"):
        _context_stack.stack = []
    _context_stack.stack.append(ctx)


def _pop_context() -> _TrackingContext | None:
    if not hasattr(_context_stack, "stack") or not _context_stack.stack:
        return None
    return _context_stack.stack.pop()


def get_current_context() -> _TrackingContext | None:
    """Get the current active tracking context (for integrations to record calls)."""
    if not hasattr(_context_stack, "stack") or not _context_stack.stack:
        return None
    return _context_stack.stack[-1]
