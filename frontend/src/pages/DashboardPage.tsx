import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Activity, AlertTriangle, BarChart2, CheckCircle2, ChevronDown,
  ChevronRight, Clock, Database, FileText, Globe, LineChart,
  Loader2, LogOut, Radar, Radio, Search, Settings, Shield,
  TrendingUp, Zap,
} from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { usePipeline, type PipelinePhase } from '@/hooks/usePipeline'
import { AVATAR_MAP } from '@/components/profile/ProfileInfoTab'
import ReportModal from '@/components/dashboard/ReportModal'
import AssetChart from '@/components/dashboard/AssetChart'
import Logo from '@/components/ui/Logo'
import { pipelineApi } from '@/services/api'
import { cn } from '@/lib/utils'
import type { ChartData, UserRunItem } from '@/types/pipeline'

// ── Asset catalogue ────────────────────────────────────────────────────────────
const ASSET_CATEGORIES = [
  {
    id: 'crypto', label: 'Crypto', color: '#f59e0b',
    assets: [
      { ticker: 'BTC-USD', name: 'Bitcoin' },
      { ticker: 'ETH-USD', name: 'Ethereum' },
      { ticker: 'SOL-USD', name: 'Solana' },
      { ticker: 'BNB-USD', name: 'BNB' },
      { ticker: 'XRP-USD', name: 'XRP' },
      { ticker: 'ADA-USD', name: 'Cardano' },
      { ticker: 'AVAX-USD', name: 'Avalanche' },
      { ticker: 'DOGE-USD', name: 'Dogecoin' },
      { ticker: 'DOT-USD', name: 'Polkadot' },
      { ticker: 'LINK-USD', name: 'Chainlink' },
      { ticker: 'MATIC-USD', name: 'Polygon' },
      { ticker: 'UNI-USD', name: 'Uniswap' },
    ],
  },
  {
    id: 'equities', label: 'Equities', color: '#60a5fa',
    assets: [
      { ticker: 'AAPL', name: 'Apple' },
      { ticker: 'NVDA', name: 'NVIDIA' },
      { ticker: 'MSFT', name: 'Microsoft' },
      { ticker: 'TSLA', name: 'Tesla' },
      { ticker: 'GOOGL', name: 'Alphabet' },
      { ticker: 'META', name: 'Meta' },
      { ticker: 'AMZN', name: 'Amazon' },
      { ticker: 'NFLX', name: 'Netflix' },
      { ticker: 'AMD', name: 'AMD' },
      { ticker: 'JPM', name: 'JPMorgan' },
      { ticker: 'GS', name: 'Goldman Sachs' },
      { ticker: 'V', name: 'Visa' },
    ],
  },
  {
    id: 'indices', label: 'Indices', color: '#c084fc',
    assets: [
      { ticker: 'SPY', name: 'S&P 500 ETF' },
      { ticker: 'QQQ', name: 'Nasdaq 100' },
      { ticker: 'IWM', name: 'Russell 2000' },
      { ticker: 'DIA', name: 'Dow Jones ETF' },
      { ticker: '^VIX', name: 'VIX Volatility' },
      { ticker: 'TLT', name: '20Y US Bonds' },
      { ticker: 'GLD', name: 'Gold ETF' },
      { ticker: 'EFA', name: 'EAFE ETF' },
    ],
  },
  {
    id: 'commodities', label: 'Commodities', color: '#fb923c',
    assets: [
      { ticker: 'GC=F', name: 'Gold' },
      { ticker: 'SI=F', name: 'Silver' },
      { ticker: 'CL=F', name: 'Crude Oil' },
      { ticker: 'NG=F', name: 'Natural Gas' },
      { ticker: 'HG=F', name: 'Copper' },
      { ticker: 'PL=F', name: 'Platinum' },
    ],
  },
  {
    id: 'fx', label: 'FX', color: '#34d399',
    assets: [
      { ticker: 'DX-Y.NYB', name: 'USD Index' },
      { ticker: 'EUR=X',    name: 'EUR / USD' },
      { ticker: 'JPY=X',    name: 'USD / JPY' },
      { ticker: 'GBP=X',    name: 'GBP / USD' },
      { ticker: 'CHF=X',    name: 'USD / CHF' },
      { ticker: 'AUD=X',    name: 'AUD / USD' },
    ],
  },
] as const

type CategoryId = typeof ASSET_CATEGORIES[number]['id']

