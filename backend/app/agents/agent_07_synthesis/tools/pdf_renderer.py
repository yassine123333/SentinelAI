"""
PDF renderer for Agent 07 — Report Synthesis.

Converts the SynthesisOutput into a professional PDF report using WeasyPrint.
WeasyPrint runs locally on the FastAPI server — no external PDF service dependency.

If WeasyPrint is not installed, render_pdf() returns None gracefully so the agent
can still return the dashboard payload and narrative without a PDF attachment.
"""
from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..resources.schemas import SynthesisOutput

logger = logging.getLogger(__name__)

# ── Optional WeasyPrint import ─────────────────────────────────────────────────
try:
    from weasyprint import HTML as _WeasyHTML  # type: ignore

    _WEASYPRINT_AVAILABLE = True
except Exception:  # pragma: no cover
    _WEASYPRINT_AVAILABLE = False

# ── HTML template ──────────────────────────────────────────────────────────────
# Inline CSS ensures the PDF is self-contained and renders correctly
# without external font or stylesheet dependencies.

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SentinelAI Risk Report — {asset}</title>
  <style>
    @page {{
      size: A4;
      margin: 20mm 18mm 20mm 18mm;
    }}
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      font-family: "DejaVu Sans", "Helvetica Neue", Helvetica, Arial, sans-serif;
      font-size: 10pt;
      color: #1a202c;
      line-height: 1.55;
      margin: 0;
      padding: 0;
    }}
    /* ── Header ─────────────────────────────────────────────────────────────── */
    .report-header {{
      border-bottom: 2.5pt solid #1a365d;
      padding-bottom: 8pt;
      margin-bottom: 16pt;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
    }}
    .brand {{ font-size: 16pt; font-weight: 700; color: #1a365d; letter-spacing: 0.5pt; }}
    .brand span {{ color: #2b6cb0; }}
    .report-meta {{ text-align: right; font-size: 8pt; color: #4a5568; }}
    .report-meta .verdict-badge {{
      display: inline-block;
      padding: 2pt 8pt;
      border-radius: 3pt;
      font-weight: 700;
      font-size: 9pt;
      margin-top: 3pt;
    }}
    .verdict-pass {{ background: #c6f6d5; color: #22543d; }}
    .verdict-fail {{ background: #fed7d7; color: #742a2a; }}
    /* ── Section headings ────────────────────────────────────────────────────── */
    h1 {{ font-size: 13pt; color: #1a365d; margin: 0 0 6pt 0; font-weight: 700; }}
    h2 {{ font-size: 11pt; color: #2d3748; margin: 14pt 0 5pt 0; font-weight: 700;
          border-left: 3pt solid #2b6cb0; padding-left: 6pt; }}
    h3 {{ font-size: 10pt; color: #4a5568; margin: 10pt 0 3pt 0; font-weight: 600; }}
    /* ── Executive summary box ───────────────────────────────────────────────── */
    .exec-summary {{
      background: #ebf8ff;
      border: 1pt solid #bee3f8;
      border-radius: 4pt;
      padding: 10pt 12pt;
      margin-bottom: 14pt;
    }}
    .exec-summary p {{ margin: 0; font-size: 10.5pt; color: #1a365d; }}
    /* ── Risk overview grid ──────────────────────────────────────────────────── */
    .risk-grid {{ display: flex; gap: 10pt; margin-bottom: 12pt; }}
    .risk-card {{
      flex: 1;
      border: 1pt solid #e2e8f0;
      border-radius: 4pt;
      padding: 8pt 10pt;
      background: #f7fafc;
    }}
    .risk-card .card-label {{ font-size: 7.5pt; color: #718096; text-transform: uppercase;
                              letter-spacing: 0.4pt; margin-bottom: 3pt; }}
    .risk-card .card-value {{ font-size: 13pt; font-weight: 700; color: #1a365d; }}
    .risk-card .card-sub {{ font-size: 8pt; color: #4a5568; margin-top: 1pt; }}
    /* ── Narrative sections ──────────────────────────────────────────────────── */
    .narrative-section p {{ margin: 0 0 6pt 0; text-align: justify; }}
    /* ── Confidence table ────────────────────────────────────────────────────── */
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 12pt; }}
    th {{ background: #2d3748; color: #fff; font-size: 8.5pt; padding: 5pt 8pt;
          text-align: left; font-weight: 600; }}
    td {{ padding: 4pt 8pt; font-size: 8.5pt; border-bottom: 0.5pt solid #e2e8f0; }}
    tr:nth-child(even) td {{ background: #f7fafc; }}
    .pct-bar-wrap {{ background: #e2e8f0; border-radius: 2pt; height: 6pt;
                     width: 80pt; display: inline-block; vertical-align: middle; }}
    .pct-bar {{ height: 6pt; border-radius: 2pt; background: #2b6cb0; }}
    /* ── Risks & opportunities ───────────────────────────────────────────────── */
    .risk-list {{ columns: 2; column-gap: 16pt; }}
    .risk-list li {{ font-size: 9pt; margin-bottom: 3pt; break-inside: avoid; }}
    .risk-item {{ color: #c53030; }}
    .opp-item {{ color: #276749; }}
    /* ── Scenario probabilities ──────────────────────────────────────────────── */
    .scenario-row {{ display: flex; gap: 8pt; margin-bottom: 12pt; }}
    .scenario-cell {{
      flex: 1; text-align: center;
      border: 1pt solid #e2e8f0; border-radius: 4pt; padding: 8pt;
    }}
    .scenario-cell .s-label {{ font-size: 8pt; text-transform: uppercase;
                                letter-spacing: 0.5pt; color: #718096; }}
    .scenario-cell .s-value {{ font-size: 14pt; font-weight: 700; margin: 3pt 0 1pt; }}
    .bull .s-value {{ color: #276749; }}
    .base .s-value {{ color: #2b6cb0; }}
    .bear .s-value {{ color: #c53030; }}
    /* ── Footer ──────────────────────────────────────────────────────────────── */
    .report-footer {{
      border-top: 1pt solid #e2e8f0;
      margin-top: 20pt;
      padding-top: 8pt;
      font-size: 7.5pt;
      color: #718096;
      text-align: center;
    }}
    .disclaimer {{
      font-size: 7pt;
      color: #a0aec0;
      font-style: italic;
      margin-top: 4pt;
    }}
    /* ── Page break control ──────────────────────────────────────────────────── */
    .no-break {{ page-break-inside: avoid; }}
  </style>
</head>
<body>

<!-- ── Header ─────────────────────────────────────────────────────────────── -->
<div class="report-header">
  <div>
    <div class="brand">Sentinel<span>AI</span></div>
    <div style="font-size:10pt; color:#2d3748; margin-top:2pt;">
      Geopolitical Market Intelligence Platform
    </div>
  </div>
  <div class="report-meta">
    <div><strong>Asset:</strong> {asset} &nbsp;|&nbsp;
         <strong>Run:</strong> {query_id}</div>
    <div><strong>Generated:</strong> {timestamp}</div>
    <div>
      <span class="verdict-badge {verdict_class}">{verdict}</span>
    </div>
  </div>
</div>

<!-- ── Executive Summary ───────────────────────────────────────────────────── -->
<h1>Executive Summary</h1>
<div class="exec-summary">
  <p>{executive_summary}</p>
</div>

<!-- ── Risk Overview ───────────────────────────────────────────────────────── -->
<h2>Risk Overview</h2>
<div class="risk-grid no-break">
  <div class="risk-card">
    <div class="card-label">Overall Risk</div>
    <div class="card-value">{risk_label}</div>
    <div class="card-sub">Score: {risk_score_pct}%</div>
  </div>
  <div class="risk-card">
    <div class="card-label">Geopolitical Stability</div>
    <div class="card-value">{geo_stability}/100</div>
    <div class="card-sub">{geo_events} key events</div>
  </div>
  <div class="risk-card">
    <div class="card-label">Market Sentiment</div>
    <div class="card-value">{sentiment_label}</div>
    <div class="card-sub">F&amp;G Index: {fear_greed}</div>
  </div>
  <div class="risk-card">
    <div class="card-label">Volatility (30d Ann.)</div>
    <div class="card-value">{vol_pct}%</div>
    <div class="card-sub">VaR (95%): {var_pct}%</div>
  </div>
</div>

<!-- ── Scenario Probabilities ──────────────────────────────────────────────── -->
<h2>Scenario Probabilities</h2>
<div class="scenario-row no-break">
  <div class="scenario-cell bull">
    <div class="s-label">Bullish</div>
    <div class="s-value">{bull_pct}%</div>
  </div>
  <div class="scenario-cell base">
    <div class="s-label">Base Case</div>
    <div class="s-value">{base_pct}%</div>
  </div>
  <div class="scenario-cell bear">
    <div class="s-label">Bearish</div>
    <div class="s-value">{bear_pct}%</div>
  </div>
</div>

<!-- ── Narrative Report ─────────────────────────────────────────────────────── -->
<h2>Geopolitical Context</h2>
<div class="narrative-section"><p>{geo_context}</p></div>

<h2>Market Sentiment</h2>
<div class="narrative-section"><p>{market_sentiment}</p></div>

<h2>Asset Analysis</h2>
<div class="narrative-section"><p>{asset_analysis}</p></div>

<h2>Risk Assessment</h2>
<div class="narrative-section"><p>{risk_assessment}</p></div>

<h2>Scenario Outlook</h2>
<div class="narrative-section"><p>{scenario_outlook}</p></div>

<!-- ── Key Risks & Opportunities ───────────────────────────────────────────── -->
<div class="no-break">
<h2>Key Risks &amp; Opportunities</h2>
<ul class="risk-list">
  {risks_html}
  {opportunities_html}
</ul>
</div>

<!-- ── Agent Confidence Table ──────────────────────────────────────────────── -->
<div class="no-break">
<h2>Agent Confidence Scores</h2>
<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Confidence</th>
      <th>Signal</th>
    </tr>
  </thead>
  <tbody>
    {confidence_rows}
  </tbody>
</table>
</div>

<!-- ── Footer ─────────────────────────────────────────────────────────────── -->
<div class="report-footer">
  SentinelAI | Powered by Gemini 2.5 Flash &nbsp;|&nbsp; Critic verdict:
  <strong>{verdict}</strong> &nbsp;|&nbsp; Overall confidence:
  <strong>{overall_confidence_pct}%</strong>
  <div class="disclaimer">
    This report is generated by an AI pipeline for informational purposes only.
    It does not constitute financial advice or a solicitation to buy or sell any asset.
    Past performance is not indicative of future results. Always consult a qualified
    financial professional before making investment decisions.
  </div>
</div>

</body>
</html>
"""


# ── HTML builder ───────────────────────────────────────────────────────────────

def _e(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text))


def _build_html(output: "SynthesisOutput") -> str:
    dp = output.dashboard_payload
    rg = dp.risk_gauge
    sp = dp.scenario_probabilities

    verdict_class = "verdict-pass" if output.verdict == "PASS" else "verdict-fail"

    # Key risks / opportunities list items
    risks_html = "\n  ".join(
        f'<li class="risk-item">⚠ {_e(r)}</li>' for r in output.key_risks
    )
    opportunities_html = "\n  ".join(
        f'<li class="opp-item">✦ {_e(o)}</li>' for o in output.key_opportunities
    )

    # Agent confidence rows
    confidence_rows = ""
    for bar in dp.agent_confidence_chart:
        pct = round(bar.confidence * 100, 1)
        bar_width = round(bar.confidence * 80)
        confidence_rows += (
            f"<tr>"
            f"<td>{_e(bar.agent_label)}</td>"
            f"<td>{pct}%</td>"
            f"<td>"
            f'<div class="pct-bar-wrap">'
            f'<div class="pct-bar" style="width:{bar_width}pt;"></div>'
            f"</div>"
            f"</td>"
            f"</tr>\n"
        )

    ns = output.narrative_sections
    meta = dp.meta

    return _HTML_TEMPLATE.format(
        asset=_e(output.asset),
        query_id=_e(output.query_id),
        timestamp=_e(meta.get("timestamp", output.timestamp)[:19].replace("T", " ")),
        verdict=_e(output.verdict),
        verdict_class=verdict_class,
        executive_summary=_e(output.executive_summary),
        risk_label=_e(rg.label),
        risk_score_pct=round(rg.score * 100, 1),
        geo_stability=round(dp.geopolitical.get("stability_score", 0), 1),
        geo_events=dp.geopolitical.get("key_events_count", 0),
        sentiment_label=_e(dp.sentiment.get("label", "—")),
        fear_greed=round(dp.sentiment.get("fear_greed_index", 0), 1),
        vol_pct=round(dp.quant_risk.get("volatility_30d_pct", 0), 2),
        var_pct=round(dp.quant_risk.get("var_95_pct", 0), 2),
        bull_pct=round(sp.bull * 100, 1),
        base_pct=round(sp.base * 100, 1),
        bear_pct=round(sp.bear * 100, 1),
        geo_context=_e(ns.geopolitical_context),
        market_sentiment=_e(ns.market_sentiment),
        asset_analysis=_e(ns.asset_analysis),
        risk_assessment=_e(ns.risk_assessment),
        scenario_outlook=_e(ns.scenario_outlook),
        risks_html=risks_html or '<li style="color:#718096;">No key risks identified.</li>',
        opportunities_html=opportunities_html,
        confidence_rows=confidence_rows,
        overall_confidence_pct=round(dp.meta.get("overall_confidence", 0) * 100, 1),
    )


# ── Public entry point ─────────────────────────────────────────────────────────

def render_pdf(output: "SynthesisOutput") -> bytes | None:
    """
    Render the SynthesisOutput as a PDF document using WeasyPrint.

    Returns:
        bytes  — raw PDF bytes ready for HTTP response or file storage.
        None   — if WeasyPrint is not installed (graceful degradation).
    """
    if not _WEASYPRINT_AVAILABLE:
        logger.warning(
            "pdf_renderer: WeasyPrint not installed — skipping PDF generation. "
            "Install with: pip install weasyprint"
        )
        return None

    try:
        html_str = _build_html(output)
        return _WeasyHTML(string=html_str).write_pdf()
    except Exception as exc:
        logger.warning("pdf_renderer: PDF generation failed: %s", exc)
        return None
