"""
main.py — SOC Multi-Agent Security System: LangGraph Orchestrator
=================================================================
Architecture:
    Ingestion → [Identity ‖ ThreatIntel ‖ Pattern] → Reasoning → Action → END

Environment setup:
    export GROQ_API_KEY="your-groq-api-key-here"
    # Free key at https://console.groq.com

Install dependencies:
    pip install langgraph langchain-core groq

Usage:
    # Read a specific log file
    python main.py --log-file /var/log/nginx/access.log

    # Read from stdin (pipe)
    tail -f /var/log/nginx/access.log | python main.py --stdin

    # Read only the last N lines from a file
    python main.py --log-file /var/log/nginx/access.log --tail 500

    # Watch mode: monitor the file in real-time (like tail -f)
    python main.py --log-file /var/log/nginx/access.log --watch

    # Default path if no argument given: /var/log/nginx/access.log
    python main.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Generator, TypedDict

from langgraph.graph import END, StateGraph

from .agents import (
    action_agent,
    get_blocked_ips,
    identity_agent,
    ingestion_agent,
    pattern_agent,
    reasoning_agent,
    reset_session_state,
    threat_intel_agent,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Default Nginx log file path
DEFAULT_LOG_PATH = Path("/var/log/nginx/access.log")


# ===========================================================================
# LangGraph State Definition
# ===========================================================================

class SOCState(TypedDict, total=False):
    """
    Shared state passed between LangGraph nodes.

    All fields are optional (total=False) because nodes populate them
    incrementally as the graph executes.
    """
    # Raw input
    raw_log: str

    # IngestionAgent output
    parsed_log: dict[str, Any] | None

    # Sub-agent findings
    identity_finding: dict[str, Any]
    threat_intel_finding: dict[str, Any]
    pattern_finding: dict[str, Any]

    # ReasoningAgent output
    reasoning_decision: dict[str, Any]

    # ActionAgent output
    action_result: dict[str, Any]

    # Aggregated findings forwarded to Reasoning
    aggregated_findings: dict[str, Any]


# ===========================================================================
# Graph Node Functions
# ===========================================================================

def node_ingestion(state: SOCState) -> SOCState:
    """Parse the raw Nginx log line into a structured dict."""
    logger.info("── Node: Ingestion ──────────────────────────────")
    raw = state["raw_log"]
    parsed = ingestion_agent(raw)
    if parsed is None:
        logger.error("Ingestion failed — skipping pipeline for this log line.")
    return {"parsed_log": parsed}


def node_identity(state: SOCState) -> SOCState:
    """Detect User-Agent IP rotation."""
    logger.info("── Node: Identity ───────────────────────────────")
    parsed = state.get("parsed_log")
    if not parsed:
        return {"identity_finding": {"agent": "IdentityAgent", "alert": False, "skipped": True}}
    finding = identity_agent(ip=parsed["ip"], user_agent=parsed["user_agent"])
    return {"identity_finding": finding}


def node_threat_intel(state: SOCState) -> SOCState:
    """Check IP against the threat-intel blocklist."""
    logger.info("── Node: ThreatIntel ────────────────────────────")
    parsed = state.get("parsed_log")
    if not parsed:
        return {"threat_intel_finding": {"agent": "ThreatIntelAgent", "is_malicious": False, "skipped": True}}
    finding = threat_intel_agent(ip=parsed["ip"])
    return {"threat_intel_finding": finding}


def node_pattern(state: SOCState) -> SOCState:
    """Detect distributed rate-limit abuse on sensitive paths."""
    logger.info("── Node: Pattern ────────────────────────────────")
    parsed = state.get("parsed_log")
    if not parsed:
        return {"pattern_finding": {"agent": "PatternAgent", "alert": False, "skipped": True}}
    finding = pattern_agent(path=parsed["path"])
    return {"pattern_finding": finding}


def node_aggregate(state: SOCState) -> SOCState:
    """
    Combine all sub-agent findings and parsed log data into a single context
    object for the ReasoningAgent.

    This node acts as the fan-in point after the parallel sub-agents.
    """
    logger.info("── Node: Aggregate ──────────────────────────────")
    parsed = state.get("parsed_log")
    # Strip bulky 'raw' field to save tokens when sent to the LLM
    parsed_slim = None
    if parsed:
        parsed_slim = {k: v for k, v in parsed.items() if k != "raw"}
    aggregated: dict[str, Any] = {
        "parsed_log": parsed_slim,
        "identity": state.get("identity_finding", {}),
        "threat_intel": state.get("threat_intel_finding", {}),
        "pattern": state.get("pattern_finding", {}),
    }
    logger.info("Aggregated findings:\n%s", json.dumps(aggregated, indent=2, default=str))
    return {"aggregated_findings": aggregated}


def node_reasoning(state: SOCState) -> SOCState:
    """Send aggregated findings to Groq llama-3.1-8b-instant for the final decision."""
    logger.info("── Node: Reasoning (Groq llama-3.1-8b-instant) ──")
    findings = state.get("aggregated_findings", {})
    decision = reasoning_agent(findings=findings)
    return {"reasoning_decision": decision}


def node_action(state: SOCState) -> SOCState:
    """Execute the enforcement action (block / allow)."""
    logger.info("── Node: Action ─────────────────────────────────")
    parsed = state.get("parsed_log")
    decision = state.get("reasoning_decision", {"decision": "ALLOW", "reason": "No decision made."})
    ip = parsed["ip"] if parsed else "unknown"
    result = action_agent(ip=ip, decision=decision)
    return {"action_result": result}


# ===========================================================================
# Graph Construction
# ===========================================================================

def build_graph() -> Any:
    """
    Construct the LangGraph StateGraph.

    Flow:
        ingestion
            ↓
        identity ─┐
        threat     ├─ (sequential fan-out; LangGraph Pro supports true parallel)
        pattern  ──┘
            ↓
        aggregate
            ↓
        reasoning
            ↓
        action
            ↓
           END
    """
    builder = StateGraph(SOCState)

    # Register nodes
    builder.add_node("ingestion",    node_ingestion)
    builder.add_node("identity",     node_identity)
    builder.add_node("threat_intel", node_threat_intel)
    builder.add_node("pattern",      node_pattern)
    builder.add_node("aggregate",    node_aggregate)
    builder.add_node("reasoning",    node_reasoning)
    builder.add_node("action",       node_action)

    # Entry point
    builder.set_entry_point("ingestion")

    # ingestion → three analysis nodes (sequential; swap for parallel with Send API)
    builder.add_edge("ingestion",    "identity")
    builder.add_edge("ingestion",    "threat_intel")
    builder.add_edge("ingestion",    "pattern")

    # Fan-in to aggregate
    builder.add_edge("identity",     "aggregate")
    builder.add_edge("threat_intel", "aggregate")
    builder.add_edge("pattern",      "aggregate")

    # Linear tail
    builder.add_edge("aggregate",  "reasoning")
    builder.add_edge("reasoning",  "action")
    builder.add_edge("action",     END)

    return builder.compile()


# ===========================================================================
# Nginx Log File Readers
# ===========================================================================

def _is_comment_or_empty(line: str) -> bool:
    """Skip blank lines and comments."""
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def read_log_file(path: Path, tail: int | None = None) -> list[tuple[str, str]]:
    """
    Read a static Nginx log file and return a list of (log_id, raw_line)
    tuples ready to be processed by the pipeline.

    Parameters
    ----------
    path:
        Path to the Nginx access.log file.
    tail:
        If provided, only read the last N lines (equivalent to tail -n N).
    """
    if not path.exists():
        logger.error("Log file not found: %s", path)
        sys.exit(1)

    if not path.is_file():
        logger.error("Path is not a file: %s", path)
        sys.exit(1)

    logger.info("Reading log file: %s", path)

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        all_lines = fh.readlines()

    lines = all_lines[-tail:] if tail and tail > 0 else all_lines

    entries: list[tuple[str, str]] = []
    for idx, line in enumerate(lines, start=1):
        raw = line.rstrip("\n")
        if _is_comment_or_empty(raw):
            continue
        entries.append((f"LINE-{idx:06d}", raw))

    logger.info("%d valid lines read from %s", len(entries), path)
    return entries


def read_stdin() -> list[tuple[str, str]]:
    """
    Read log lines from stdin (useful with pipe or redirection).

    Example: tail -n 100 /var/log/nginx/access.log | python main.py --stdin
    """
    logger.info("Reading logs from stdin…")
    entries: list[tuple[str, str]] = []
    for idx, line in enumerate(sys.stdin, start=1):
        raw = line.rstrip("\n")
        if _is_comment_or_empty(raw):
            continue
        entries.append((f"STDIN-{idx:06d}", raw))
    logger.info("%d lines read from stdin", len(entries))
    return entries


def watch_log_file(
    path: Path,
    graph: Any,
    poll_interval: float = 0.5,
) -> Generator[dict[str, Any], None, None]:
    """
    Monitor a Nginx log file in real-time (tail -f mode).

    Uses a file cursor to only process new lines appended after startup.
    Log rotation is detected when the file shrinks.

    Parameters
    ----------
    path:
        Path to the Nginx access.log file.
    graph:
        Compiled LangGraph StateGraph.
    poll_interval:
        Seconds between file checks.

    Yields
    ------
    The final SOCState for each new line processed.
    """
    if not path.exists():
        logger.error("Log file not found for watch mode: %s", path)
        sys.exit(1)

    print(f"\n  👁️   Watch mode active — monitoring: {path}")
    print("  Press Ctrl+C to stop.\n")

    line_count = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        # Seek to end — only process NEW lines
        fh.seek(0, 2)
        last_size = fh.tell()

        try:
            while True:
                current_size = path.stat().st_size

                # Detect log rotation (file was truncated)
                if current_size < last_size:
                    logger.warning("Log rotation detected — seeking to beginning.")
                    fh.seek(0)
                    last_size = 0

                line = fh.readline()
                if not line:
                    time.sleep(poll_interval)
                    continue

                raw = line.rstrip("\n")
                last_size = fh.tell()

                if _is_comment_or_empty(raw):
                    continue

                line_count += 1
                log_id = f"WATCH-{line_count:06d}"
                state = run_pipeline(log_id, raw, graph)
                yield state

        except KeyboardInterrupt:
            print("\n\n  ⏹️   Watch mode stopped by user.\n")


# ===========================================================================
# Pipeline Runner
# ===========================================================================

def run_pipeline(log_id: str, raw_log: str, graph: Any) -> dict[str, Any]:
    """Execute the LangGraph pipeline for a single log line."""
    print(f"\n{'─' * 70}")
    print(f"  📄  [{log_id}]")
    print(f"  {raw_log[:95]}{'…' if len(raw_log) > 95 else ''}")
    print(f"{'─' * 70}")

    initial_state: SOCState = {"raw_log": raw_log}
    final_state: SOCState = graph.invoke(initial_state)
    return final_state


def print_summary(results: list[dict[str, Any]]) -> None:
    """Print the summary table at the end of processing."""
    blocked = get_blocked_ips()
    print("\n" + "═" * 70)
    print("  📋  PIPELINE SUMMARY")
    print("═" * 70)
    for r in results:
        icon = "🚫" if r["verdict"] == "BLOCK" else "✅"
        fallback = " ⚠️ [heuristic]" if r.get("fallback") else ""
        print(
            f"  {icon}  [{r['log_id']:18s}]  "
            f"IP: {str(r['ip']):18s}  "
            f"Verdict: {r['verdict']}{fallback}"
        )
    print(f"\n  Total IPs blocked this session: {len(blocked)}")
    if blocked:
        print(f"  Blocked IPs: {', '.join(sorted(blocked))}")
    print("═" * 70 + "\n")


# ===========================================================================
# Argument Parser
# ===========================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SOC Multi-Agent Security System — Real Nginx log analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py
  python main.py --log-file /var/log/nginx/access.log
  python main.py --log-file /var/log/nginx/access.log --tail 200
  python main.py --log-file /var/log/nginx/access.log --watch
  tail -f /var/log/nginx/access.log | python main.py --stdin
        """,
    )

    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--log-file",
        metavar="PATH",
        type=Path,
        default=DEFAULT_LOG_PATH,
        help=f"Path to the Nginx access.log file (default: {DEFAULT_LOG_PATH})",
    )
    source_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read log lines from stdin (pipe)",
    )

    parser.add_argument(
        "--tail",
        metavar="N",
        type=int,
        default=None,
        help="Only process the last N lines of the file (ignored with --stdin/--watch)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Real-time mode: monitor the file and process new lines (like tail -f)",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Application log verbosity level (default: INFO)",
    )

    return parser.parse_args()


