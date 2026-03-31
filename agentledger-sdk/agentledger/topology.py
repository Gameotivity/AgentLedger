"""Agent topology declaration for Shapley attribution.

Allows users to declare their agent interaction graph so the server
can compute game-theoretic cost attribution.

Usage:
    from agentledger import ledger
    from agentledger.topology import declare_pipeline, declare_tree, declare_topology

    # Sequential pipeline: planner → researcher → writer → reviewer
    declare_pipeline(["planner", "researcher", "writer", "reviewer"])

    # Supervisor-worker tree
    declare_tree(supervisor="orchestrator", workers=["coder", "tester", "reviewer"])

    # Arbitrary DAG
    declare_topology(
        agents=["a", "b", "c"],
        edges=[("a", "b", 1.0), ("a", "c", 0.5), ("b", "c", 1.0)],
    )
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agentledger.ledger import ledger

logger = logging.getLogger("agentledger.topology")


def declare_pipeline(
    agents: list[str],
    context_retention: float = 1.0,
) -> None:
    """Declare a sequential pipeline topology: a1 → a2 → ... → an.

    This is the most common orchestration pattern (ReAct chains, LangGraph
    sequential workflows). Each agent passes its full output to the next.

    Args:
        agents: Ordered list of agent names.
        context_retention: α — fraction of output passed downstream (default 1.0).
    """
    edges = []
    for i in range(len(agents) - 1):
        edges.append({
            "project_id": ledger.config.project,
            "source_agent": agents[i],
            "target_agent": agents[i + 1],
            "topology": "pipeline",
            "context_retention": context_retention,
        })

    _send_topology({
        "project_id": ledger.config.project,
        "topology": "pipeline",
        "agents": agents,
        "edges": edges,
    })


def declare_tree(
    supervisor: str,
    workers: list[str],
    context_retention: float = 1.0,
) -> None:
    """Declare a hierarchical supervisor-worker tree topology.

    The supervisor sends instructions to each worker and reads their
    results. Edges: supervisor ↔ worker_k for all k.

    Args:
        supervisor: Name of the supervisor agent.
        workers: List of worker agent names.
        context_retention: α for all edges.
    """
    edges = []
    for w in workers:
        # Supervisor → worker (instructions)
        edges.append({
            "project_id": ledger.config.project,
            "source_agent": supervisor,
            "target_agent": w,
            "topology": "tree",
            "context_retention": context_retention,
        })
        # Worker → supervisor (results)
        edges.append({
            "project_id": ledger.config.project,
            "source_agent": w,
            "target_agent": supervisor,
            "topology": "tree",
            "context_retention": context_retention,
        })

    _send_topology({
        "project_id": ledger.config.project,
        "topology": "tree",
        "agents": [supervisor] + workers,
        "edges": edges,
        "supervisor": supervisor,
    })


def declare_debate(
    agents: list[str],
    rounds: int = 1,
    context_retention: float = 1.0,
) -> None:
    """Declare a peer-to-peer debate topology (complete graph).

    Every agent sends its output to every other agent. Symmetric
    structure means Shapley values are equal (v(N)/n).

    Args:
        agents: List of debater agent names.
        rounds: Number of debate rounds.
        context_retention: α for all edges.
    """
    edges = []
    for i, a in enumerate(agents):
        for j, b in enumerate(agents):
            if i != j:
                edges.append({
                    "project_id": ledger.config.project,
                    "source_agent": a,
                    "target_agent": b,
                    "topology": "debate",
                    "context_retention": context_retention,
                })

    _send_topology({
        "project_id": ledger.config.project,
        "topology": "debate",
        "agents": agents,
        "edges": edges,
    })


def declare_topology(
    agents: list[str],
    edges: list[tuple[str, str, float]],
    topology: str = "dag",
) -> None:
    """Declare an arbitrary agent topology (DAG).

    Args:
        agents: List of agent names.
        edges: List of (source, target, context_retention) tuples.
        topology: Topology type label.
    """
    edge_dicts = [
        {
            "project_id": ledger.config.project,
            "source_agent": src,
            "target_agent": tgt,
            "topology": topology,
            "context_retention": alpha,
        }
        for src, tgt, alpha in edges
    ]

    _send_topology({
        "project_id": ledger.config.project,
        "topology": topology,
        "agents": agents,
        "edges": edge_dicts,
    })


def _send_topology(payload: dict[str, Any]) -> None:
    """Send topology declaration to the server."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if ledger.config.api_key:
        headers["Authorization"] = f"Bearer {ledger.config.api_key}"

    try:
        resp = httpx.post(
            f"{ledger.config.server_url}/api/v1/topology",
            json=payload,
            headers=headers,
            timeout=10.0,
        )
        resp.raise_for_status()
        logger.info(
            "Declared %s topology with %d agents",
            payload.get("topology"), len(payload.get("agents", [])),
        )
    except Exception as exc:
        logger.warning("Failed to declare topology: %s", exc)