// ── Agent pipeline nodes ───────────────────────────────────────────────────────
const AGENTS = [
  { id: 1, label: 'Intake',      sub: 'Routing',    Icon: Search,     bg: 'bg-sentinel-green-neon/10', ring: 'ring-sentinel-green-neon/30', color: '#00e87b' },
  { id: 2, label: 'Geo & Macro', sub: 'Analysis',   Icon: Globe,      bg: 'bg-blue-500/10',            ring: 'ring-blue-400/30',            color: '#60a5fa' },
  { id: 3, label: 'Sentiment',   sub: 'Engine',     Icon: Radio,      bg: 'bg-purple-500/10',          ring: 'ring-purple-400/30',          color: '#c084fc' },
  { id: 4, label: 'Asset',       sub: 'Forecaster', Icon: TrendingUp, bg: 'bg-amber-500/10',           ring: 'ring-amber-400/30',           color: '#fbbf24' },
  { id: 5, label: 'Critic',      sub: 'Verifier',   Icon: Shield,     bg: 'bg-orange-500/10',          ring: 'ring-orange-400/30',          color: '#fb923c' },
  { id: 6, label: 'Synthesis',   sub: 'Reporter',   Icon: FileText,   bg: 'bg-sentinel-green-neon/10', ring: 'ring-sentinel-green-neon/30', color: '#00e87b' },
] as const

const AGENT_CUTOFFS_MS = [0, 2_000, 15_000, 30_000, 60_000, 75_000, Infinity]

type AgentNodeStatus = 'idle' | 'pending' | 'active' | 'done' | 'error'

function getAgentNodeStatus(agentIdx: number, phase: PipelinePhase, elapsedMs: number): AgentNodeStatus {
  if (phase === 'idle') return 'idle'
  if (phase === 'done') return 'done'
  if (phase === 'error') return 'error'
  if (phase === 'submitting') return agentIdx === 0 ? 'active' : 'pending'
  const start = AGENT_CUTOFFS_MS[agentIdx]
  const end   = AGENT_CUTOFFS_MS[agentIdx + 1]
  if (elapsedMs < start) return 'pending'
  if (elapsedMs < end)   return 'active'
  return 'done'
}

// ── Live feeds ─────────────────────────────────────────────────────────────────
const FEEDS = [
  { name: 'GDELT Project', detail: '100+ languages · live events' },
  { name: 'FRED API',      detail: '840K economic time series'    },
  { name: 'yfinance',      detail: 'Real-time asset prices'       },
] as const

// ── Helpers ────────────────────────────────────────────────────────────────────
function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60_000)
  if (m < 1)  return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  return `${Math.floor(h / 24)}d ago`
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function LiveClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  const p = (n: number) => n.toString().padStart(2, '0')
  return (
    <span className="font-mono text-[10px] tabular-nums tracking-widest text-dark-text-muted hidden sm:block select-none">
      {p(now.getUTCHours())}:{p(now.getUTCMinutes())}:{p(now.getUTCSeconds())} <span className="opacity-40">UTC</span>
    </span>
  )
}

type AuthUser = NonNullable<ReturnType<typeof useAuth>['user']>

function ProfileWidget({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const src      = user.avatar_id ? AVATAR_MAP[user.avatar_id] : null
  const firstName = user.fullname.split(' ')[0]
  const initials  = user.fullname.split(' ').map((w: string) => w[0]).slice(0, 2).join('').toUpperCase()

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className={cn(
          'flex items-center gap-2.5 pl-2 pr-3 py-1.5 rounded-xl',
          'bg-dark-card border border-dark-border',
          'hover:border-sentinel-green-neon/30 hover:bg-dark-elevated transition-all duration-200',
        )}
      >
        <div className="w-7 h-7 rounded-lg overflow-hidden flex-shrink-0 ring-1 ring-sentinel-green-neon/25">
          {src ? (
            <img src={src} alt="" className="w-full h-full object-cover object-top" draggable={false} />
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-sentinel-green-neon/20 to-sentinel-green-neon/5">
              <span className="font-mono text-[9px] font-bold text-sentinel-green-neon">{initials}</span>
            </div>
          )}
        </div>
        <span className="font-mono text-xs text-dark-text-secondary hidden sm:block">{firstName}</span>
        <ChevronDown size={11} className={cn('text-dark-text-muted transition-transform duration-200', open && 'rotate-180')} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 4, scale: 0.97 }}
            transition={{ duration: 0.13 }}
            className="absolute right-0 top-full mt-2 w-52 z-50 bg-dark-card border border-dark-border rounded-xl overflow-hidden shadow-card-dark"
          >
            <div className="px-4 py-3 border-b border-dark-border">
              <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Signed in as</p>
              <p className="font-mono text-xs text-dark-text-primary mt-0.5 truncate">{user.fullname}</p>
              <p className="font-mono text-[10px] text-dark-text-muted truncate">{user.email}</p>
            </div>
            <button
              onClick={() => { setOpen(false); navigate('/profile') }}
              className="w-full flex items-center gap-2.5 px-4 py-2.5 hover:bg-dark-elevated transition-colors"
            >
              <Settings size={12} className="text-dark-text-muted" />
              <span className="font-mono text-xs text-dark-text-secondary">Profile Settings</span>
            </button>
            <div className="h-px bg-dark-border" />
            <button
              onClick={() => { setOpen(false); onLogout() }}
              className="w-full flex items-center gap-2.5 px-4 py-2.5 hover:bg-sentinel-red-neon/5 transition-colors group"
            >
              <LogOut size={12} className="text-dark-text-muted group-hover:text-sentinel-red-neon transition-colors" />
              <span className="font-mono text-xs text-dark-text-secondary group-hover:text-sentinel-red-neon transition-colors">Sign Out</span>
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function StatCard({
  label, value, sub, icon: Icon, delay = 0, accent = false,
}: { label: string; value: string | number; sub: string; icon: React.ElementType; delay?: number; accent?: boolean }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 18 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay, ease: 'easeOut' }}
      className={cn(
        'relative rounded-xl overflow-hidden bg-dark-card border',
        accent ? 'border-sentinel-green-neon/20' : 'border-dark-border',
      )}
    >
      <div className={cn('h-[1px] bg-gradient-to-r from-transparent to-transparent', accent ? 'via-sentinel-green-neon/50' : 'via-dark-border/50')} />
      {accent && <div className="absolute top-0 right-0 w-24 h-24 bg-sentinel-green-neon/5 blur-2xl pointer-events-none rounded-full" />}
      <div className="px-5 py-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-2">{label}</p>
          <p className={cn('font-display italic text-2xl font-bold leading-none', accent ? 'text-sentinel-green-neon' : 'text-dark-text-primary')}>{value}</p>
          <p className="font-mono text-[10px] text-dark-text-muted mt-1.5 truncate">{sub}</p>
        </div>
        <div className={cn('flex-shrink-0 p-2.5 rounded-xl mt-0.5', accent ? 'bg-sentinel-green-neon/10 border border-sentinel-green-neon/20' : 'bg-dark-elevated border border-dark-border')}>
          <Icon size={14} className={accent ? 'text-sentinel-green-neon' : 'text-dark-text-muted'} />
        </div>
      </div>
    </motion.div>
  )
}

