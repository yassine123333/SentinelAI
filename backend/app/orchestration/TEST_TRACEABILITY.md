# Orchestrator Test Traceability Report

## Scope

This report provides test traceability for the orchestration layer in:

- `backend/app/orchestration`

It covers pipeline integrity, parallel stage behavior, prompt-injection defense,
and scenario output consistency.

## Test Artifacts

- Unit test source:
  - `test_orchestration.py`
  - `test_orchestration_scenarios.py`
- Execution logs:
  - `test_traceability_unittest.log`
  - `test_traceability_showcase.log`

## Execution Commands

Unit tests:

```bash
python3 -m unittest app.orchestration.test_orchestration app.orchestration.test_orchestration_scenarios -v
```

Scenario showcase:

```bash
GEMINI_API_KEY="<key>" GEMINI_MODEL="gemini-2.5-flash" python3 -m app.orchestration.showcase_orchestrator
```

## Latest Results

- Unit tests: **PASS**
  - `Ran 6 tests in 0.005s`
  - `OK`
- Showcase scenarios: **PASS**
  - `3/3 scenarios passed integrity checks`

## Requirement → Test Mapping

1. Sequential orchestration chain is stable
   - Tests:
     - `TestSentinelOrchestration.test_simulation_pipeline_has_expected_structure`
     - `TestOrchestrationScenarios.test_reference_brent_macro_scenario`
   - Evidence:
     - report count = 6
     - first agent = `agent_01_routing`
     - last agent = `agent_07_synthesis`

2. `agent_02_geopolitical` and `agent_03_sentiment` run in parallel
   - Tests:
     - `TestSentinelOrchestration.test_simulation_pipeline_has_expected_structure`
     - `TestOrchestrationScenarios.test_reference_brent_macro_scenario`
   - Evidence:
     - trace contains: `parallel: agent_02_geopolitical and agent_03_sentiment executed concurrently`

3. Probability output is normalized and valid
   - Tests:
     - `TestSentinelOrchestration.test_simulation_pipeline_has_expected_structure`
     - scenario helper `_assert_probabilities()` in `test_orchestration_scenarios.py`
   - Evidence:
     - keys: `high_risk`, `base_case`, `low_risk`
     - all values in `[0, 1]`
     - sum ≈ 1.0

4. Prompt injection is detected and LLM path is blocked at high risk
   - Tests:
     - `TestSentinelOrchestration.test_high_risk_prompt_injection_blocks_gemini`
     - `TestOrchestrationScenarios.test_prompt_injection_block_path`
   - Evidence:
     - `prompt_injection_risk = high`
     - score threshold met (`>= 7`)
     - synthesis payload `gemini_status = blocked_prompt_injection`

5. Asset/timeframe/focus hints are respected
   - Tests:
     - `TestOrchestrationScenarios.test_crypto_hint_and_short_horizon`
   - Evidence:
     - input echoes `BTC-USD`, `14 days`, `volatility`

6. Equity index symbol parsing works (`^GSPC`)
   - Tests:
     - `TestOrchestrationScenarios.test_equity_index_stable_context`
   - Evidence:
     - normalized asset equals `^GSPC`

## Scenario Evidence Summary (Showcase)

1. Brent geopolitical + macro scenario
   - Final verdict: `PASS`
   - Security: `risk=low score=0`
   - Gemini: `used`
   - Probabilities: `high=72.63% | base=5.23% | low=22.14%`

2. Crypto stress scenario (no Gemini requested)
   - Final verdict: `PASS`
   - Security: `risk=low score=0`
   - Gemini: `not_requested`
   - Probabilities: `high=70.89% | base=4.80% | low=24.31%`

3. Prompt-injection security scenario
   - Final verdict: `PASS`
   - Security: `risk=high score=11`
   - Gemini: `blocked_prompt_injection`
   - Security reasons include instruction override, prompt exfiltration, tool coercion

## Conclusion

Traceability confirms that the orchestration layer is robust for current
simulation scope:

- Pipeline integrity is stable.
- Parallel stage is enforced and observable.
- Prompt-injection defense is active and effective.
- Scenario outputs remain structured and consistent.
