/**
 * Pipeline API types — mirrors backend app/models/pipeline.py schemas.
 *
 * Security notes:
 *  - raw_query max 500 chars — validated by usePipeline hook before submission.
 *  - asset_hint matches ^[A-Z0-9^=.-]{1,12}$ — validated client-side + backend.
 *  - No user_id exposed in UserRunItem (server strips it).
 */

// ── Requests ──────────────────────────────────────────────────────────────────

export interface QueryRequest {
  raw_query: string
  asset_hint?: string
  timeframe_hint?: string
  risk_focus_hint?: string
}

// ── Responses: submission + status ───────────────────────────────────────────

export interface QueryResponse {
  run_id: string
  status: 'pending'
  message: string
  created_at: string
}

export type RunStatus = 'pending' | 'running' | 'done' | 'failed'

export interface PipelineStatus {
  run_id: string
  status: RunStatus
  asset?: string
  timeframe?: string
  risk_focus?: string
  created_at: string
  updated_at: string
  completed_at?: string
  error_message?: string
}

export interface UserRunItem {
  run_id: string
  raw_query: string
  asset?: string
  timeframe?: string
  risk_focus?: string
  status: RunStatus
  created_at: string
  updated_at: string
  completed_at?: string
  error_message?: string
}

// ── Report / dashboard payload ────────────────────────────────────────────────

export interface RiskGauge {
  score: number        // 0.0–1.0
  level: 'low' | 'medium' | 'high' | 'extreme'
  label: string
}

export interface ScenarioProbabilities {
  bull: number   // 0–1, sums to 1.0 with base + bear
  base: number
  bear: number
}

export interface AgentConfidenceBar {
  agent_id: string
  agent_label: string
  confidence: number   // 0–1
}

export interface DashboardPayload {
  meta: Record<string, unknown>
  risk_gauge: RiskGauge
  scenario_probabilities: ScenarioProbabilities
  agent_confidence_chart: AgentConfidenceBar[]
  key_risks: string[]
  key_opportunities: string[]
  geopolitical: Record<string, unknown>
  sentiment: Record<string, unknown>
  asset: Record<string, unknown>
  quant_risk: Record<string, unknown>
  critic: Record<string, unknown>
}

export interface NarrativeSections {
  geopolitical_context: string
  market_sentiment: string
  asset_analysis: string
  risk_assessment: string
  scenario_outlook: string
}

export interface CriticMeta {
  verdict?: string
  overall_confidence?: number
  checks_passed?: number
  checks_total?: number
  retry_count?: number
}

// ── Chart data ────────────────────────────────────────────────────────────────

export interface ChartPrice {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface ChartForecast {
  horizon_days: number
  current_price: number
  p10: number
  median: number
  p90: number
  directional_bias: string
  uncertainty_score: number
  forecast_date: string
  run_completed_at: string
}

export interface ChartData {
  ticker: string
  days: number
  prices: ChartPrice[]
  forecast: ChartForecast | null
}

export interface PipelineReport {
  run_id: string
  asset?: string
  status: string
  executive_summary?: string
  verdict?: string
  overall_confidence?: number
  dashboard_payload?: DashboardPayload
  narrative_sections?: NarrativeSections
  key_risks?: string[]
  key_opportunities?: string[]
  reasoning_trace?: string
  critic?: CriticMeta
  created_at: string
  completed_at?: string
  pdf_available: boolean
}
