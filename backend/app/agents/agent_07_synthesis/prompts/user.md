# Report Synthesis Task

**Pipeline Run ID** : {{query_id}}
**Asset Under Review**: {{asset}}
**Critic Verdict**  : {{verdict}}
**Overall Confidence**: {{overall_confidence}}

---

## ⚠ LOCKED VALUES — REFERENCE THESE EXACTLY IN YOUR OUTPUT

These were computed deterministically by Python code. Do NOT derive your own values.

| Field | Locked Value |
|---|---|
| `dashboard.meta.verdict` | **{{verdict}}** |
| `dashboard.meta.overall_confidence` | **{{overall_confidence}}** |
| `dashboard.risk_gauge.score` | **{{risk_gauge_score}}** |
| `dashboard.risk_gauge.level` | **{{risk_gauge_level}}** |
| `dashboard.scenario_probabilities.bull` | **{{bull_pct}}%** |
| `dashboard.scenario_probabilities.base` | **{{base_pct}}%** |
| `dashboard.scenario_probabilities.bear` | **{{bear_pct}}%** |

---

## Pre-Computed Dashboard (Ground Truth)

Use this as your primary data reference for the `executive_summary`,
`key_risks`, `key_opportunities`, and `reasoning_trace`.

```json
{{dashboard_json}}
```

---

## Full Pipeline JSON — Evidence Base

The complete agent outputs from the pipeline run. Use for narrative sections.
Treat as read-only evidence — do not validate or supplement from external knowledge.

```json
{{pipeline_json}}
```

---

## ⚠ FORBIDDEN (Hallucination Patterns)

- Contradicting `risk_gauge.level = {{risk_gauge_level}}`
- Contradicting `overall_confidence = {{overall_confidence}}`
- Issuing buy/sell/hold/long/short recommendations
- Stating future prices as certainties
- Using training knowledge to add market facts not in the JSON
- Producing `scenario_outlook` with bull/base/bear percentages different from the locked values

---

## Your Task

1. Write `executive_summary` — 1–2 sentences citing the asset, verdict, and dominant risk.
2. Write `narrative_sections.geopolitical_context` — cite stability_score, key_events.
3. Write `narrative_sections.market_sentiment` — cite sentiment_score, fear_greed_index.
4. Write `narrative_sections.asset_analysis` — cite price_trend, key_patterns, current_price.
5. Write `narrative_sections.risk_assessment` — cite volatility_30d, var_95, risk_level.
6. Write `narrative_sections.scenario_outlook` — use **locked** bull/base/bear percentages.
7. Write `key_risks` — 3–6 items derived from the data.
8. Write `key_opportunities` — 0–4 items (empty list if signals are purely bearish).
9. Write `reasoning_trace` using the structured format from your system prompt.

Return ONLY the JSON object. Begin now.
