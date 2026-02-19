from __future__ import annotations

import argparse
import json
import uuid

from .orchestrator import SentinelOrchestrator
from .types import OrchestrationRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SentinelAI orchestrator in simulation mode")
    parser.add_argument("query", type=str, help="Natural-language risk query")
    parser.add_argument("--asset", dest="asset_hint", default=None)
    parser.add_argument("--timeframe", dest="timeframe_hint", default=None)
    parser.add_argument("--focus", dest="risk_focus", default=None)
    parser.add_argument("--use-gemini", action="store_true", help="Enable Gemini synthesis if GOOGLE_API_KEY exists")
    args = parser.parse_args()

    orchestrator = SentinelOrchestrator()
    request = OrchestrationRequest(
        query=args.query,
        session_id=str(uuid.uuid4()),
        asset_hint=args.asset_hint,
        timeframe_hint=args.timeframe_hint,
        risk_focus=args.risk_focus,
        use_gemini=args.use_gemini,
    )
    result = orchestrator.run(request=request, simulation=True)

    serializable = {
        "session_id": result.session_id,
        "final_verdict": result.final_verdict,
        "scenario_probabilities": result.scenario_probabilities,
        "normalized_input": result.normalized_input,
        "reasoning_trace": result.reasoning_trace,
        "reports": [
            {
                "agent_name": report.agent_name,
                "status": report.status,
                "confidence": report.confidence,
                "payload": report.payload,
                "reasoning": report.reasoning,
                "timestamp": report.timestamp,
            }
            for report in result.reports
        ],
    }
    print(json.dumps(serializable, indent=2))


if __name__ == "__main__":
    main()
