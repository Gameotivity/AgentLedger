"""AgentLedger CLI — check agent costs, waste, and recommendations from the terminal."""

from __future__ import annotations

import click
import httpx
from rich.console import Console
from rich.table import Table

console = Console()
DEFAULT_URL = "http://localhost:8100"


def _api(server: str, path: str, params: dict | None = None) -> dict | list:
    resp = httpx.get(f"{server}/api/v1{path}", params=params or {}, timeout=10.0)
    resp.raise_for_status()
    return resp.json()


@click.group()
@click.option("--server", default=DEFAULT_URL, envvar="AGENTLEDGER_SERVER", help="Server URL")
@click.option("--project", default="default", envvar="AGENTLEDGER_PROJECT", help="Project ID")
@click.pass_context
def cli(ctx, server, project):
    """AgentLedger — Know exactly where your agent money goes."""
    ctx.ensure_object(dict)
    ctx.obj["server"] = server.rstrip("/")
    ctx.obj["project"] = project


@cli.command()
@click.pass_context
def status(ctx):
    """Show overall cost dashboard."""
    data = _api(ctx.obj["server"], "/dashboard", {"project": ctx.obj["project"]})

    console.print()
    console.print("[bold]AgentLedger Dashboard[/bold]", style="cyan")
    console.print(f"  Project: {ctx.obj['project']}")
    console.print()

    # Summary cards
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style="bold")
    table.add_column(style="green")
    table.add_row("Total Spend", f"${data['total_spend']:.2f}")
    table.add_row("Total Calls", f"{data['total_calls']:,}")
    table.add_row("Total Waste", f"[red]${data['total_waste']:.2f}[/red]")
    table.add_row("Potential Savings", f"[yellow]${data['potential_savings']:.2f}/month[/yellow]")
    console.print(table)

    # Top agents
    if data.get("top_agents"):
        console.print()
        console.print("[bold]Top Agents by Cost[/bold]")
        agents_table = Table()
        agents_table.add_column("Agent", style="cyan")
        agents_table.add_column("Cost", justify="right", style="green")
        agents_table.add_column("Calls", justify="right")
        agents_table.add_column("Waste %", justify="right")
        for a in data["top_agents"][:5]:
            agents_table.add_row(
                a["agent_name"],
                f"${a['total_cost']:.2f}",
                str(a["call_count"]),
                f"[red]{a['waste_pct']:.0f}%[/red]" if a["waste_pct"] > 10 else f"{a['waste_pct']:.0f}%",
            )
        console.print(agents_table)
    console.print()


@cli.command()
@click.pass_context
def agents(ctx):
    """List all agents with cost summaries."""
    data = _api(ctx.obj["server"], "/agents", {"project": ctx.obj["project"]})

    table = Table(title="Agents")
    table.add_column("Agent", style="cyan")
    table.add_column("Total Cost", justify="right", style="green")
    table.add_column("Tokens", justify="right")
    table.add_column("Calls", justify="right")
    table.add_column("Avg Latency", justify="right")
    table.add_column("Waste", justify="right", style="red")
    table.add_column("Top Model")

    for a in data:
        table.add_row(
            a["agent_name"],
            f"${a['total_cost']:.4f}",
            f"{a['total_tokens']:,}",
            str(a["call_count"]),
            f"{a['avg_latency']:.0f}ms",
            f"${a['waste_cost']:.4f} ({a['waste_pct']:.0f}%)",
            a.get("top_model", "-"),
        )
    console.print(table)


@cli.command()
@click.pass_context
def waste(ctx):
    """Show all detected waste flags."""
    data = _api(ctx.obj["server"], "/waste", {"project": ctx.obj["project"]})

    if not data:
        console.print("[green]No waste detected. Your agents are running clean.[/green]")
        return

    table = Table(title="Waste Flags")
    table.add_column("Agent", style="cyan")
    table.add_column("Type", style="yellow")
    table.add_column("Waste", justify="right", style="red")
    table.add_column("Suggestion")

    for w in data:
        table.add_row(
            w["agent_name"],
            w["waste_type"],
            f"${w['estimated_waste_usd']:.2f}",
            (w.get("suggestion") or "")[:80],
        )
    console.print(table)


@cli.command(name="recommend")
@click.pass_context
def recommendations(ctx):
    """Show model routing recommendations."""
    data = _api(ctx.obj["server"], "/recommendations", {"project": ctx.obj["project"]})

    if not data:
        console.print("[green]No routing recommendations yet. Need more usage data.[/green]")
        return

    table = Table(title="Routing Recommendations")
    table.add_column("Agent", style="cyan")
    table.add_column("Current Model")
    table.add_column("Recommended", style="green")
    table.add_column("Savings/mo", justify="right", style="yellow")
    table.add_column("Confidence", justify="right")

    for r in data:
        conf_color = "green" if r["confidence"] >= 0.7 else "yellow" if r["confidence"] >= 0.5 else "red"
        table.add_row(
            r["agent_name"],
            r["current_model"],
            r["recommended_model"],
            f"${r['estimated_monthly_savings']:.0f}",
            f"[{conf_color}]{r['confidence']:.0%}[/{conf_color}]",
        )
    console.print(table)


if __name__ == "__main__":
    cli()
