# Orchestration Step-by-Step Traceability

This file tracks how each orchestration step is executed, validated, and evidenced.

## Traceability Matrix

| Step | Component | Input | Output | Control/Validation | Evidence Location |
|---|---|---|---|---|---|
| 0S | Secrets Gate (`settings.py` + `app/security/vault.py`) | Vault config + env vars | Gemini API key + source (`vault`/`env`/`missing`) | Vault-first resolution policy, env fallback, refresh-based rotation pickup | `normalized_input.pipeline.gemini_key_source`, `reasoning_trace` (`secrets:*`) |
| 0 | Security Gate (`security.py`) | Raw user query | Sanitized query + risk score + risk level | Prompt-injection rule scoring; high-risk LLM block flag | `normalized_input.security`, `reasoning_trace` (`security:*`) |
| 1 | Routing (`agent_01_routing`) | Sanitized query + optional hints | `asset`, `timeframe`, `risk_focus` | Hint precedence, fallback defaults | `reports[agent_01_routing].payload` |
| 2A | Geopolitical (`agent_02_geopolitical`) | Sanitized query | `risk_score`, `drivers` | Heuristic weighted trigger rules | `reports[agent_02_geopolitical].payload` |
| 2B | Sentiment (`agent_03_sentiment`) | Sanitized query | `sentiment_score`, `label` | Positive/negative cue scoring | `reports[agent_03_sentiment].payload` |
| 2P | Parallelization Control (`parallel_02_03` node) | Step 2A + Step 2B | Concurrent execution of both stages | LangGraph node executes `ThreadPoolExecutor(max_workers=2)` with deterministic report ordering | `reasoning_trace` contains parallel marker |
| 3 | Asset Analyst (`agent_04_asset_analyst`) | Routed asset + geo score + sentiment score | `implied_risk`, regime, low/mid/high move bands | Bounded risk transformation and regime mapping | `reports[agent_04_asset_analyst].payload` |
| 4 | Critic (`agent_05_critic`) | Geo/sentiment/asset outputs | `PASS` or `REVISE` + reason | Contradiction and consistency checks | `reports[agent_05_critic].payload`, `.reasoning` |
| 5 | Synthesis (`agent_06_report_synthesis`) | Pipeline outputs + security policy | Scenario probabilities + optional Gemini summary | Gemini gated by security + key status + fallback path | `reports[agent_06_report_synthesis].payload` |
| 6 | Final Aggregation | All reports + trace | `OrchestrationResult` | Probability normalization and structured result contract | `scenario_probabilities`, `reports`, `reasoning_trace` |

### Observability Evidence

- Per-stage runtime metrics are attached under:
  - `normalized_input.pipeline.timing_ms`
  - `reports[*].payload.timing_ms` (for stage payloads)
- Orchestration runtime metadata is attached under:
  - `normalized_input.pipeline.orchestration_runtime`
- Secret source metadata is attached under:
  - `normalized_input.pipeline.gemini_key_source`
- Parallel stage declaration is attached under:
  - `normalized_input.pipeline.parallel_stage`

## Security Traceability Rules

- If prompt-injection risk is `high`, then Gemini is blocked:
  - `gemini_status = blocked_prompt_injection`
  - simulation output still returns normally
- If Gemini key missing:
  - `gemini_status = missing_api_key`
- If Vault is enabled and key exists in configured path/field:
  - `gemini_key_source = vault`
- If Vault is unavailable/empty and env key exists:
  - `gemini_key_source = env`
- If Gemini API fails:
  - `gemini_status = failed_or_empty`
  - `gemini_error` contains error reason
- For transient API/network failures:
  - Gemini client retries with exponential backoff before fallback
- If Gemini succeeds:
  - `gemini_status = used`
  - `gemini_summary` is present

## Test Traceability (Code-Level)

- `test_orchestration.py`
  - validates pipeline structure, parallel marker, probability sum, injection block path
- `test_orchestration_scenarios.py`
  - validates multiple realistic scenarios (Brent, crypto, equity index, security)

Run tests:

```bash
python3 -m unittest app.orchestration.test_orchestration app.orchestration.test_orchestration_scenarios -v
```

## Runtime Traceability (Demo-Level)

Run showcase:

```bash
GEMINI_API_KEY="<key>" GEMINI_MODEL="gemini-2.5-flash" python3 -m app.orchestration.showcase_orchestrator
```

What this demonstrates:

1. End-to-end pipeline integrity checks
2. Per-agent status and confidence
3. Security gate decision and reasons
4. Prompt-injection block in malicious scenario
5. Final probability distribution and verdict

## Acceptance Checklist

- [ ] Step 0 security metadata appears in `normalized_input.security`
- [ ] Parallel marker exists in `reasoning_trace`
- [ ] Exactly 6 agent reports are returned in expected order
- [ ] Probability keys are present (`high_risk`, `base_case`, `low_risk`) and sum to ~1
- [ ] Critic verdict exists (`PASS` or `REVISE`)
- [ ] Gemini status correctly reflects policy/runtime conditions
