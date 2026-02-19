"""
GeoKG-RAG — Main Entry Points
CLI for running the agent interactively or starting the API server.

Usage:
    # Interactive CLI
    python main.py query "Who funds the armed group in Eastern Ukraine?"
    python main.py query "Is the Middle East approaching a conflict threshold?"

    # Start API server
    python main.py server

    # Run ingestion
    python main.py ingest --hours-back 2

    # Run pattern scan
    python main.py scan

    # Seed historical data
    python main.py seed --acled data/acled.csv
"""
from __future__ import annotations
import logging
import sys
from pathlib import Path
import config

import typer
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.WARNING,  # Quiet for CLI usage
    format="%(levelname)s — %(message)s",
)

app = typer.Typer(
    name="geokg-rag",
    help="🌍 GeoKG-RAG Geopolitical Intelligence Agent",
    add_completion=False,
)
console = Console()


@app.command("query")
def run_query_cli(
    query: str = typer.Argument(..., help="Intelligence query to analyze"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show processing details"),
):
    """Submit an intelligence query and display the report."""
    if verbose:
        logging.getLogger().setLevel(logging.INFO)

    console.print(f"\n[bold cyan]🌍 GeoKG-RAG Intelligence Query[/bold cyan]")
    console.print(f"[dim]Query: {query}[/dim]\n")

    try:
        with console.status("[bold green]Processing intelligence query..."):
            from agent.geokg_agent import run_query
            result = run_query(query)
    finally:
        # Close connections cleanly to suppress ResourceWarning
        try:
            import graph.neo4j_client as _nmod
            if _nmod._client:
                _nmod._client.close()
                _nmod._client = None
        except Exception:
            pass
        try:
            import retrieval.weaviate_client as _wmod
            if _wmod._client:
                _wmod._client.close()
                _wmod._client = None
        except Exception:
            pass

    # Display results
    console.print(Panel(
        Markdown(result.get("report", "No report generated.")),
        title=f"[bold]Intelligence Report[/bold] [dim](type: {result.get('query_type', '?')})[/dim]",
        border_style="cyan",
    ))

    if result.get("pattern_alerts"):
        console.print("\n[bold red]⚠  Active Pattern Alerts:[/bold red]")
        for alert in result["pattern_alerts"]:
            console.print(
                f"  [{alert.get('alert_level', '?')}] "
                f"{alert.get('signature_name', '?')} @ {alert.get('region', '?')}"
            )

    if result.get("sources_used"):
        console.print(f"\n[dim]Sources: {', '.join(result['sources_used'][:5])}[/dim]")

    console.print(f"[dim]Processing time: {result.get('processing_time_ms', 0):.0f}ms[/dim]\n")


@app.command("server")
def run_server(
    host: str = typer.Option("0.0.0.0", help="API host"),
    port: int = typer.Option(8000, help="API port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes"),
):
    """Start the FastAPI intelligence API server."""
    import uvicorn
    console.print(f"\n[bold green]🚀 Starting GeoKG-RAG API[/bold green]")
    console.print(f"  API:  http://{host}:{port}")
    console.print(f"  Docs: http://{host}:{port}/docs\n")
    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@app.command("ingest")
def run_ingestion(
    hours_back: int = typer.Option(1, "--hours-back", help="Hours to look back"),
    loop: bool = typer.Option(False, "--loop", help="Run continuously"),
    interval: int = typer.Option(15, "--interval", help="Interval in minutes (loop mode)"),
):
    """Run the news ingestion pipeline."""
    logging.getLogger().setLevel(logging.INFO)
    from scripts.run_ingestion import run_cycle
    import time

    console.print(f"\n[bold]📡 Starting Ingestion (hours_back={hours_back})[/bold]\n")
    if loop:
        while True:
            run_cycle(hours_back=hours_back)
            console.print(f"[dim]Sleeping {interval} minutes...[/dim]")
            time.sleep(interval * 60)
    else:
        run_cycle(hours_back=hours_back)


@app.command("scan")
def run_scan(
    region: str = typer.Option(None, "--region", help="Specific region to scan"),
    loop: bool = typer.Option(False, "--loop", help="Run hourly"),
):
    """Run conflict pattern detection scan."""
    logging.getLogger().setLevel(logging.INFO)
    from scripts.run_pattern_scan import run_scan as _scan
    import time

    console.print(f"\n[bold]🔍 Running Pattern Scan[/bold]\n")
    if loop:
        while True:
            _scan(region)
            console.print("[dim]Next scan in 1 hour...[/dim]")
            time.sleep(3600)
    else:
        _scan(region)


@app.command("seed")
def seed_data(
    acled: str = typer.Option(None, "--acled", help="Path to ACLED CSV"),
    gdelt: str = typer.Option(None, "--gdelt", help="Path to GDELT CSV"),
    un_sanctions: str = typer.Option(None, "--un-sanctions", help="Path to UN XML"),
    limit: int = typer.Option(50000, "--limit", help="Max events per source"),
    static_only: bool = typer.Option(False, "--static-only", help="Seed only built-in actors"),
):
    """Seed Neo4j with historical geopolitical data."""
    logging.getLogger().setLevel(logging.INFO)

    from graph.neo4j_client import get_neo4j_client
    from graph.delta_writer import DeltaGraphWriter
    from scripts.seed_historical import (
        seed_static_actors, load_acled, load_gdelt_csv, load_un_sanctions
    )

    # ── Pre-flight URI check ──────────────────────────────────────
    raw_uri = config.NEO4J_URI
    if raw_uri.startswith("http://") or raw_uri.startswith("https://"):
        console.print(
            f"[yellow]⚠  NEO4J_URI is {raw_uri!r} — auto-correcting to bolt://[/yellow]"
        )
        console.print("[dim]   Update your .env:  NEO4J_URI=bolt://localhost:7687[/dim]")

    try:
        neo4j = get_neo4j_client()
    except Exception as e:
        console.print(f"[bold red]{e}[/bold red]")
        raise typer.Exit(1)

    if not neo4j.verify_connectivity():
        console.print("[bold red]❌ Neo4j is not reachable.[/bold red]")
        console.print("[dim]   Make sure Docker is running: docker compose up -d neo4j[/dim]")
        console.print("[dim]   Then wait ~30 seconds and try again.[/dim]")
        raise typer.Exit(1)

    neo4j.initialize_schema()
    writer = DeltaGraphWriter(neo4j)

    seed_static_actors(writer)

    if not static_only:
        if acled:
            load_acled(acled, writer, limit=limit)
        if gdelt:
            load_gdelt_csv(gdelt, writer, limit=limit)
        if un_sanctions:
            load_un_sanctions(un_sanctions, writer)

    console.print("[bold green]✅ Seeding complete![/bold green]")


@app.command("train-gnn")
def train_gnn(
    epochs: int = typer.Option(100, "--epochs", help="Training epochs"),
    confidence: float = typer.Option(0.65, "--confidence", help="Prediction confidence threshold"),
    write: bool = typer.Option(True, "--write/--no-write", help="Write predictions to graph"),
):
    """Train link prediction GNN and infer hidden proxy relations."""
    logging.getLogger().setLevel(logging.INFO)
    from intelligence.proxy_detector import ProxyDetector

    console.print("[bold]🧠 Training RotatE link prediction model...[/bold]")
    detector = ProxyDetector()
    predictions = detector.run_full_pipeline(
        retrain=True,
        confidence_threshold=confidence,
    )
    console.print(f"✅ Predicted {len(predictions)} new relations above {confidence:.0%} confidence")
    if predictions:
        for p in predictions[:10]:
            console.print(f"  ({p['subject']}) --[{p['relation']}]--> ({p['object']}) [{p['confidence']:.2f}]")


if __name__ == "__main__":
    app()
