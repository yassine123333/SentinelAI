/**
 * SecurityBadge — adaptive risk status indicator.
 *
 * Appearance adapts to the current risk level assessed by useBotDetection:
 *
 *  LOW      → Tiny green "Protected" pill. Almost invisible — real users
 *              shouldn't notice or be bothered by security.
 *
 *  MEDIUM   → Amber "Enhanced verification active" bar with pulsing dot.
 *              Shown after ≥2 failed attempts or moderate fingerprint signals.
 *
 *  HIGH     → Red "Suspicious activity detected" panel with signal list.
 *              Submission still allowed but token is required and risk logged.
 *
 *  CRITICAL → Full red blocker with "Automated access detected" header and
 *              a manual override button (in case of false positive).
 *              reCAPTCHA may surface an image challenge via Google's engine.
 */

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Shield, ShieldAlert, ShieldCheck, ShieldX, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react'
import type { RiskLevel } from '@/hooks/useBotDetection'
import { cn } from '@/lib/utils'

interface SecurityBadgeProps {
  level: RiskLevel
  score: number
  flagged: string[]
  failedAttempts: number
  isRecaptchaReady: boolean
  /** Called when the user requests a manual override from CRITICAL state */
  onOverride?: () => void
}

// ── Human-readable signal labels ──────────────────────────────────────────────
const SIGNAL_LABELS: Record<string, string> = {
  'webdriver':          'Automation API detected',
  'headless-ua':        'Headless browser UA',
  'webgl-anomaly':      'WebGL renderer anomaly (SwiftShader/Mesa)',
  'canvas-anomaly':     'Canvas rendering anomaly',
  'no-chrome-obj':      'Chrome object fingerprint mismatch',
  'no-plugins':         'No browser plugins detected',
  'low-hw-concurrency': 'Low CPU core count (<= 2)',
  'low-color-depth':    'Low display color depth',
  'vm-screen':          'VM/remote desktop screen resolution',
  'no-languages':       'No browser language settings',
  'tz-anomaly':         'Timezone / locale mismatch',
  'fast-fill':          'Form completed too quickly (< 2.5s)',
  'no-mouse':           'No mouse movement detected',
  'no-keyboard':        'No keyboard activity detected',
  'failed-x2':          '2+ failed authentication attempts',
  'failed-x4':          '4+ failed authentication attempts',
}

// ── Level config ──────────────────────────────────────────────────────────────
type LevelConfig = {
  icon: typeof Shield
  label: string
  sublabel: string
  iconClass: string
  borderClass: string
  bgClass: string
  textClass: string
  dotClass: string
  pulseClass: string
}

