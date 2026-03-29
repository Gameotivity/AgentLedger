"""LiteLLM integration — wraps litellm.completion to auto-track calls."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from agentledger.pricing import calculate_cost
from agentledger.tracker import get_current_context


def patch_litellm() -> None:
    """Monkey-patch litellm.completion and litellm.acompletion to auto-record costs.

    Usage:
        from agentledger.integrations.litellm import patch_litellm
        patch_litellm()
        # All subsequent litellm.completion() calls are now tracked
    """
    try:
        import litellm
    except ImportError:
        raise ImportError(
            "litellm integration requires litellm. "
            "Install with: pip install agentledger[litellm]"
        )

    _original_completion = litellm.completion

    def tracked_completion(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        error = None
        try:
            response = _original_completion(*args, **kwargs)
            return response
        except Exception as exc:
            error = exc
            raise
        finally:
            latency_ms = (time.perf_counter() - start) * 1000
            ctx = get_current_context()
            if ctx is not None:
                model = kwargs.get("model", args[0] if args else "unknown")
                tokens_in = 0
                tokens_out = 0
                if not error and hasattr(response, "usage") and response.usage:
                    tokens_in = getattr(response.usage, "prompt_tokens", 0)
                    tokens_out = getattr(response.usage, "completion_tokens", 0)
                cost = calculate_cost(model, tokens_in, tokens_out)

                prompt_hash = None
                messages = kwargs.get("messages", [])
                if messages:
                    content = str(messages[-1].get("content", ""))[:500]
                    prompt_hash = hashlib.md5(content.encode()).hexdigest()[:12]

                ctx.record_call(
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    prompt_hash=prompt_hash,
                    status="error" if error else "success",
                )

    litellm.completion = tracked_completion
