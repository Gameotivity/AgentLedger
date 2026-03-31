"""Shapley attribution engine — closed-form cost attribution for multi-agent systems.

Implements the theoretical framework from:
  "Shapley Attribution and Optimal Routing in Multi-Agent LLM Inference Systems"
  (Khial, 2026)

Three canonical topologies with closed-form Shapley values:
  - Sequential pipeline (Theorem 4.1)
  - Hierarchical supervisor-worker tree (Theorem 4.3)
  - Peer-to-peer debate graph (Proposition 4.4)

Plus Monte Carlo Shapley for arbitrary DAGs (Section 7.2).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import AgentEdge, Event, ShapleyAttribution

logger = logging.getLogger("agentledger.shapley")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AgentStats:
    """Aggregated stats for one agent in a project."""
    name: str
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost: float = 0.0
    avg_tokens_in: float = 0.0
    avg_tokens_out: float = 0.0
    call_count: int = 0
    model: str | None = None
    cin: float = 0.0  # per-token input cost ($/token)
    cout: float = 0.0  # per-token output cost ($/token)
    system_prompt_tokens: int = 200  # s_k — estimated system prompt size


@dataclass
class TopologyGraph:
    """Agent interaction topology."""
    agents: list[str]
    edges: dict[tuple[str, str], float] = field(default_factory=dict)  # (src, tgt) → α
    topology_type: str = "pipeline"  # pipeline | tree | debate
    supervisor: str | None = None  # for tree topology


@dataclass
class ShapleyResult:
    """Attribution result for one agent."""
    agent_name: str
    direct_cost: float
    propagation_cost: float
    shapley_value: float
    shapley_pct: float
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Load agent stats from database
# ---------------------------------------------------------------------------

async def _load_agent_stats(
    db: AsyncSession, project_id: str,
) -> dict[str, AgentStats]:
    """Load aggregated per-agent stats from the events table."""
    import json
    from pathlib import Path

    # Load pricing for cin/cout
    pricing_file = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "pricing" / "models.json"
    )
    pricing: dict[str, dict] = {}
    if pricing_file.exists():
        with pricing_file.open() as f:
            data = json.load(f)
        for entry in data.get("models", []):
            pricing[entry["model"]] = {
                "cin": entry.get("input_cost_per_1m", 0) / 1_000_000,
                "cout": entry.get("output_cost_per_1m", 0) / 1_000_000,
            }

    result = await db.execute(
        select(
            Event.agent_name,
            Event.model,
            func.sum(Event.tokens_in).label("total_in"),
            func.sum(Event.tokens_out).label("total_out"),
            func.sum(Event.cost_usd).label("total_cost"),
            func.avg(Event.tokens_in).label("avg_in"),
            func.avg(Event.tokens_out).label("avg_out"),
            func.count(Event.id).label("cnt"),
        )
        .where(
            Event.project_id == project_id,
            Event.event_type == "llm_call",
        )
        .group_by(Event.agent_name, Event.model)
    )

    agents: dict[str, AgentStats] = {}
    for row in result.all():
        name = row.agent_name
        if name not in agents:
            agents[name] = AgentStats(name=name)
        a = agents[name]
        a.total_tokens_in += int(row.total_in or 0)
        a.total_tokens_out += int(row.total_out or 0)
        a.total_cost += float(row.total_cost or 0)
        a.call_count += int(row.cnt or 0)
        a.avg_tokens_in = a.total_tokens_in / max(a.call_count, 1)
        a.avg_tokens_out = a.total_tokens_out / max(a.call_count, 1)
        # Use the most-used model's pricing
        if row.model and (a.model is None or int(row.cnt or 0) > 0):
            a.model = row.model
            p = pricing.get(row.model, {})
            a.cin = p.get("cin", 0)
            a.cout = p.get("cout", 0)

    return agents


async def _load_topology(
    db: AsyncSession, project_id: str,
) -> TopologyGraph | None:
    """Load agent topology from the edges table."""
    result = await db.execute(
        select(AgentEdge).where(AgentEdge.project_id == project_id)
    )
    edges_list = result.scalars().all()
    if not edges_list:
        return None

    agents_set: set[str] = set()
    edges: dict[tuple[str, str], float] = {}
    topology_type = "pipeline"

    for e in edges_list:
        agents_set.add(e.source_agent)
        agents_set.add(e.target_agent)
        edges[(e.source_agent, e.target_agent)] = e.context_retention
        topology_type = e.topology

    # Determine agent ordering for pipeline
    agents = _topological_sort(list(agents_set), edges)

    return TopologyGraph(
        agents=agents,
        edges=edges,
        topology_type=topology_type,
    )


def _topological_sort(
    agents: list[str], edges: dict[tuple[str, str], float],
) -> list[str]:
    """Topological sort of agents based on edge directions."""
    in_degree: dict[str, int] = {a: 0 for a in agents}
    adj: dict[str, list[str]] = {a: [] for a in agents}
    for (src, tgt) in edges:
        adj[src].append(tgt)
        in_degree[tgt] = in_degree.get(tgt, 0) + 1

    queue = [a for a in agents if in_degree[a] == 0]
    result = []
    while queue:
        queue.sort()  # deterministic
        node = queue.pop(0)
        result.append(node)
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # Add any remaining agents not in edges
    for a in agents:
        if a not in result:
            result.append(a)
    return result


# ---------------------------------------------------------------------------
# Theorem 4.1 — Sequential Pipeline Shapley Values
# ---------------------------------------------------------------------------

def compute_pipeline_shapley(
    agents: list[AgentStats],
    edges: dict[tuple[str, str], float],
) -> list[ShapleyResult]:
    """Closed-form Shapley values for sequential pipeline (Theorem 4.1).

    Sh_k(v) = c_in(s_k + τ) + c_out·Ō_k + c_in·Ō_k·(n-k)/2 + c_in·Σ_{j<k} Ō_j / 2

    Where:
      - s_k = system prompt tokens for agent k
      - τ = task specification tokens (shared)
      - Ō_k = average output tokens of agent k
      - n = number of agents
      - k = position (1-indexed)
    """
    n = len(agents)
    if n == 0:
        return []

    # Use average cin/cout across pipeline for uniform model assumption
    avg_cin = sum(a.cin for a in agents) / n if n > 0 else 0
    avg_cout = sum(a.cout for a in agents) / n if n > 0 else 0
    tau = 100  # estimated task specification tokens

    results = []
    total_shapley = 0.0

    for k_idx, agent in enumerate(agents):
        k = k_idx + 1  # 1-indexed position

        # Per-agent output size (Ō_k)
        o_k = agent.avg_tokens_out
        s_k = agent.system_prompt_tokens

        # Direct cost: c_in(s_k + τ) + c_out · Ō_k
        direct = avg_cin * (s_k + tau) + avg_cout * o_k

        # Propagation cost from Theorem 4.1:
        # c_in · Ō_k · (n - k) / 2  — cost this agent imposes downstream
        downstream_prop = avg_cin * o_k * (n - k) / 2

        # c_in · Σ_{j<k} Ō_j / 2  — cost from upstream context
        upstream_output = sum(agents[j].avg_tokens_out for j in range(k_idx))
        upstream_prop = avg_cin * upstream_output / 2

        propagation = downstream_prop + upstream_prop
        shapley = direct + propagation
        total_shapley += shapley

        results.append(ShapleyResult(
            agent_name=agent.name,
            direct_cost=round(direct, 6),
            propagation_cost=round(propagation, 6),
            shapley_value=round(shapley, 6),
            shapley_pct=0,  # computed after total
            details={
                "position": k,
                "avg_output_tokens": round(o_k),
                "downstream_agents": n - k,
                "upstream_output_tokens": round(upstream_output),
                "downstream_propagation": round(downstream_prop, 6),
                "upstream_propagation": round(upstream_prop, 6),
            },
        ))

    # Compute percentages
    for r in results:
        r.shapley_pct = round(
            r.shapley_value / total_shapley * 100 if total_shapley > 0 else 0,
            2,
        )

    return results


# ---------------------------------------------------------------------------
# Theorem 4.3 — Hierarchical Supervisor-Worker Tree
# ---------------------------------------------------------------------------

def compute_tree_shapley(
    agents: list[AgentStats],
    supervisor_name: str,
    edges: dict[tuple[str, str], float],
) -> list[ShapleyResult]:
    """Closed-form Shapley values for supervisor-worker tree (Theorem 4.3).

    Supervisor (a_0):
      Sh_0 = c_in(s_0 + τ) + c_out·Ō_0 + (c_in/2)·Σ_k Ō_k + (n/2)·c_in·Ō_0

    Worker (a_k):
      Sh_k = c_in(s_k + τ) + c_out·Ō_k + c_in·Ō_0/2 + c_in·Ō_k·n/(2(n+1))
    """
    # Separate supervisor from workers
    supervisor = None
    workers = []
    for a in agents:
        if a.name == supervisor_name:
            supervisor = a
        else:
            workers.append(a)

    if supervisor is None:
        # Fallback: first agent is supervisor
        supervisor = agents[0]
        workers = agents[1:]

    n = len(workers)
    avg_cin = sum(a.cin for a in agents) / len(agents)
    avg_cout = sum(a.cout for a in agents) / len(agents)
    tau = 100

    results = []
    total_shapley = 0.0

    # Supervisor attribution (Eq. 9)
    o_0 = supervisor.avg_tokens_out
    s_0 = supervisor.system_prompt_tokens
    total_worker_output = sum(w.avg_tokens_out for w in workers)

    sup_direct = avg_cin * (s_0 + tau) + avg_cout * o_0
    # Reads all worker outputs + pushes context to all workers
    sup_prop = (avg_cin / 2) * total_worker_output + (n / 2) * avg_cin * o_0
    sup_shapley = sup_direct + sup_prop
    total_shapley += sup_shapley

    results.append(ShapleyResult(
        agent_name=supervisor.name,
        direct_cost=round(sup_direct, 6),
        propagation_cost=round(sup_prop, 6),
        shapley_value=round(sup_shapley, 6),
        shapley_pct=0,
        details={
            "role": "supervisor",
            "num_workers": n,
            "reads_worker_output": round(total_worker_output),
            "pushes_to_workers": round(o_0 * n),
        },
    ))

    # Worker attributions (Eq. 10)
    for w in workers:
        o_k = w.avg_tokens_out
        s_k = w.system_prompt_tokens

        w_direct = avg_cin * (s_k + tau) + avg_cout * o_k
        # Reads supervisor context + contributes output to supervisor
        w_prop = avg_cin * o_0 / 2 + avg_cin * o_k * n / (2 * (n + 1))
        w_shapley = w_direct + w_prop
        total_shapley += w_shapley

        results.append(ShapleyResult(
            agent_name=w.name,
            direct_cost=round(w_direct, 6),
            propagation_cost=round(w_prop, 6),
            shapley_value=round(w_shapley, 6),
            shapley_pct=0,
            details={
                "role": "worker",
                "supervisor": supervisor.name,
                "supervisor_context_tokens": round(o_0),
                "output_contribution": round(o_k),
            },
        ))

    for r in results:
        r.shapley_pct = round(
            r.shapley_value / total_shapley * 100 if total_shapley > 0 else 0,
            2,
        )

    return results


# ---------------------------------------------------------------------------
# Proposition 4.4 — Peer-to-Peer Debate Graph
# ---------------------------------------------------------------------------

def compute_debate_shapley(
    agents: list[AgentStats],
    rounds: int = 1,
) -> list[ShapleyResult]:
    """Shapley values for peer-to-peer debate (Proposition 4.4).

    In a complete graph, every agent has an identical structural role,
    so Shapley value = v(N) / n (equal splitting).

    Sh_k = (1/n) · Σ_r Σ_i [c_in · I_i^(r) + c_out · O_i^(r)]
    """
    n = len(agents)
    if n == 0:
        return []

    # Total cost across all agents
    total_cost = sum(a.total_cost for a in agents)
    per_agent = total_cost / n if n > 0 else 0

    results = []
    for a in agents:
        # In debate, propagation cost = shapley_value - direct_cost
        direct = a.total_cost
        propagation = per_agent - direct  # redistribution

        results.append(ShapleyResult(
            agent_name=a.name,
            direct_cost=round(direct, 6),
            propagation_cost=round(propagation, 6),
            shapley_value=round(per_agent, 6),
            shapley_pct=round(100.0 / n, 2),
            details={
                "role": "debater",
                "debate_rounds": rounds,
                "equal_share": round(per_agent, 6),
                "direct_cost": round(direct, 6),
                "redistribution": round(propagation, 6),
            },
        ))

    return results


# ---------------------------------------------------------------------------
# Monte Carlo Shapley for arbitrary DAGs (Section 7.2)
# ---------------------------------------------------------------------------

def compute_montecarlo_shapley(
    agents: list[AgentStats],
    edges: dict[tuple[str, str], float],
    num_permutations: int = 1000,
) -> list[ShapleyResult]:
    """Monte Carlo approximation of Shapley values for arbitrary DAGs.

    Samples random permutations and computes average marginal contributions.
    Uses O(num_permutations × n) evaluations of the characteristic function.
    """
    n = len(agents)
    if n == 0:
        return []

    agent_names = [a.name for a in agents]
    stats = {a.name: a for a in agents}
    tau = 100

    def coalition_cost(coalition: set[str]) -> float:
        """Compute v(S) — coalition cost per Definition 3.1."""
        total = 0.0
        for name in coalition:
            a = stats[name]
            # Effective input: s_k + τ + Σ α_{ik} · O_i for upstream agents in S
            effective_input = a.system_prompt_tokens + tau
            for src in coalition:
                if src == name:
                    continue
                alpha = edges.get((src, name), 0.0)
                if alpha > 0:
                    effective_input += alpha * stats[src].avg_tokens_out
            total += a.cin * effective_input + a.cout * a.avg_tokens_out
        return total

    # Monte Carlo sampling
    marginal_contributions: dict[str, list[float]] = {
        name: [] for name in agent_names
    }

    rng = random.Random(42)
    for _ in range(num_permutations):
        perm = list(agent_names)
        rng.shuffle(perm)
        coalition: set[str] = set()
        prev_cost = 0.0

        for name in perm:
            coalition.add(name)
            new_cost = coalition_cost(coalition)
            marginal = new_cost - prev_cost
            marginal_contributions[name].append(marginal)
            prev_cost = new_cost

    # Average marginal contributions = Shapley values
    total_shapley = 0.0
    results = []
    for a in agents:
        contribs = marginal_contributions[a.name]
        shapley = sum(contribs) / len(contribs)
        direct = a.total_cost
        propagation = shapley - direct

        total_shapley += shapley
        results.append(ShapleyResult(
            agent_name=a.name,
            direct_cost=round(direct, 6),
            propagation_cost=round(propagation, 6),
            shapley_value=round(shapley, 6),
            shapley_pct=0,
            details={
                "method": "montecarlo",
                "num_permutations": num_permutations,
                "avg_marginal": round(shapley, 6),
                "std_marginal": round(
                    (sum((c - shapley) ** 2 for c in contribs) / len(contribs))
                    ** 0.5, 6
                ),
            },
        ))

    for r in results:
        r.shapley_pct = round(
            r.shapley_value / total_shapley * 100 if total_shapley > 0 else 0,
            2,
        )

    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def compute_shapley_attribution(
    db: AsyncSession,
    project_id: str,
    topology_override: str | None = None,
    agents_override: list[str] | None = None,
    supervisor: str | None = None,
) -> list[ShapleyResult]:
    """Compute Shapley attribution for a project.

    1. Loads agent stats from events table
    2. Loads topology from agent_edges table (or uses override)
    3. Dispatches to the appropriate closed-form formula
    4. Persists results to shapley_attributions table
    """
    # Load stats
    all_stats = await _load_agent_stats(db, project_id)
    if not all_stats:
        return []

    # Load or construct topology
    topo = await _load_topology(db, project_id)

    if agents_override:
        agent_list = [
            all_stats[name] for name in agents_override if name in all_stats
        ]
    elif topo:
        agent_list = [
            all_stats[name] for name in topo.agents if name in all_stats
        ]
    else:
        agent_list = list(all_stats.values())

    if not agent_list:
        return []

    topology_type = topology_override or (topo.topology_type if topo else "pipeline")
    edges = topo.edges if topo else {}

    # Dispatch to correct formula
    if topology_type == "pipeline":
        results = compute_pipeline_shapley(agent_list, edges)
    elif topology_type == "tree":
        sup = supervisor or (topo.supervisor if topo else None) or agent_list[0].name
        results = compute_tree_shapley(agent_list, sup, edges)
    elif topology_type == "debate":
        results = compute_debate_shapley(agent_list)
    else:
        # Arbitrary DAG — use Monte Carlo
        results = compute_montecarlo_shapley(agent_list, edges)

    # Persist results
    for r in results:
        existing = await db.execute(
            select(ShapleyAttribution).where(
                ShapleyAttribution.project_id == project_id,
                ShapleyAttribution.agent_name == r.agent_name,
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            row.topology = topology_type
            row.direct_cost = r.direct_cost
            row.propagation_cost = r.propagation_cost
            row.shapley_value = r.shapley_value
            row.shapley_pct = r.shapley_pct
            row.details_json = r.details
        else:
            db.add(ShapleyAttribution(
                project_id=project_id,
                agent_name=r.agent_name,
                topology=topology_type,
                direct_cost=r.direct_cost,
                propagation_cost=r.propagation_cost,
                shapley_value=r.shapley_value,
                shapley_pct=r.shapley_pct,
                details_json=r.details,
            ))

    await db.commit()
    logger.info(
        "Computed %s Shapley attribution for %d agents in project %s",
        topology_type, len(results), project_id,
    )

    return results
