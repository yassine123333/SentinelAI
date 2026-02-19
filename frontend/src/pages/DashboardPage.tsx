import { useEffect, useRef, useState, useMemo } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Activity, BarChart2, ChevronDown, ChevronRight,
  Clock, Database, FileText, Globe, LogOut,
  Plus, Radar, Radio, Search, Settings, Shield,
  TrendingDown, TrendingUp, Zap,
} from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import { AVATAR_MAP } from '@/components/profile/ProfileInfoTab'
import Logo from '@/components/ui/Logo'
import { cn } from '@/lib/utils'

// ── Agent pipeline data ────────────────────────────────────────────────────────
const AGENTS = [
  { id: 1, label: 'Intake',      sub: 'Routing',    Icon: Search,     bg: 'bg-sentinel-green-neon/10', ring: 'ring-sentinel-green-neon/30', color: '#00e87b' },
  { id: 2, label: 'Geo & Macro', sub: 'Analysis',   Icon: Globe,      bg: 'bg-blue-500/10',            ring: 'ring-blue-400/30',            color: '#60a5fa' },
  { id: 3, label: 'Sentiment',   sub: 'Engine',     Icon: Radio,      bg: 'bg-purple-500/10',          ring: 'ring-purple-400/30',          color: '#c084fc' },
  { id: 4, label: 'Asset',       sub: 'Forecaster', Icon: TrendingUp, bg: 'bg-amber-500/10',           ring: 'ring-amber-400/30',           color: '#fbbf24' },
  { id: 5, label: 'Critic',      sub: 'Verifier',   Icon: Shield,     bg: 'bg-orange-500/10',          ring: 'ring-orange-400/30',          color: '#fb923c' },
  { id: 6, label: 'Synthesis',   sub: 'Reporter',   Icon: FileText,   bg: 'bg-sentinel-green-neon/10', ring: 'ring-sentinel-green-neon/30', color: '#00e87b' },
] as const

// ── Live data feeds ────────────────────────────────────────────────────────────
const FEEDS = [
  { name: 'GDELT Project', detail: '100+ languages · live events'  },
  { name: 'FRED API',      detail: '840K economic time series'      },
  { name: 'yfinance',      detail: 'Real-time asset prices'         },
] as const

// ── Deterministic fake sparkline / pct change per ticker ──────────────────────
function hashStr(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0
  return h >>> 0
}
function getSparkline(ticker: string): number[] {
  const seed = hashStr(ticker)
  return Array.from({ length: 12 }, (_, i) => {
    const v = (hashStr(ticker + i) ^ (seed >> (i % 8))) >>> 0
    return 15 + (v % 85)
  })
}
function getMockPct(ticker: string): number {
  const v = hashStr(ticker)
  return ((v % 600) - 300) / 100  // −3.00 … +3.00
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
      {p(now.getUTCHours())}:{p(now.getUTCMinutes())}:{p(now.getUTCSeconds())}{' '}
      <span className="opacity-40">UTC</span>
    </span>
  )
}

type AuthUser = NonNullable<ReturnType<typeof useAuth>['user']>

function ProfileWidget({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const navigate   = useNavigate()
  const [open, setOpen] = useState(false)
  const ref        = useRef<HTMLDivElement>(null)

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
          'hover:border-sentinel-green-neon/30 hover:bg-dark-elevated',
          'transition-all duration-200',
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
            className={cn(
              'absolute right-0 top-full mt-2 w-52 z-50',
              'bg-dark-card border border-dark-border rounded-xl overflow-hidden shadow-card-dark',
            )}
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
}: {
  label: string; value: string | number; sub: string
  icon: React.ElementType; delay?: number; accent?: boolean
}) {
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
      <div className={cn(
        'h-[1px] bg-gradient-to-r from-transparent to-transparent',
        accent ? 'via-sentinel-green-neon/50' : 'via-dark-border/50',
      )} />
      {accent && (
        <div className="absolute top-0 right-0 w-24 h-24 bg-sentinel-green-neon/5 blur-2xl pointer-events-none rounded-full" />
      )}
      <div className="px-5 py-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-2">{label}</p>
          <p className={cn(
            'font-display italic text-2xl font-bold leading-none',
            accent ? 'text-sentinel-green-neon' : 'text-dark-text-primary',
          )}>
            {value}
          </p>
          <p className="font-mono text-[10px] text-dark-text-muted mt-1.5 truncate">{sub}</p>
        </div>
        <div className={cn(
          'flex-shrink-0 p-2.5 rounded-xl mt-0.5',
          accent
            ? 'bg-sentinel-green-neon/10 border border-sentinel-green-neon/20'
            : 'bg-dark-elevated border border-dark-border',
        )}>
          <Icon size={14} className={accent ? 'text-sentinel-green-neon' : 'text-dark-text-muted'} />
        </div>
      </div>
    </motion.div>
  )
}