# ===========================================================================
# Main Entry Point
# ===========================================================================

def main() -> None:
    args = parse_args()

    # Adjust log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    reset_session_state()

    print("\n" + "═" * 70)
    print("  🛡️   SOC Multi-Agent Security System — Starting")
    if args.stdin:
        print("  Source: stdin")
    elif args.watch:
        print(f"  Source: {args.log_file}  [watch mode]")
    else:
        tail_info = f"  (last {args.tail} lines)" if args.tail else ""
        print(f"  Source: {args.log_file}{tail_info}")
    print("═" * 70)

    graph = build_graph()

    # ── Watch mode (real-time) ───────────────────────────────────────────
    if args.watch:
        if args.stdin:
            print("  ❌  --watch and --stdin are incompatible.")
            sys.exit(1)

        results: list[dict[str, Any]] = []
        for state in watch_log_file(args.log_file, graph):
            results.append({
                "log_id": "WATCH",
                "ip": state.get("parsed_log", {}).get("ip") if state.get("parsed_log") else None,
                "verdict": state.get("reasoning_decision", {}).get("decision"),
                "fallback": state.get("reasoning_decision", {}).get("fallback", False),
                "action": state.get("action_result", {}).get("action_taken"),
            })
        print_summary(results)
        return

    # ── Batch mode (file or stdin) ───────────────────────────────────────
    if args.stdin:
        log_entries = read_stdin()
    else:
        log_entries = read_log_file(args.log_file, tail=args.tail)

    if not log_entries:
        print("  ⚠️   No valid log lines found. Check your file or filter.")
        sys.exit(0)

    print(f"\n  {len(log_entries)} lines to analyze…\n")

    results = []
    for log_id, raw_log in log_entries:
        state = run_pipeline(log_id, raw_log, graph)
        results.append({
            "log_id": log_id,
            "ip": state.get("parsed_log", {}).get("ip") if state.get("parsed_log") else None,
            "verdict": state.get("reasoning_decision", {}).get("decision"),
            "fallback": state.get("reasoning_decision", {}).get("fallback", False),
            "action": state.get("action_result", {}).get("action_taken"),
        })

    print_summary(results)


if __name__ == "__main__":
    main()