function HistoryRow({ run, onView }: { run: UserRunItem; onView: (id: string, status: UserRunItem['status']) => void }) {
  const isDone    = run.status === 'done'
  const isFailed  = run.status === 'failed'
  const isRunning = run.status === 'running' || run.status === 'pending'

  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-dark-border/60 last:border-0">
      <span className={cn(
        'w-1.5 h-1.5 rounded-full flex-shrink-0',
        isDone && 'bg-sentinel-green-neon', isFailed && 'bg-sentinel-red-neon', isRunning && 'bg-amber-400 animate-pulse-dot',
      )} />
      <div className="flex-1 min-w-0">
        <p className="font-mono text-[10px] text-dark-text-primary truncate">
          {run.asset && <span className="text-sentinel-green-neon font-bold">{run.asset} · </span>}
          <span className="text-dark-text-secondary">{run.raw_query.slice(0, 45)}{run.raw_query.length > 45 ? '…' : ''}</span>
        </p>
        <p className="font-mono text-[9px] text-dark-text-muted mt-0.5">{timeAgo(run.created_at)} · {run.status}</p>
      </div>
      {isDone && (
        <button
          onClick={() => onView(run.run_id, run.status)}
          className="flex-shrink-0 px-2 py-1 rounded-md bg-dark-elevated border border-dark-border font-mono text-[9px] text-dark-text-muted hover:border-sentinel-green-neon/30 hover:text-sentinel-green-neon transition-all"
        >View</button>
      )}
      {isFailed  && <AlertTriangle size={11} className="text-sentinel-red-neon/60 flex-shrink-0" />}
      {isRunning && <Loader2 size={11} className="text-amber-400 animate-spin flex-shrink-0" />}
    </div>
  )
}