function TickerChip({ ticker }: { ticker: string }) {
  const bars = useMemo(() => getSparkline(ticker), [ticker])
  const pct  = useMemo(() => getMockPct(ticker), [ticker])
  const up   = pct >= 0

  return (
    <div className={cn(
      'flex items-center gap-3 px-3 py-2.5 rounded-xl cursor-default group',
      'bg-dark-elevated border border-dark-border',
      'hover:border-sentinel-green-neon/25 transition-colors',
    )}>
      <div className="flex flex-col gap-0.5">
        <span className="font-mono text-xs font-bold text-dark-text-primary">{ticker}</span>
        <span className={cn(
          'font-mono text-[9px] flex items-center gap-0.5',
          up ? 'text-sentinel-green-neon' : 'text-sentinel-red-neon',
        )}>
          {up ? <TrendingUp size={8} /> : <TrendingDown size={8} />}
          {up ? '+' : ''}{pct.toFixed(2)}%
        </span>
      </div>
      <div className="sparkline flex-shrink-0 opacity-60 group-hover:opacity-100 transition-opacity">
        {bars.map((h, i) => (
          <div
            key={i}
            className={cn('sparkline-bar', up ? 'bg-sentinel-green-neon' : 'bg-sentinel-red-neon')}
            style={{ height: `${h}%` }}
          />
        ))}
      </div>
    </div>
  )
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const { isAuthenticated, isLoading, logout, user } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (!isLoading && !isAuthenticated) navigate('/login', { replace: true })
  }, [isAuthenticated, isLoading, navigate])

  if (isLoading) {
    return (
      <div className="min-h-dvh bg-dark-bg flex items-center justify-center">
        <div className="btn-spinner" style={{ width: 24, height: 24 }} />
      </div>
    )
  }

  if (!isAuthenticated || !user) return null

  const handleLogout = () => logout().then(() => navigate('/login', { replace: true }))

  const hour      = new Date().getHours()
  const greeting  = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
  const firstName = user.fullname.split(' ')[0]

  return (
    <div className={cn('min-h-dvh flex flex-col', 'bg-dark-bg bg-grid-dark bg-grid-40')}>

      {/* ── Header ──────────────────────────────────────────────────────── */}
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
            <span className="w-1.5 h-1.5 rounded-full bg-sentinel-green-neon animate-pulse-dot" />
            <span className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">All systems online</span>
          </div>
          <ProfileWidget user={user} onLogout={handleLogout} />
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────────────── */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 py-8 space-y-6">

        {/* Greeting row */}
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="flex flex-col sm:flex-row sm:items-end justify-between gap-4"
        >
          <div>
            <p className="font-mono text-[10px] uppercase tracking-widest text-sentinel-green-neon mb-1">
              {greeting}
            </p>
            <h1 className="font-display italic text-4xl text-dark-text-primary leading-none">
              {firstName}.
            </h1>
            <p className="font-sans text-sm text-dark-text-secondary mt-2">
              Your multi-agent intelligence terminal is standing by.
            </p>
          </div>

          <motion.button
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
            className={cn(
              'flex-shrink-0 flex items-center gap-2 px-5 py-2.5 rounded-xl',
              'bg-gradient-to-r from-sentinel-green-neon to-sentinel-green-mid',
              'font-mono text-xs font-bold uppercase tracking-wider text-dark-void',
              'shadow-glow-green-sm hover:shadow-glow-green-md transition-shadow duration-300',
            )}
          >
            <Plus size={13} />
            New Analysis
          </motion.button>
        </motion.div>

        {/* Stat cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
          <StatCard
            label="Tracked Instruments" icon={BarChart2} delay={0} accent
            value={user.ticker_preferences.length || '—'}
            sub={user.ticker_preferences.length ? 'in your watchlist' : 'Add tickers in Profile'}
          />
          <StatCard label="Data Sources"   icon={Database}  delay={0.07} value="3"      sub="GDELT · FRED · yfinance"   />
          <StatCard label="Agent Pipeline" icon={Zap}        delay={0.14} value="6"      sub="agents orchestrated"       />
          <StatCard label="System Status"  icon={Activity}   delay={0.21} value="Ready"  sub="awaiting first analysis"   />
        </div>

        {/* ── Main 2/3 + 1/3 grid ─────────────────────────────────────── */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

          {/* ── Left column ───────────────────────────────────────────── */}
          <div className="xl:col-span-2 space-y-5">

            {/* Analysis terminal */}
            <motion.div
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.08 }}
              className={cn(
                'relative rounded-xl overflow-hidden',
                'bg-dark-card border border-dark-border',
                'hover:border-sentinel-green-neon/20 transition-colors duration-300',
                'scan-container',
              )}
            >
              <div className="h-[1px] bg-gradient-to-r from-transparent via-sentinel-green-neon/50 to-transparent" />
              {/* Ambient glow */}
              <div className="absolute top-0 left-1/2 -translate-x-1/2 w-80 h-24 bg-sentinel-green-neon/3 blur-3xl pointer-events-none" />
              {/* Scan line */}
              <div className="scan-line" />

              <div className="relative px-6 py-6">
                <div className="flex items-center gap-3 mb-5">
                  <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-sentinel-green-neon/10 border border-sentinel-green-neon/20 flex-shrink-0">
                    <Search size={15} className="text-sentinel-green-neon" />
                  </div>
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Intelligence Query</p>
                    <p className="font-display italic text-lg text-dark-text-primary leading-tight">Analysis Terminal</p>
                  </div>
                </div>

                {/* Query input */}
                <div className={cn(
                  'flex items-center gap-3 px-4 py-3 rounded-xl',
                  'bg-dark-surface border border-dark-border',
                  'focus-within:border-sentinel-green-neon/40 focus-within:shadow-input-focus-green',
                  'transition-all duration-200',
                )}>
                  <span className="font-mono text-sm text-sentinel-green-neon select-none flex-shrink-0">›_</span>
                  <input
                    type="text"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                    placeholder="Enter ticker symbol  (e.g. AAPL, TSLA, BTC-USD, GC=F…)"
                    className="flex-1 bg-transparent font-mono text-sm text-dark-text-primary placeholder:text-dark-text-muted/40 outline-none min-w-0"
                  />
                  <motion.button
                    whileHover={{ scale: 1.04 }}
                    whileTap={{ scale: 0.97 }}
                    className={cn(
                      'flex items-center gap-1.5 px-4 py-1.5 rounded-lg flex-shrink-0',
                      'bg-sentinel-green-neon/10 border border-sentinel-green-neon/25',
                      'hover:bg-sentinel-green-neon/20 hover:border-sentinel-green-neon/50',
                      'font-mono text-[11px] font-semibold text-sentinel-green-neon uppercase tracking-wider',
                      'transition-all duration-150',
                    )}
                  >
                    <Zap size={11} />
                    Analyze
                  </motion.button>
                </div>

                {/* Quick-select */}
                <div className="flex items-center gap-2 mt-3 flex-wrap">
                  <span className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Quick:</span>
                  {['AAPL', 'TSLA', 'BTC-USD', 'GC=F', 'DX-Y.NYB'].map(t => (
                    <button
                      key={t}
                      onClick={() => setQuery(t)}
                      className="font-mono text-[10px] text-dark-text-muted hover:text-sentinel-green-neon transition-colors"
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>
            </motion.div>

            {/* Agent pipeline */}
            <motion.div
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, delay: 0.16 }}
              className={cn('rounded-xl overflow-hidden', 'bg-dark-card border border-dark-border')}
            >
              <div className="h-[1px] bg-gradient-to-r from-transparent via-dark-border/60 to-transparent" />
              <div className="px-6 py-5">
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Orchestration</p>
                    <p className="font-display italic text-lg text-dark-text-primary mt-0.5">Multi-Agent Pipeline</p>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-dark-text-muted opacity-40" />
                    <span className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Idle</span>
                  </div>
                </div>

                {/* Nodes row */}
                <div className="flex items-center overflow-x-auto pb-2">
                  {AGENTS.map((agent, idx) => {
                    const { Icon } = agent
                    return (
                      <div key={agent.id} className="flex items-center flex-shrink-0">
                        <div className="flex flex-col items-center gap-2.5 group/node">
                          <div className={cn(
                            'agent-node ring-1 transition-transform duration-200 group-hover/node:scale-110',
                            agent.bg, agent.ring,
                          )}>
                            <Icon size={13} style={{ color: agent.color }} />
                          </div>
                          <div className="text-center">
                            <p className="font-mono text-[9px] font-medium text-dark-text-secondary whitespace-nowrap">{agent.label}</p>
                            <p className="font-mono text-[8px] text-dark-text-muted whitespace-nowrap">{agent.sub}</p>
                          </div>
                        </div>
                        {idx < AGENTS.length - 1 && (
                          <div className="agent-connector mx-2 sm:mx-4 flex-shrink-0" style={{ minWidth: 28 }} />
                        )}
                      </div>
                    )
                  })}
                </div>

                <div className="mt-5 pt-4 border-t border-dark-border flex flex-wrap gap-x-5 gap-y-1">
                  {['GDELT → long-memory synthesis', 'Chronos-2 zero-shot forecasting', 'GARCH volatility · Monte Carlo scenarios'].map(t => (
                    <span key={t} className="font-mono text-[9px] text-dark-text-muted">{t}</span>
                  ))}
                </div>
              </div>
            </motion.div>

            {/* Watchlist */}
            {user.ticker_preferences.length > 0 ? (
              <motion.div
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.45, delay: 0.24 }}
                className={cn('rounded-xl overflow-hidden', 'bg-dark-card border border-dark-border')}
              >
                <div className="h-[1px] bg-gradient-to-r from-transparent via-dark-border/60 to-transparent" />
                <div className="px-6 py-5">
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Monitored</p>
                      <p className="font-display italic text-lg text-dark-text-primary mt-0.5">Your Watchlist</p>
                    </div>
                    <Link
                      to="/profile"
                      className="flex items-center gap-1 font-mono text-[10px] text-dark-text-muted hover:text-sentinel-green-neon transition-colors"
                    >
                      Manage <ChevronRight size={10} />
                    </Link>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {user.ticker_preferences.map((ticker: string) => (
                      <TickerChip key={ticker} ticker={ticker} />
                    ))}
                  </div>
                  <p className="font-mono text-[9px] text-dark-text-muted/60 mt-3">
                    Indicative display only · Live prices connect on first analysis run
                  </p>
                </div>
              </motion.div>
            ) : (
              <motion.div
                initial={{ opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.45, delay: 0.24 }}
                className={cn(
                  'rounded-xl overflow-hidden',
                  'bg-dark-card border border-dashed border-dark-border',
                )}
              >
                <div className="px-6 py-4 flex items-center gap-4">
                  <div className="w-9 h-9 rounded-xl flex items-center justify-center bg-dark-elevated border border-dark-border flex-shrink-0">
                    <BarChart2 size={15} className="text-dark-text-muted" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-mono text-xs text-dark-text-secondary">No watchlist configured</p>
                    <p className="font-mono text-[10px] text-dark-text-muted">Add ticker symbols in your profile to monitor instruments</p>
                  </div>
                  <Link
                    to="/profile"
                    className={cn(
                      'flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg',
                      'bg-sentinel-green-neon/8 border border-sentinel-green-neon/20',
                      'font-mono text-[10px] text-sentinel-green-neon',
                      'hover:bg-sentinel-green-neon/14 transition-colors',
                    )}
                  >
                    <Plus size={10} />
                    Add Tickers
                  </Link>
                </div>
              </motion.div>
            )}
          </div>

          {/* ── Right column ──────────────────────────────────────────── */}
          <div className="space-y-5">

            {/* Live data feeds */}
            <motion.div
              initial={{ opacity: 0, x: 14 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.45, delay: 0.14 }}
              className={cn('rounded-xl overflow-hidden', 'bg-dark-card border border-dark-border')}
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
                      { name: 'MongoDB',    ok: true  },
                      { name: 'Qdrant',     ok: true  },
                      { name: 'LangGraph',  ok: false },
                      { name: 'Celery',     ok: false },
                    ].map(svc => (
                      <div key={svc.name} className="flex items-center justify-between">
                        <span className="font-mono text-[10px] text-dark-text-muted">{svc.name}</span>
                        <span className={cn(
                          'font-mono text-[9px] uppercase tracking-widest',
                          svc.ok ? 'text-sentinel-green-neon' : 'text-dark-text-muted/50',
                        )}>
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
              className={cn('rounded-xl overflow-hidden', 'bg-dark-card border border-dark-border')}
            >
              <div className="h-[1px] bg-gradient-to-r from-transparent via-dark-border/50 to-transparent" />
              <div className="px-5 py-5">
                <div className="flex items-center justify-between mb-4">
                  <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">Recent Analyses</p>
                  <Clock size={11} className="text-dark-text-muted/40" />
                </div>
                <div className="flex flex-col items-center text-center gap-3 py-6">
                  <div className="w-12 h-12 rounded-2xl flex items-center justify-center bg-dark-elevated border border-dark-border">
                    <Radar size={20} className="text-dark-text-muted" />
                  </div>
                  <div>
                    <p className="font-mono text-xs text-dark-text-secondary">No reports yet</p>
                    <p className="font-mono text-[10px] text-dark-text-muted mt-0.5 leading-relaxed">
                      Run your first analysis<br />to see intelligence reports here
                    </p>
                  </div>
                </div>
              </div>
            </motion.div>

            {/* Intelligence stack */}
            <motion.div
              initial={{ opacity: 0, x: 14 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.45, delay: 0.30 }}
              className={cn('rounded-xl overflow-hidden', 'bg-dark-card border border-dark-border')}
            >
              <div className="h-[1px] bg-gradient-to-r from-transparent via-dark-border/50 to-transparent" />
              <div className="px-5 py-5">
                <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-3">Intelligence Stack</p>
                <div className="flex flex-wrap gap-1.5">
                  {['Gemini 2.5 Flash', 'LangGraph', 'Chronos-2', 'GARCH', 'Monte Carlo', 'GDELT', 'FRED API'].map(tech => (
                    <span
                      key={tech}
                      className={cn(
                        'font-mono text-[9px] px-2 py-1 rounded-md',
                        'bg-dark-elevated text-dark-text-muted border border-dark-border',
                        'hover:border-sentinel-green-neon/20 hover:text-dark-text-secondary transition-colors',
                      )}
                    >
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

      {/* ── Footer ────────────────────────────────────────────────────────── */}
      <footer className="border-t border-dark-border px-6 py-3">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <span className="font-mono text-[10px] text-dark-text-muted/40">SentinelAI · Intelligence Platform · v0.1</span>
          <span className="font-mono text-[10px] text-dark-text-muted/40 hidden sm:block">
            End-to-end encrypted · Zero trading signals · bcrypt · JWT
          </span>
        </div>
      </footer>
    </div>
  )
}
