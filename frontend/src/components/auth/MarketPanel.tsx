import { motion } from 'framer-motion'
import Logo from '@/components/ui/Logo'

// ── Icons ───────────────────────────────────────────────────────────────────
function ShieldIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="w-3.5 h-3.5">
      <path
        d="M8 1.5L2 4v4c0 3.3 2.5 5.8 6 6.5 3.5-.7 6-3.2 6-6.5V4L8 1.5z"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function NetworkIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="w-3.5 h-3.5">
      <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.25" />
      <circle cx="2.5" cy="8" r="1.25" stroke="currentColor" strokeWidth="1.25" />
      <circle cx="13.5" cy="8" r="1.25" stroke="currentColor" strokeWidth="1.25" />
      <circle cx="8" cy="2.5" r="1.25" stroke="currentColor" strokeWidth="1.25" />
      <circle cx="8" cy="13.5" r="1.25" stroke="currentColor" strokeWidth="1.25" />
      <path
        d="M3.75 8h2.25M10 8h2.25M8 3.75v2.25M8 10v2.25"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
      />
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" className="w-3.5 h-3.5">
      <path
        d="M13.5 4.5l-7 7L3 8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// ── Feature list ─────────────────────────────────────────────────────────────
const FEATURES = [
  {
    icon: <ShieldIcon />,
    title: 'Multi-asset risk coverage',
    desc: 'Gold, Crude Oil, S&P 500, Bitcoin, and Ethereum — five markets, one view.',
  },
  {
    icon: <NetworkIcon />,
    title: 'Autonomous agent pipeline',
    desc: 'Seven specialized AI agents collaborate to produce verified intelligence briefs.',
  },
  {
    icon: <CheckIcon />,
    title: 'Source-attributed analysis',
    desc: 'Every claim traced to its origin. No hallucinations, no black boxes.',
  },
]

const STATS = [
  { val: '5',    label: 'Asset Classes' },
  { val: '<30s', label: 'Per Analysis' },
  { val: '7',    label: 'AI Agents' },
]

// ── Market Panel ─────────────────────────────────────────────────────────────
export default function MarketPanel() {
  return (
    <div
      className="
        auth-market-panel relative flex flex-col overflow-hidden
        bg-dark-bg
        bg-grid-dark
      "
    >
      {/* Ambient glow — top-left */}
      <div
        className="absolute -top-40 -left-40 w-[480px] h-[480px] rounded-full pointer-events-none
          bg-sentinel-green-neon/[0.04] blur-3xl"
        aria-hidden="true"
      />
      {/* Ambient glow — bottom-right */}
      <div
        className="absolute -bottom-24 -right-24 w-72 h-72 rounded-full pointer-events-none
          bg-sentinel-green-neon/[0.03] blur-3xl"
        aria-hidden="true"
      />

      {/* Content */}
      <div className="relative z-10 flex flex-col flex-1 px-10 py-10 gap-12 justify-between">

        {/* Logo */}
        <motion.div
          initial={{ opacity: 0, y: -12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        >
          <Logo size="lg" showTagline />
        </motion.div>

        {/* Hero text */}
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.15, ease: 'easeOut' }}
          className="flex flex-col gap-4"
        >
          <h2 className="font-display italic text-[2.4rem] leading-tight text-dark-text-primary max-w-xs">
            Geopolitical intelligence at machine speed.
          </h2>
          <p className="font-sans text-sm leading-relaxed text-dark-text-secondary max-w-sm">
            SentinelAI synthesizes global news, macroeconomic signals, and market
            data into verified risk briefs — in under 30 seconds.
          </p>
        </motion.div>

        {/* Features */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.3 }}
          className="flex flex-col gap-5"
        >
          {FEATURES.map((f, i) => (
            <motion.div
              key={f.title}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.45, delay: 0.35 + i * 0.1 }}
              className="flex items-start gap-3.5"
            >
              <div
                className="
                  flex-shrink-0 mt-0.5 w-7 h-7 rounded-lg flex items-center justify-center
                  bg-sentinel-green-neon/10
                  text-sentinel-green-neon
                  border border-sentinel-green-neon/20
                "
              >
                {f.icon}
              </div>
              <div>
                <p className="font-sans text-sm font-semibold text-dark-text-primary mb-0.5">
                  {f.title}
                </p>
                <p className="font-sans text-xs leading-relaxed text-dark-text-secondary">
                  {f.desc}
                </p>
              </div>
            </motion.div>
          ))}
        </motion.div>

        {/* Stats strip */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.6 }}
          className="flex items-center gap-8 pt-6 border-t border-dark-border"
        >
          {STATS.map((s) => (
            <div key={s.label} className="flex flex-col gap-0.5">
              <span className="font-display italic text-2xl text-sentinel-green-neon">
                {s.val}
              </span>
              <span className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted">
                {s.label}
              </span>
            </div>
          ))}
        </motion.div>

      </div>
    </div>
  )
}
