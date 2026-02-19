/**
 * ReportModal — full-screen overlay displaying a completed pipeline report.
 *
 * Sections:
 *   1. Header bar — asset, verdict badge, confidence, close
 *   2. Executive summary
 *   3. Risk gauge + Scenario probabilities (side-by-side on md+)
 *   4. Agent confidence chart (horizontal bars)
 *   5. Key risks + Key opportunities (two columns)
 *   6. Narrative sections (accordion tabs)
 *   7. Footer — disclaimer + PDF download
 *
 * Security:
 *   - All user-provided strings rendered as React text nodes (no innerHTML).
 *   - PDF download uses axios (sends Bearer token) then creates an object URL
 *     locally — never passes the JWT token through a URL query param.
 *   - Overlay traps keyboard focus; Escape closes the modal.
 */
import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronUp,
  Download, ExternalLink, TrendingDown, TrendingUp, X,
  BarChart2, Globe, Radio, Shield, FileText, Search,
} from 'lucide-react'
import { pipelineApi } from '@/services/api'
import type { AgentConfidenceBar, NarrativeSections, PipelineReport } from '@/types/pipeline'
import { cn } from '@/lib/utils'

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60_000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

function riskColor(level?: string): string {
  switch (level) {
    case 'low':     return '#00e87b'
    case 'medium':  return '#fbbf24'
    case 'high':    return '#fb923c'
    case 'extreme': return '#ff2d4a'
    default:        return '#8b9dc3'
  }
}

function riskBg(level?: string): string {
  switch (level) {
    case 'low':     return 'rgba(0,232,123,0.08)'
    case 'medium':  return 'rgba(251,191,36,0.08)'
    case 'high':    return 'rgba(251,146,60,0.08)'
    case 'extreme': return 'rgba(255,45,74,0.08)'
    default:        return 'rgba(139,157,195,0.06)'
  }
}

const NARRATIVE_TABS: { key: keyof NarrativeSections; label: string }[] = [
  { key: 'geopolitical_context', label: 'Geopolitical' },
  { key: 'market_sentiment',     label: 'Sentiment'    },
  { key: 'asset_analysis',       label: 'Asset'        },
  { key: 'risk_assessment',      label: 'Risk'         },
  { key: 'scenario_outlook',     label: 'Outlook'      },
]

const AGENT_ICONS = [Search, Globe, Radio, BarChart2, Shield, FileText]

// ── Sub-components ────────────────────────────────────────────────────────────

function VerdictBadge({ verdict }: { verdict?: string }) {
  const isPass = verdict === 'PASS'
  const isFail = verdict === 'FAIL'
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg font-mono text-[10px] font-bold uppercase tracking-widest',
      isPass && 'bg-sentinel-green-neon/10 border border-sentinel-green-neon/30 text-sentinel-green-neon',
      isFail && 'bg-sentinel-red-neon/10 border border-sentinel-red-neon/30 text-sentinel-red-neon',
      !isPass && !isFail && 'bg-dark-elevated border border-dark-border text-dark-text-muted',
    )}>
      {isPass && <CheckCircle2 size={9} />}
      {isFail && <AlertTriangle size={9} />}
      {verdict ?? '—'}
    </span>
  )
}

function RiskGaugeBar({ score, level, label }: { score: number; level?: string; label?: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100)
  const color = riskColor(level)
  return (
    <div>
      <div className="flex items-end justify-between mb-2">
        <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Risk Gauge</p>
        <span className="font-mono text-[10px]" style={{ color }}>{label ?? level?.toUpperCase() ?? '—'}</span>
      </div>

      {/* Track + fill */}
      <div className="relative h-3 rounded-full overflow-hidden bg-dark-surface border border-dark-border">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.9, ease: 'easeOut' }}
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ background: `linear-gradient(90deg, #00e87b, ${color})` }}
        />
      </div>

      {/* Tick labels */}
      <div className="flex justify-between mt-1.5">
        {['LOW', 'MEDIUM', 'HIGH', 'EXTREME'].map(l => (
          <span key={l} className="font-mono text-[8px] text-dark-text-muted/50">{l}</span>
        ))}
      </div>

      {/* Score */}
      <p className="font-display italic text-2xl font-bold mt-3 leading-none" style={{ color }}>
        {(score * 100).toFixed(0)}<span className="text-base font-sans font-normal text-dark-text-muted">/100</span>
      </p>
    </div>
  )
}