// ── Asset card ─────────────────────────────────────────────────────────────────
function AssetCard({
  ticker, name, catColor, selected, running,
  onClick,
}: {
  ticker: string; name: string; catColor: string
  selected: boolean; running: boolean
  onClick: () => void
}) {
  return (
    <motion.button
      onClick={onClick}
      disabled={running}
      whileHover={running ? {} : { scale: 1.03 }}
      whileTap={running ? {} : { scale: 0.97 }}
      className={cn(
        'relative flex flex-col items-start gap-1 px-3 py-2.5 rounded-xl border text-left',
        'transition-all duration-200 overflow-hidden',
        selected
          ? 'bg-sentinel-green-neon/10 border-sentinel-green-neon/40 shadow-glow-green-sm'
          : 'bg-dark-elevated border-dark-border hover:border-dark-text-muted/20',
        running && 'opacity-50 cursor-not-allowed',
      )}
    >
      {/* Category accent bar */}
      <div
        className="absolute top-0 left-0 w-[3px] h-full rounded-l-xl"
        style={{ backgroundColor: catColor, opacity: selected ? 1 : 0.35 }}
      />
      <span className={cn(
        'font-mono text-[10px] font-bold truncate max-w-full',
        selected ? 'text-sentinel-green-neon' : 'text-dark-text-primary',
      )}>
        {ticker}
      </span>
      <span className="font-mono text-[8px] text-dark-text-muted truncate max-w-full leading-none">{name}</span>
      {selected && (
        <motion.div
          layoutId="asset-active-dot"
          className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full bg-sentinel-green-neon"
        />
      )}
    </motion.button>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const { isAuthenticated, isLoading, logout, user } = useAuth()
  const navigate = useNavigate()
  const [reportOpen, setReportOpen] = useState(false)
  const [activeCategory, setActiveCategory] = useState<CategoryId>('crypto')
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)
  const [chartData, setChartData] = useState<ChartData | null>(null)
  const [chartLoading, setChartLoading] = useState(false)
  const [chartError, setChartError] = useState<string | null>(null)

  const { phase, report, error, elapsedMs, history, historyLoading, submit, viewReport, dismiss } = usePipeline()

  useEffect(() => {
    if (!isLoading && !isAuthenticated) navigate('/login', { replace: true })
  }, [isAuthenticated, isLoading, navigate])

  useEffect(() => {
    if (phase === 'done' && report) setReportOpen(true)
  }, [phase, report])

  // ── Load chart data whenever selectedTicker changes ────────────────────────
  useEffect(() => {
    if (!selectedTicker) return
    let cancelled = false
    setChartLoading(true)
    setChartError(null)
    setChartData(null)
    pipelineApi.getChartData(selectedTicker)
      .then(res => { if (!cancelled) setChartData(res.data) })
      .catch(() => { if (!cancelled) setChartError('Price data unavailable') })
      .finally(() => { if (!cancelled) setChartLoading(false) })
    return () => { cancelled = true }
  }, [selectedTicker])

  const isActive = phase === 'submitting' || phase === 'polling' || phase === 'loading_report'

  const handleSelectAsset = useCallback((ticker: string) => {
    if (isActive) return
    setSelectedTicker(ticker)
    submit(ticker)          // buildQuery auto-expands ticker → full query + asset_hint
  }, [isActive, submit])

  const handleWatchlistClick = useCallback((ticker: string) => {
    if (isActive) return
    setSelectedTicker(ticker)
    submit(ticker)
  }, [isActive, submit])

  const handleLogout = () => logout().then(() => navigate('/login', { replace: true }))

  if (isLoading) {
    return (
      <div className="min-h-dvh bg-dark-bg flex items-center justify-center">
        <div className="btn-spinner" style={{ width: 24, height: 24 }} />
      </div>
    )
  }
  if (!isAuthenticated || !user) return null

  const hour      = new Date().getHours()
  const greeting  = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  const firstName = user.fullname.split(' ')[0]

  const statusValue = isActive ? 'Running' : phase === 'done' ? 'Done' : phase === 'error' ? 'Failed' : 'Ready'
  const statusSub   = isActive
    ? `${Math.floor(elapsedMs / 1000)}s elapsed`
    : phase === 'error' ? (error?.slice(0, 32) ?? 'See terminal') : history.length > 0
      ? `${history.filter(r => r.status === 'done').length} analyses completed`
      : 'awaiting first analysis'

  const currentCategory = ASSET_CATEGORIES.find(c => c.id === activeCategory)!

  // All tickers user has watchlisted
  const watchlist: string[] = user.ticker_preferences ?? []

  // Find a ticker currently selected from the watchlist (for chart data)
  const activeAssetInfo = useMemo(() => {
    for (const cat of ASSET_CATEGORIES) {
      const found = cat.assets.find(a => a.ticker === selectedTicker)
      if (found) return { ...found, color: cat.color }
    }
    if (selectedTicker) return { ticker: selectedTicker, name: selectedTicker, color: '#00e87b' }
    return null
  }, [selectedTicker])

  return (
    <div className={cn('min-h-dvh flex flex-col', 'bg-dark-bg bg-grid-dark bg-grid-40')}>

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <header className={cn(
        'sticky top-0 z-30 flex items-center justify-between px-5 py-3',
        'bg-dark-bg/80 backdrop-blur-md border-b border-dark-border',
      )}>
        <div className="flex items-center gap-3">
          <Logo size="sm" />
          <span className="text-dark-text-muted/30 select-none hidden md:block">/</span>
          <span className="hidden md:block font-mono text-[10px] uppercase tracking-widest text-dark-text-muted">
            Intelligence Terminal
          </span>
        </div>
        <div className="flex items-center gap-4">
          <LiveClock />
          <div className="hidden sm:flex items-center gap-1.5 border-r border-dark-border pr-4">
            <span className={cn('w-1.5 h-1.5 rounded-full', isActive ? 'bg-amber-400 animate-pulse-dot' : 'bg-sentinel-green-neon animate-pulse-dot')} />
            <span className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">
              {isActive ? 'Pipeline running' : 'All systems online'}
            </span>
          </div>
          <ProfileWidget user={user} onLogout={handleLogout} />
        </div>
      </header>

      {/* ── Body ──────────────────────────────────────────────────────────── */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-6">

        {/* Greeting */}
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="flex flex-col sm:flex-row sm:items-end justify-between gap-4"
        >
          <div>
            <p className="font-mono text-[10px] uppercase tracking-widest text-sentinel-green-neon mb-1">{greeting}</p>
            <h1 className="font-display italic text-4xl text-dark-text-primary leading-none">{firstName}.</h1>
            <p className="font-sans text-sm text-dark-text-secondary mt-2">
              {isActive
                ? 'Multi-agent pipeline is running your analysis…'
                : selectedTicker
                  ? `Select an asset to run a full intelligence report.`
                  : 'Select an asset below to run a full intelligence report.'}
            </p>
          </div>
          {/* Running indicator (replaces the "New Analysis" button) */}
          {isActive && (
            <motion.div
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-400/8 border border-amber-400/20"
            >
              <Loader2 size={12} className="text-amber-400 animate-spin" />
              <span className="font-mono text-xs text-amber-400">
                {selectedTicker && <span className="font-bold">{selectedTicker} · </span>}
                {phase === 'loading_report' ? 'Generating report…' : `Analysing · ${Math.floor(elapsedMs / 1000)}s`}
              </span>
            </motion.div>
          )}
        </motion.div>

        {/* Stat cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          <StatCard label="Tracked Instruments" icon={BarChart2} delay={0} accent
            value={watchlist.length || '—'}
            sub={watchlist.length ? 'in your watchlist' : 'Add tickers in Profile'}
          />
          <StatCard label="Data Sources"   icon={Database}    delay={0.07} value="3"        sub="GDELT · FRED · yfinance" />
          <StatCard label="Agent Pipeline" icon={Zap}          delay={0.14} value="6"        sub="agents orchestrated"     />
          <StatCard label="System Status"  icon={Activity}     delay={0.21} value={statusValue} sub={statusSub} accent={isActive} />
        </div>

        {/* ── Main grid ─────────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

          {/* Left 2/3 */}
          <div className="xl:col-span-2 space-y-5">

            {/* ── Asset selector ──────────────────────────────────────── */}
            <motion.div
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.08 }}
              className={cn(
                'rounded-xl overflow-hidden bg-dark-card border transition-colors duration-300',
                isActive ? 'border-amber-400/30' : phase === 'error' ? 'border-sentinel-red-neon/30' : 'border-dark-border',
              )}
            >
              <div className={cn(
                'h-[1px] bg-gradient-to-r from-transparent to-transparent',
                isActive ? 'via-amber-400/50' : phase === 'error' ? 'via-sentinel-red-neon/50' : 'via-sentinel-green-neon/50',
              )} />

              <div className="px-6 py-5">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Intelligence Query</p>
                    <p className="font-display italic text-lg text-dark-text-primary mt-0.5">Select an Asset</p>
                  </div>
                  {phase === 'error' && error && (
                    <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-sentinel-red-neon/5 border border-sentinel-red-neon/20">
                      <AlertTriangle size={10} className="text-sentinel-red-neon" />
                      <span className="font-mono text-[9px] text-sentinel-red-neon">{error.slice(0, 40)}</span>
                    </div>
                  )}
                </div>

                {/* Category tabs */}
                <div className="flex gap-1 mb-4 flex-wrap">
                  {ASSET_CATEGORIES.map(cat => (
                    <button
                      key={cat.id}
                      onClick={() => setActiveCategory(cat.id)}
                      className={cn(
                        'px-3 py-1 rounded-lg font-mono text-[9px] uppercase tracking-widest transition-all duration-150',
                        activeCategory === cat.id
                          ? 'text-dark-void font-bold'
                          : 'bg-dark-surface border border-dark-border text-dark-text-muted hover:text-dark-text-secondary',
                      )}
                      style={activeCategory === cat.id ? { backgroundColor: cat.color, border: `1px solid ${cat.color}` } : {}}
                    >
                      {cat.label}
                    </button>
                  ))}
                </div>

                {/* Asset grid */}
                <AnimatePresence mode="wait">
                  <motion.div
                    key={activeCategory}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    transition={{ duration: 0.18 }}
                    className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2"
                  >
                    {currentCategory.assets.map(asset => (
                      <AssetCard
                        key={asset.ticker}
                        ticker={asset.ticker}
                        name={asset.name}
                        catColor={currentCategory.color}
                        selected={selectedTicker === asset.ticker}
                        running={isActive}
                        onClick={() => handleSelectAsset(asset.ticker)}
                      />
                    ))}
                  </motion.div>
                </AnimatePresence>

                <p className="font-mono text-[9px] text-dark-text-muted/40 mt-3">
                  Click any asset to immediately launch the 6-agent intelligence pipeline · Results typically take 60–90s
                </p>
              </div>
            </motion.div>

            {/* ── Price Chart ──────────────────────────────────────────── */}
            <motion.div
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.14 }}
              className="rounded-xl overflow-hidden bg-dark-card border border-dark-border"
            >
              <div className="h-[1px] bg-gradient-to-r from-transparent via-sentinel-green-neon/20 to-transparent" />
              <div className="px-6 py-5">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Price History</p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <p className="font-display italic text-lg text-dark-text-primary leading-tight">
                        {activeAssetInfo ? (
                          <>
                            <span style={{ color: activeAssetInfo.color }}>{activeAssetInfo.ticker}</span>
                            {' '}
                            <span className="text-dark-text-secondary text-base not-italic font-sans">{activeAssetInfo.name}</span>
                          </>
                        ) : 'Market Chart'}
                      </p>
                      {chartLoading && <Loader2 size={11} className="text-dark-text-muted animate-spin" />}
                    </div>
                  </div>
                  <LineChart size={14} className="text-dark-text-muted/40" />
                </div>

                {!selectedTicker ? (
                  <div className="flex flex-col items-center justify-center py-10 gap-3">
                    <div className="w-10 h-10 rounded-xl bg-dark-elevated border border-dark-border flex items-center justify-center">
                      <BarChart2 size={16} className="text-dark-text-muted" />
                    </div>
                    <p className="font-mono text-[10px] text-dark-text-muted/60 text-center">
                      Select an asset above to view<br />price history and forecast
                    </p>
                  </div>
                ) : (
                  <AssetChart data={chartData} loading={chartLoading} error={chartError} />
                )}
              </div>
            </motion.div>

            {/* ── Agent pipeline ────────────────────────────────────── */}
            <motion.div
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.20 }}
              className="rounded-xl overflow-hidden bg-dark-card border border-dark-border"
            >
              <div className="h-[1px] bg-gradient-to-r from-transparent via-dark-border/60 to-transparent" />
              <div className="px-6 py-5">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Orchestration</p>
                    <p className="font-display italic text-lg text-dark-text-primary mt-0.5">Multi-Agent Pipeline</p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    {isActive ? (
                      <><span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse-dot" /><span className="font-mono text-[9px] uppercase tracking-widest text-amber-400">Running</span></>
                    ) : phase === 'done' ? (
                      <><CheckCircle2 size={10} className="text-sentinel-green-neon" /><span className="font-mono text-[9px] uppercase tracking-widest text-sentinel-green-neon">Done</span></>
                    ) : phase === 'error' ? (
                      <><AlertTriangle size={10} className="text-sentinel-red-neon" /><span className="font-mono text-[9px] uppercase tracking-widest text-sentinel-red-neon">Failed</span></>
                    ) : (
                      <><span className="w-1.5 h-1.5 rounded-full bg-dark-text-muted opacity-40" /><span className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Idle</span></>
                    )}
                  </div>
                </div>

                <div className="flex items-center overflow-x-auto pb-2">
                  {AGENTS.map((agent, idx) => {
                    const nodeStatus = getAgentNodeStatus(idx, phase, elapsedMs)
                    const isNodeActive = nodeStatus === 'active'
                    const isNodeDone   = nodeStatus === 'done'
                    const isNodeError  = nodeStatus === 'error'
                    const { Icon } = agent
                    return (
                      <div key={agent.id} className="flex items-center flex-shrink-0">
                        <div className="flex flex-col items-center gap-2.5 group/node">
                          <motion.div
                            animate={isNodeActive ? { scale: [1, 1.08, 1] } : {}}
                            transition={isNodeActive ? { duration: 1.4, repeat: Infinity } : {}}
                            className={cn(
                              'agent-node ring-1 transition-all duration-300',
                              isNodeActive && `${agent.bg} ${agent.ring} shadow-glow-green-sm`,
                              isNodeDone   && 'bg-sentinel-green-neon/10 ring-sentinel-green-neon/40',
                              isNodeError  && 'bg-sentinel-red-neon/10 ring-sentinel-red-neon/40',
                              (nodeStatus === 'idle' || nodeStatus === 'pending') && `${agent.bg} ${agent.ring} opacity-40`,
                            )}
                          >
                            {isNodeDone  ? <CheckCircle2 size={13} className="text-sentinel-green-neon" />
                            : isNodeError ? <AlertTriangle size={13} className="text-sentinel-red-neon" />
                            : isNodeActive ? (
                              <motion.div animate={{ rotate: 360 }} transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }}>
                                <Icon size={13} style={{ color: agent.color }} />
                              </motion.div>
                            ) : (
                              <Icon size={13} style={{ color: (nodeStatus === 'idle' || nodeStatus === 'pending') ? '#5a6a8a' : agent.color }} />
                            )}
                          </motion.div>
                          <div className="text-center">
                            <p className={cn(
                              'font-mono text-[9px] font-medium whitespace-nowrap transition-colors',
                              isNodeActive ? 'text-dark-text-primary' : isNodeDone ? 'text-sentinel-green-neon' : 'text-dark-text-muted',
                            )}>{agent.label}</p>
                            <p className="font-mono text-[8px] text-dark-text-muted whitespace-nowrap">{agent.sub}</p>
                          </div>
                        </div>
                        {idx < AGENTS.length - 1 && (
                          <div className={cn('agent-connector mx-2 sm:mx-4 flex-shrink-0 transition-opacity duration-500', isNodeDone || phase === 'done' ? 'opacity-100' : 'opacity-30')} style={{ minWidth: 28 }} />
                        )}
                      </div>
                    )
                  })}
                </div>

                <div className="mt-5 pt-4 border-t border-dark-border flex flex-wrap gap-x-5 gap-y-1">
                  {['GDELT → long-memory synthesis', 'Chronos-2 zero-shot forecasting', 'GARCH volatility · Monte Carlo scenarios'].map(t => (
                    <span key={t} className="font-mono text-[9px] text-dark-text-muted">{t}</span>
                  ))}
                  {isActive && elapsedMs > 0 && (
                    <span className="font-mono text-[9px] text-amber-400/80 ml-auto">{Math.floor(elapsedMs / 1000)}s</span>
                  )}
                </div>
              </div>
            </motion.div>

            {/* ── Watchlist ──────────────────────────────────────────── */}
            {watchlist.length > 0 ? (
              <motion.div
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.45, delay: 0.26 }}
                className="rounded-xl overflow-hidden bg-dark-card border border-dark-border"
              >
                <div className="h-[1px] bg-gradient-to-r from-transparent via-dark-border/60 to-transparent" />
                <div className="px-6 py-5">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Monitored</p>
                      <p className="font-display italic text-lg text-dark-text-primary mt-0.5">Your Watchlist</p>
                    </div>
                    <Link to="/profile" className="flex items-center gap-1 font-mono text-[10px] text-dark-text-muted hover:text-sentinel-green-neon transition-colors">
                      Manage <ChevronRight size={10} />
                    </Link>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {watchlist.map((ticker: string) => (
                      <motion.button
                        key={ticker}
                        whileHover={isActive ? {} : { scale: 1.04 }}
                        whileTap={isActive ? {} : { scale: 0.97 }}
                        onClick={() => handleWatchlistClick(ticker)}
                        disabled={isActive}
                        className={cn(
                          'flex items-center gap-2 px-3 py-2 rounded-xl border transition-all duration-150',
                          selectedTicker === ticker
                            ? 'bg-sentinel-green-neon/10 border-sentinel-green-neon/40 text-sentinel-green-neon'
                            : 'bg-dark-elevated border-dark-border text-dark-text-primary hover:border-sentinel-green-neon/25',
                          isActive && 'opacity-50 cursor-not-allowed',
                        )}
                      >
                        <span className="font-mono text-xs font-bold">{ticker}</span>
                        <Zap size={9} className={selectedTicker === ticker ? 'text-sentinel-green-neon' : 'text-dark-text-muted/40'} />
                      </motion.button>
                    ))}
                  </div>
                  <p className="font-mono text-[9px] text-dark-text-muted/50 mt-3">
                    Click a ticker to immediately run the full intelligence pipeline
                  </p>
                </div>
              </motion.div>
            ) : (
              <motion.div
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.45, delay: 0.26 }}
                className="rounded-xl overflow-hidden bg-dark-card border border-dashed border-dark-border"
              >
                <div className="px-6 py-4 flex items-center gap-4">
                  <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-dark-elevated border border-dark-border flex-shrink-0">
                    <BarChart2 size={15} className="text-dark-text-muted" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-mono text-xs text-dark-text-secondary">No watchlist configured</p>
                    <p className="font-mono text-[10px] text-dark-text-muted">Configure your watchlist in Profile to monitor specific instruments</p>
                  </div>
                  <Link
                    to="/profile"
                    className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-sentinel-green-neon/8 border border-sentinel-green-neon/20 font-mono text-[10px] text-sentinel-green-neon hover:bg-sentinel-green-neon/14 transition-colors"
                  >
                    Configure
                  </Link>
                </div>
              </motion.div>
            )}
          </div>

          {/* Right 1/3 */}
          <div className="space-y-5">

            {/* Live feeds + services */}
            <motion.div
              initial={{ opacity: 0, x: 14 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.45, delay: 0.14 }}
              className="rounded-xl overflow-hidden bg-dark-card border border-dark-border"
            >
              <div className="h-[1px] bg-gradient-to-r from-transparent via-sentinel-green-neon/30 to-transparent" />
              <div className="px-5 py-5">
                <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-4">Live Data Feeds</p>
                <div className="space-y-4">
                  {FEEDS.map(f => (
                    <div key={f.name} className="flex items-center gap-3">
                      <span className="w-1.5 h-1.5 rounded-full bg-sentinel-green-neon animate-pulse-dot flex-shrink-0 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <p className="font-mono text-xs text-dark-text-primary">{f.name}</p>
                        <p className="font-mono text-[9px] text-dark-text-muted">{f.detail}</p>
                      </div>
                      <span className="font-mono text-[9px] uppercase tracking-widest text-sentinel-green-neon flex-shrink-0">Live</span>
                    </div>
                  ))}
                </div>
                <div className="mt-4 pt-4 border-t border-dark-border">
                  <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-3">Services</p>
                  <div className="space-y-2.5">
                    {[
                      { name: 'MongoDB',       ok: true },
                      { name: 'Qdrant',        ok: true },
                      { name: 'LangGraph',     ok: isActive || phase === 'done' },
                      { name: 'Groq (Llama)',  ok: isActive || phase === 'done' },
                    ].map(svc => (
                      <div key={svc.name} className="flex items-center justify-between">
                        <span className="font-mono text-[10px] text-dark-text-muted">{svc.name}</span>
                        <span className={cn('font-mono text-[9px] uppercase tracking-widest', svc.ok ? 'text-sentinel-green-neon' : 'text-dark-text-muted/50')}>
                          {svc.ok ? 'Connected' : 'Standby'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </motion.div>

            {/* Recent analyses */}
            <motion.div
              initial={{ opacity: 0, x: 14 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.45, delay: 0.22 }}
              className="rounded-xl overflow-hidden bg-dark-card border border-dark-border"
            >
              <div className="h-[1px] bg-gradient-to-r from-transparent via-dark-border/50 to-transparent" />
              <div className="px-5 py-5">
                <div className="flex items-center justify-between mb-4">
                  <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Recent Analyses</p>
                  <Clock size={11} className="text-dark-text-muted/40" />
                </div>
                {historyLoading && history.length === 0 ? (
                  <div className="flex items-center justify-center py-6">
                    <Loader2 size={16} className="text-dark-text-muted animate-spin" />
                  </div>
                ) : history.length === 0 ? (
                  <div className="flex flex-col items-center text-center gap-3 py-6">
                    <div className="w-12 h-12 rounded-2xl flex items-center justify-center bg-dark-elevated border border-dark-border">
                      <Radar size={20} className="text-dark-text-muted" />
                    </div>
                    <div>
                      <p className="font-mono text-xs text-dark-text-secondary">No reports yet</p>
                      <p className="font-mono text-[10px] text-dark-text-muted mt-0.5 leading-relaxed">
                        Select an asset above<br />to run your first analysis
                      </p>
                    </div>
                  </div>
                ) : (
                  <div>
                    {history.slice(0, 8).map(run => (
                      <HistoryRow key={run.run_id} run={run} onView={(id, status) => { viewReport(id, status) }} />
                    ))}
                  </div>
                )}
              </div>
            </motion.div>

            {/* Intelligence stack */}
            <motion.div
              initial={{ opacity: 0, x: 14 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.45, delay: 0.30 }}
              className="rounded-xl overflow-hidden bg-dark-card border border-dark-border"
            >
              <div className="h-[1px] bg-gradient-to-r from-transparent via-dark-border/50 to-transparent" />
              <div className="px-5 py-5">
                <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-3">Intelligence Stack</p>
                <div className="flex flex-wrap gap-1.5">
                  {['Groq (Llama-3.1)', 'LangGraph', 'Chronos-2', 'GARCH', 'Monte Carlo', 'GDELT', 'FRED API'].map(tech => (
                    <span key={tech} className={cn(
                      'font-mono text-[9px] px-2 py-1 rounded-md',
                      'bg-dark-elevated text-dark-text-muted border border-dark-border',
                      'hover:border-sentinel-green-neon/20 hover:text-dark-text-secondary transition-colors',
                    )}>
                      {tech}
                    </span>
                  ))}
                </div>
                <p className="font-mono text-[9px] text-dark-text-muted/60 mt-4 leading-relaxed">
                  Probability-weighted scenarios with full reasoning traces. Zero trading signals.
                </p>
              </div>
            </motion.div>
          </div>
        </div>
      </main>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <footer className="border-t border-dark-border px-6 py-3">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <span className="font-mono text-[10px] text-dark-text-muted/40">SentinelAI · Intelligence Platform · v0.1</span>
          <span className="font-mono text-[10px] text-dark-text-muted/40 hidden sm:block">
            End-to-end encrypted · Zero trading signals · bcrypt · JWT
          </span>
        </div>
      </footer>

      {/* ── Report modal ─────────────────────────────────────────────── */}
      {reportOpen && report && (
        <ReportModal report={report} onClose={() => { setReportOpen(false); dismiss() }} />
      )}
    </div>
  )
}