const LEVEL_CONFIG: Record<RiskLevel, LevelConfig> = {
  low: {
    icon:       ShieldCheck,
    label:      'Protected',
    sublabel:   'reCAPTCHA',
    iconClass:  'text-sentinel-green-neon',
    borderClass:'border-dark-border',
    bgClass:    'bg-dark-elevated',
    textClass:  'text-dark-text-muted',
    dotClass:   'bg-sentinel-green-neon',
    pulseClass: 'animate-pulse-dot',
  },
  medium: {
    icon:       Shield,
    label:      'Enhanced Verification Active',
    sublabel:   'Elevated monitoring due to repeated failures',
    iconClass:  'text-sentinel-gold',
    borderClass:'border-sentinel-gold/30',
    bgClass:    'bg-sentinel-gold/5',
    textClass:  'text-sentinel-gold',
    dotClass:   'bg-sentinel-gold',
    pulseClass: 'animate-pulse-dot',
  },
  high: {
    icon:       ShieldAlert,
    label:      'Suspicious Activity Detected',
    sublabel:   'Proceed with verification — this attempt is being logged',
    iconClass:  'text-sentinel-red-neon',
    borderClass:'border-sentinel-red-neon/30',
    bgClass:    'bg-sentinel-red-neon/5',
    textClass:  'text-sentinel-red-neon',
    dotClass:   'bg-sentinel-red-neon',
    pulseClass: 'animate-pulse-dot',
  },
  critical: {
    icon:       ShieldX,
    label:      'Automated Access Detected',
    sublabel:   'Bot-like behavior fingerprinted. Manual override available if this is an error.',
    iconClass:  'text-sentinel-red-neon',
    borderClass:'border-sentinel-red-neon/40',
    bgClass:    'bg-sentinel-red-neon/8',
    textClass:  'text-sentinel-red-neon',
    dotClass:   'bg-sentinel-red-neon',
    pulseClass: 'animate-pulse',
  },
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function SecurityBadge({
  level,
  score,
  flagged,
  failedAttempts,
  isRecaptchaReady,
  onOverride,
}: SecurityBadgeProps) {
  const [showSignals, setShowSignals] = useState(false)
  const cfg = LEVEL_CONFIG[level]
  const Icon = cfg.icon

  // LOW level: render a minimal pill — don't distract legitimate users
  if (level === 'low') {
    return (
      <div className="flex items-center justify-between pt-1">
        <p className={cn('font-mono text-[9px]', cfg.textClass)}>
          This site is protected by reCAPTCHA.{' '}
          <a
            href="https://policies.google.com/privacy"
            target="_blank"
            rel="noopener noreferrer"
            className="underline opacity-60 hover:opacity-100"
          >
            Privacy
          </a>
          {' & '}
          <a
            href="https://policies.google.com/terms"
            target="_blank"
            rel="noopener noreferrer"
            className="underline opacity-60 hover:opacity-100"
          >
            Terms
          </a>
        </p>
        <div className="flex items-center gap-1.5">
          {isRecaptchaReady && (
            <span className={cn('w-1 h-1 rounded-full flex-shrink-0', cfg.dotClass, cfg.pulseClass)} />
          )}
          <Icon size={11} className={cfg.iconClass} aria-hidden />
          <span className={cn('font-mono text-[9px] uppercase tracking-wider', cfg.textClass)}>
            {cfg.sublabel}
          </span>
        </div>
      </div>
    )
  }

  // MEDIUM / HIGH / CRITICAL: more prominent indicators
  return (
    <AnimatePresence>
      <motion.div
        key={level}
        initial={{ opacity: 0, y: 8, height: 0 }}
        animate={{ opacity: 1, y: 0, height: 'auto' }}
        exit={{ opacity: 0, y: -4, height: 0 }}
        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        className={cn(
          'rounded-md border overflow-hidden',
          cfg.borderClass,
          cfg.bgClass,
        )}
        role="alert"
        aria-live="polite"
      >
        <div className="px-3 py-2.5 flex items-start gap-2.5">
          {/* Icon with pulse ring for critical */}
          <div className="relative flex-shrink-0 mt-0.5">
            {level === 'critical' && (
              <span
                className={cn(
                  'absolute inset-0 rounded-full animate-ping opacity-30',
                  cfg.dotClass,
                )}
                aria-hidden
              />
            )}
            <Icon size={14} className={cfg.iconClass} aria-hidden />
          </div>

          <div className="flex-1 min-w-0">
            {/* Header row */}
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className={cn('font-mono text-[11px] font-medium uppercase tracking-wide', cfg.textClass)}>
                  {cfg.label}
                </p>
                <p className={cn('font-mono text-[10px] mt-0.5 opacity-75', cfg.textClass)}>
                  {cfg.sublabel}
                </p>
              </div>

              {/* Score badge */}
              <div className={cn(
                'flex-shrink-0 px-1.5 py-0.5 rounded font-mono text-[9px] font-medium border',
                cfg.borderClass, cfg.textClass,
              )}>
                {score}/100
              </div>
            </div>

            {/* Signal details (expandable on high/critical) */}
            {(level === 'high' || level === 'critical') && flagged.length > 0 && (
              <div className="mt-2">
                <button
                  type="button"
                  onClick={() => setShowSignals(p => !p)}
                  className={cn(
                    'flex items-center gap-1 font-mono text-[10px] opacity-70 hover:opacity-100 transition-opacity',
                    cfg.textClass,
                  )}
                >
                  {showSignals ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                  {showSignals ? 'Hide' : 'Show'} {flagged.length} detected signal{flagged.length !== 1 ? 's' : ''}
                </button>

                <AnimatePresence>
                  {showSignals && (
                    <motion.ul
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      className="mt-1.5 flex flex-col gap-1"
                    >
                      {flagged.map(id => (
                        <li
                          key={id}
                          className={cn(
                            'flex items-center gap-1.5 font-mono text-[9px] opacity-70',
                            cfg.textClass,
                          )}
                        >
                          <span aria-hidden>›</span>
                          {SIGNAL_LABELS[id] ?? id}
                        </li>
                      ))}
                    </motion.ul>
                  )}
                </AnimatePresence>
              </div>
            )}

            {/* Failed attempts counter */}
            {failedAttempts > 0 && (
              <p className={cn('font-mono text-[9px] mt-1.5 opacity-60', cfg.textClass)}>
                {failedAttempts} failed attempt{failedAttempts !== 1 ? 's' : ''} this session
              </p>
            )}
          </div>
        </div>

        {/* CRITICAL: manual override strip */}
        {level === 'critical' && onOverride && (
          <div className={cn(
            'border-t px-3 py-2 flex items-center gap-2',
            cfg.borderClass,
          )}>
            <RefreshCw size={11} className={cn(cfg.textClass, 'opacity-60')} aria-hidden />
            <span className={cn('font-mono text-[9px] flex-1 opacity-70', cfg.textClass)}>
              False positive? Reset and try once more.
            </span>
            <button
              type="button"
              onClick={onOverride}
              className={cn(
                'font-mono text-[9px] uppercase tracking-wider px-2 py-1 rounded border',
                'transition-opacity opacity-80 hover:opacity-100',
                cfg.borderClass, cfg.textClass,
              )}
            >
              Override
            </button>
          </div>
        )}

        {/* Google TOS attribution (required) */}
        <div className={cn('px-3 pb-2', level !== 'critical' && 'pt-0')}>
          <p className={cn('font-mono text-[8px] opacity-40', cfg.textClass)}>
            Protected by reCAPTCHA ·{' '}
            <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer" className="underline">Privacy</a>
            {' · '}
            <a href="https://policies.google.com/terms" target="_blank" rel="noopener noreferrer" className="underline">Terms</a>
          </p>
        </div>
      </motion.div>
    </AnimatePresence>
  )
}
