"""Core Ledger client — manages configuration, batching, and event shipping."""

from __future__ import annotations

import atexit
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("agentledger")

_DEFAULT_BATCH_SIZE = 50
_DEFAULT_FLUSH_INTERVAL = 5.0  # seconds
_DEFAULT_SERVER_URL = "http://localhost:8100"


@dataclass
class LedgerConfig:
    project: str = "default"
    api_key: str | None = None
    server_url: str = _DEFAULT_SERVER_URL
    batch_size: int = _DEFAULT_BATCH_SIZE
    flush_interval: float = _DEFAULT_FLUSH_INTERVAL
    fallback_path: str | None = None  # local JSON fallback when server is unreachable
    enabled: bool = True


class Ledger:
    """Singleton client that buffers events and ships them to the AgentLedger server."""

    def __init__(self) -> None:
        self._config = LedgerConfig()
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._flush_thread: threading.Thread | None = None
        self._running = False
        self._initialized = False

    def init(
        self,
        project: str = "default",
        api_key: str | None = None,
        server_url: str = _DEFAULT_SERVER_URL,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        flush_interval: float = _DEFAULT_FLUSH_INTERVAL,
        fallback_path: str | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize the ledger. Call once at application startup."""
        self._config = LedgerConfig(
            project=project,
            api_key=api_key,
            server_url=server_url.rstrip("/"),
            batch_size=batch_size,
            flush_interval=flush_interval,
            fallback_path=fallback_path,
            enabled=enabled,
        )
        self._initialized = True
        self._start_flush_thread()
        atexit.register(self.shutdown)
        logger.info("AgentLedger initialized for project=%s", project)

    @property
    def config(self) -> LedgerConfig:
        return self._config

    def record(self, event: dict[str, Any]) -> None:
        """Buffer a single event for async shipping."""
        if not self._config.enabled:
            return
        event["project"] = self._config.project
        event["recorded_at"] = time.time()
        with self._lock:
            self._buffer.append(event)
            if len(self._buffer) >= self._config.batch_size:
                self._flush_locked()

    def flush(self) -> None:
        """Force-flush the current buffer."""
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        """Must be called while holding self._lock."""
        if not self._buffer:
            return
        batch = self._buffer[:]
        self._buffer.clear()
        self._ship(batch)

    def _ship(self, batch: list[dict[str, Any]]) -> None:
        """Send a batch of events to the server, falling back to local JSON."""
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        try:
            resp = httpx.post(
                f"{self._config.server_url}/api/v1/events",
                json={"events": batch},
                headers=headers,
                timeout=10.0,
            )
            resp.raise_for_status()
            logger.debug("Shipped %d events to server", len(batch))
        except Exception as exc:
            logger.warning("Failed to ship events: %s. Writing to fallback.", exc)
            self._write_fallback(batch)

    def _write_fallback(self, batch: list[dict[str, Any]]) -> None:
        """Append events to a local JSON-lines file as fallback."""
        fallback = self._config.fallback_path or "agentledger_events.jsonl"
        path = Path(fallback)
        with path.open("a") as f:
            for event in batch:
                f.write(json.dumps(event) + "\n")
        logger.info("Wrote %d events to fallback file: %s", len(batch), path)

    def _start_flush_thread(self) -> None:
        if self._running:
            return
        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def _flush_loop(self) -> None:
        while self._running:
            time.sleep(self._config.flush_interval)
            self.flush()

    def shutdown(self) -> None:
        """Stop the flush thread and ship remaining events."""
        self._running = False
        self.flush()
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=2.0)


# Module-level singleton
ledger = Ledger()