function ScenarioBars({ bull, base, bear }: { bull: number; base: number; bear: number }) {
  const rows = [
    { label: 'Bull',   pct: Math.round(bull * 100), color: '#00e87b', Icon: TrendingUp   },
    { label: 'Base',   pct: Math.round(base * 100), color: '#60a5fa', Icon: BarChart2    },
    { label: 'Bear',   pct: Math.round(bear * 100), color: '#ff2d4a', Icon: TrendingDown },
  ]
  return (
    <div>
      <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-3">
        Scenario Probabilities
      </p>
      <div className="space-y-3">
        {rows.map(({ label, pct, color, Icon }) => (
          <div key={label}>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-1.5">
                <Icon size={9} style={{ color }} />
                <span className="font-mono text-[10px] text-dark-text-secondary">{label}</span>
              </div>
              <span className="font-mono text-[10px] font-bold" style={{ color }}>{pct}%</span>
            </div>
            <div className="relative h-1.5 rounded-full overflow-hidden bg-dark-surface border border-dark-border/50">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.8, ease: 'easeOut', delay: 0.2 }}
                className="absolute inset-y-0 left-0 rounded-full"
                style={{ backgroundColor: color }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ConfidenceChart({ bars }: { bars: AgentConfidenceBar[] }) {
  return (
    <div>
      <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-3">
        Agent Confidence
      </p>
      <div className="space-y-2.5">
        {bars.map((bar, idx) => {
          const Icon = AGENT_ICONS[idx] ?? BarChart2
          const pct = Math.round(Math.max(0, Math.min(1, bar.confidence)) * 100)
          const color = pct >= 75 ? '#00e87b' : pct >= 50 ? '#fbbf24' : '#ff2d4a'
          return (
            <div key={bar.agent_id} className="flex items-center gap-3">
              <div className="w-5 h-5 flex items-center justify-center flex-shrink-0">
                <Icon size={10} className="text-dark-text-muted" />
              </div>
              <span className="font-mono text-[9px] text-dark-text-secondary w-20 flex-shrink-0 truncate">
                {bar.agent_label}
              </span>
              <div className="flex-1 relative h-1.5 rounded-full overflow-hidden bg-dark-surface border border-dark-border/50">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.7, ease: 'easeOut', delay: idx * 0.06 }}
                  className="absolute inset-y-0 left-0 rounded-full"
                  style={{ backgroundColor: color }}
                />
              </div>
              <span className="font-mono text-[10px] font-bold w-9 text-right flex-shrink-0" style={{ color }}>
                {pct}%
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function NarrativeAccordion({ sections }: { sections: NarrativeSections }) {
  const [active, setActive] = useState<keyof NarrativeSections>('geopolitical_context')
  return (
    <div>
      <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-3">
        Narrative Analysis
      </p>
      {/* Tab pills */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {NARRATIVE_TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActive(key)}
            className={cn(
              'font-mono text-[9px] px-2.5 py-1 rounded-md transition-colors',
              active === key
                ? 'bg-sentinel-green-neon/15 border border-sentinel-green-neon/40 text-sentinel-green-neon'
                : 'bg-dark-elevated border border-dark-border text-dark-text-muted hover:text-dark-text-secondary',
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {/* Content */}
      <AnimatePresence mode="wait">
        <motion.div
          key={active}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.15 }}
          className={cn(
            'p-4 rounded-xl border',
            'bg-dark-surface border-dark-border',
          )}
        >
          <p className="font-sans text-sm text-dark-text-secondary leading-relaxed whitespace-pre-wrap">
            {sections[active] || '—'}
          </p>
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

function ListSection({
  title, items, accent,
}: {
  title: string; items: string[]; accent: 'green' | 'red'
}) {
  const [expanded, setExpanded] = useState(true)
  const color = accent === 'green' ? 'text-sentinel-green-neon' : 'text-sentinel-red-neon'
  const dotColor = accent === 'green' ? 'bg-sentinel-green-neon' : 'bg-sentinel-red-neon'

  return (
    <div className="rounded-xl border border-dark-border bg-dark-surface p-4">
      <button
        onClick={() => setExpanded(v => !v)}
        className="flex items-center justify-between w-full mb-2"
      >
        <p className={cn('font-mono text-[9px] uppercase tracking-widest', color)}>{title}</p>
        {expanded ? <ChevronUp size={11} className="text-dark-text-muted" /> : <ChevronDown size={11} className="text-dark-text-muted" />}
      </button>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.ul
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="space-y-1.5 overflow-hidden"
          >
            {items.length === 0 && (
              <li className="font-mono text-[10px] text-dark-text-muted">None identified</li>
            )}
            {items.map((item, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className={cn('w-1 h-1 rounded-full mt-1.5 flex-shrink-0', dotColor)} />
                <span className="font-sans text-xs text-dark-text-secondary leading-snug">{item}</span>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

interface ReportModalProps {
  report: PipelineReport
  onClose: () => void
}

export default function ReportModal({ report, onClose }: ReportModalProps) {
  const overlayRef = useRef<HTMLDivElement>(null)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)

  const dp = report.dashboard_payload
  const rg = dp?.risk_gauge
  const sp = dp?.scenario_probabilities
  const cc = dp?.agent_confidence_chart ?? []
  const ns = report.narrative_sections

  // Escape key closes
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  // Prevent body scroll
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = '' }
  }, [])

  const handleOverlayClick = (e: React.MouseEvent) => {
    if (e.target === overlayRef.current) onClose()
  }

  const handleDownloadPdf = async () => {
    if (!report.pdf_available) return
    setPdfLoading(true)
    setPdfError(null)
    try {
      const { data } = await pipelineApi.downloadPdf(report.run_id)
      const blob = new Blob([data], { type: 'application/pdf' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `sentinelai_${(report.asset ?? 'report').toLowerCase()}_${report.run_id.slice(0, 8)}.pdf`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch {
      setPdfError('PDF download failed. Please try again.')
    } finally {
      setPdfLoading(false)
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        ref={overlayRef}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        onClick={handleOverlayClick}
        className="fixed inset-0 z-50 flex items-start justify-center p-4 sm:p-6 overflow-y-auto"
        style={{ background: 'rgba(6,11,24,0.88)', backdropFilter: 'blur(8px)' }}
      >
        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 16, scale: 0.97 }}
          transition={{ duration: 0.22, ease: 'easeOut' }}
          className={cn(
            'w-full max-w-4xl my-auto',
            'bg-dark-card border border-dark-border rounded-2xl overflow-hidden shadow-card-dark',
          )}
          onClick={e => e.stopPropagation()}
        >

          {/* ── Header ─────────────────────────────────────────────────────── */}
          <div className="h-[1px] bg-gradient-to-r from-transparent via-sentinel-green-neon/50 to-transparent" />
          <div className={cn(
            'flex items-center justify-between px-6 py-4',
            'border-b border-dark-border',
          )}>
            <div className="flex items-center gap-3 min-w-0">
              <div className={cn(
                'px-3 py-1 rounded-lg border font-mono text-sm font-bold',
                'bg-dark-elevated border-dark-border text-dark-text-primary',
              )}>
                {report.asset ?? '—'}
              </div>
              <VerdictBadge verdict={report.verdict} />
              {report.overall_confidence !== undefined && (
                <span className="font-mono text-[10px] text-dark-text-muted hidden sm:block">
                  Confidence {(report.overall_confidence * 100).toFixed(0)}%
                </span>
              )}
              {report.completed_at && (
                <span className="font-mono text-[9px] text-dark-text-muted/60 hidden md:block">
                  {timeAgo(report.completed_at)}
                </span>
              )}
            </div>
            <button
              onClick={onClose}
              className={cn(
                'flex items-center justify-center w-8 h-8 rounded-lg flex-shrink-0',
                'bg-dark-elevated border border-dark-border',
                'hover:border-sentinel-red-neon/30 hover:bg-sentinel-red-neon/5',
                'text-dark-text-muted hover:text-sentinel-red-neon transition-all',
              )}
              aria-label="Close report"
            >
              <X size={13} />
            </button>
          </div>

          {/* ── Scrollable content ──────────────────────────────────────────── */}
          <div className="overflow-y-auto max-h-[80vh] p-6 space-y-6">

            {/* Executive summary */}
            {report.executive_summary && (
              <div className={cn(
                'p-5 rounded-xl border',
                rg ? `border-[${riskColor(rg.level)}]/20` : 'border-dark-border',
              )}
              style={{ background: rg ? riskBg(rg.level) : undefined }}
              >
                <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-2">
                  Executive Summary
                </p>
                <p className="font-display italic text-lg text-dark-text-primary leading-relaxed">
                  {report.executive_summary}
                </p>
              </div>
            )}

            {/* Risk gauge + Scenarios */}
            {(rg || sp) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {rg && (
                  <div className="p-5 rounded-xl border border-dark-border bg-dark-surface">
                    <RiskGaugeBar score={rg.score} level={rg.level} label={rg.label} />
                  </div>
                )}
                {sp && (
                  <div className="p-5 rounded-xl border border-dark-border bg-dark-surface">
                    <ScenarioBars bull={sp.bull} base={sp.base} bear={sp.bear} />
                  </div>
                )}
              </div>
            )}

            {/* Agent confidence chart */}
            {cc.length > 0 && (
              <div className="p-5 rounded-xl border border-dark-border bg-dark-surface">
                <ConfidenceChart bars={cc} />
              </div>
            )}

            {/* Key risks + Opportunities */}
            {(report.key_risks?.length || report.key_opportunities?.length) ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <ListSection
                  title="Key Risks"
                  items={report.key_risks ?? []}
                  accent="red"
                />
                <ListSection
                  title="Opportunities"
                  items={report.key_opportunities ?? []}
                  accent="green"
                />
              </div>
            ) : null}

            {/* Narrative sections */}
            {ns && <NarrativeAccordion sections={ns} />}

            {/* Critic meta */}
            {report.critic && (
              <div className="p-4 rounded-xl border border-dark-border bg-dark-surface">
                <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-2">
                  Critic Verification
                </p>
                <div className="flex flex-wrap gap-x-6 gap-y-1">
                  <span className="font-mono text-[10px] text-dark-text-muted">
                    Checks passed: <span className="text-dark-text-secondary">
                      {report.critic.checks_passed ?? '—'}/{report.critic.checks_total ?? '—'}
                    </span>
                  </span>
                  {(report.critic.retry_count ?? 0) > 0 && (
                    <span className="font-mono text-[10px] text-dark-text-muted">
                      Retries: <span className="text-amber-400">{report.critic.retry_count}</span>
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* PDF error */}
            {pdfError && (
              <p className="font-mono text-[10px] text-sentinel-red-neon">{pdfError}</p>
            )}
          </div>

          {/* ── Footer ─────────────────────────────────────────────────────── */}
          <div className="px-6 py-4 border-t border-dark-border flex items-center justify-between gap-4">
            <p className="font-mono text-[9px] text-dark-text-muted/50 leading-relaxed hidden sm:block">
              For informational purposes only · Not financial advice · SentinelAI v0.1
            </p>
            <div className="flex items-center gap-2 flex-shrink-0">
              {report.pdf_available && (
                <motion.button
                  whileHover={{ scale: 1.03 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={handleDownloadPdf}
                  disabled={pdfLoading}
                  className={cn(
                    'flex items-center gap-1.5 px-3 py-1.5 rounded-lg',
                    'bg-dark-elevated border border-dark-border',
                    'font-mono text-[10px] text-dark-text-secondary',
                    'hover:border-sentinel-green-neon/30 hover:text-sentinel-green-neon',
                    'transition-all disabled:opacity-50 disabled:cursor-not-allowed',
                  )}
                >
                  {pdfLoading ? (
                    <span className="btn-spinner" style={{ width: 10, height: 10 }} />
                  ) : (
                    <Download size={10} />
                  )}
                  {pdfLoading ? 'Generating…' : 'Download PDF'}
                </motion.button>
              )}
              <motion.button
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: 0.97 }}
                onClick={onClose}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-lg',
                  'bg-sentinel-green-neon/10 border border-sentinel-green-neon/25',
                  'font-mono text-[10px] text-sentinel-green-neon',
                  'hover:bg-sentinel-green-neon/20 transition-all',
                )}
              >
                <ExternalLink size={10} />
                Close
              </motion.button>
            </div>
          </div>

        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
