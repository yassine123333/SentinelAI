# Critic Evaluation Task

**Pipeline Run ID** : {{query_id}}
**Asset Under Review**: {{asset}}
**Attempt Number**  : {{attempt}}

---

## ⚠ LOCKED VALUES — COPY VERBATIM INTO OUTPUT

These were computed by deterministic Python code and are the ground truth.
Any deviation is a self-consistency failure and hallucination.

| Output field                              | Required value                       |
|------------------------------------------|--------------------------------------|
| `sources_verified`                       | **{{locked_sources_verified}}**      |
| `sources_total`                          | **{{locked_sources_total}}**         |
| `overall_confidence`                     | **{{locked_aggregate_confidence}}**  |
| `checks[source_attribution].passed`      | **{{locked_source_passed}}**         |
| `checks[confidence_calibration].passed`  | **{{locked_confidence_passed}}**     |
| `timestamp`                              | `"deterministic"`                    |

---

## Pre-Computed Deterministic Checks (Ground Truth)

Do NOT contradict these. Do NOT add to them.

### A. Source Verification
```json
{{source_check}}
```

### B. Consistency Check
```json
{{consistency_check}}
```

### C. Confidence Breakdown
```json
{{confidence_check}}
```

---

## Full Pipeline JSON — Read-Only Evidence

Treat this as a read-only document. Do not use training knowledge to supplement
or correct it. Do not extract market insights beyond what the text literally states.

```json
{{pipeline_json}}
```

---

## ⚠ FORBIDDEN (Hallucination Patterns)

- Producing `sources_verified` ≠ {{locked_sources_verified}}
- Producing `sources_total` ≠ {{locked_sources_total}}
- Producing `overall_confidence` ≠ {{locked_aggregate_confidence}}
- Issuing PASS on `source_attribution` when `source_check.passed` = {{locked_source_passed}}
- Issuing PASS on `confidence_calibration` when `confidence_check.passed` = {{locked_confidence_passed}}
- Inventing contradictions not in `consistency_check.contradictions`
- Stating market facts from training data ("historically X tends to...")
- Producing point price predictions as certainties
- Generating any timestamp other than `"deterministic"`
- Producing `retry_instructions` when verdict = PASS
- Omitting `retry_instructions` when verdict = FAIL

---

## Your Task

1. Fill in the locked fields from the table above — copy the exact values.
2. `source_attribution` → follow `source_check` exactly.
3. `internal_consistency` → follow `consistency_check` exactly, do not add contradictions.
4. `confidence_calibration` → follow `confidence_check` exactly.
5. `narrative_coherence` → evaluate ONLY the text in agent summaries from the pipeline JSON.
   Cite evidence as `[agent_id.field = "value"] → conclusion`.
6. `completeness` → check field presence/emptiness in the pipeline JSON only.
7. Write `reasoning_trace` in the Evidence-Anchored Format from your system prompt.
8. On FAIL: write `retry_instructions` with specific `agent_id.field = value` citations.
9. Run self-consistency check before outputting.

Return ONLY the JSON object. Begin now.
