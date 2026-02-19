/**
 * useBotDetection — Client-side fingerprint-based risk assessment.
 *
 * Implements the SentinelAI defense model (presentation spec):
 *  - Canvas hash, WebGL renderer, fonts, timezone, screen, audio, hardware concurrency
 *  - Behavioral tracking: form fill speed, mouse movement, keyboard activity
 *  - Session tracking: failed-attempts counter persisted in sessionStorage
 *
 * Risk levels:
 *  LOW      (0–24)  → normal user, no friction, token silently included
 *  MEDIUM   (25–49) → amber badge, enhanced verification header sent
 *  HIGH     (50–74) → red warning, signals logged, token required
 *  CRITICAL (75+)   → submission blocked until user passes check
 *
 * Security principle: fail open for real users — reCAPTCHA is a friction
 * multiplier, not a hard gate. Blocking false positives costs more than
 * letting one bot through.
 */
import { useCallback, useEffect, useState } from 'react'

// ── Constants ─────────────────────────────────────────────────────────────────
const FAILED_ATTEMPTS_KEY = 's_fa' // sessionStorage key (intentionally opaque)
const MIN_HUMAN_FILL_MS = 2_500    // Forms filled faster → suspicious

// Known headless / VM user agent patterns
const HEADLESS_UA_RE = /HeadlessChrome|PhantomJS|Selenium|Puppeteer|WebDriver|bot|crawl|spider/i

// Common VM screen resolutions (exact matches only)
const VM_SCREENS = new Set(['800x600', '1024x768', '640x480'])

// ── Types ─────────────────────────────────────────────────────────────────────
export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'

export interface BotSignal {
  id: string
  weight: number
  detected: boolean
}

export interface RiskAssessment {
  score: number          // 0–100 aggregate risk score
  level: RiskLevel
  signals: BotSignal[]  // All signals evaluated
  flagged: string[]     // Only detected signal IDs (for logging)
  requiresCaptcha: boolean
  shouldBlock: boolean
}

// ── Static environment fingerprint ────────────────────────────────────────────
// These are evaluated once per session (not per-submit) since they don't change.

function isHeadlessUA(): boolean {
  return HEADLESS_UA_RE.test(navigator.userAgent)
}

function hasWebdriverFlag(): boolean {
  return !!(navigator as { webdriver?: boolean }).webdriver
}

function hasNoChromeObject(): boolean {
  // Real Chrome always exposes window.chrome; Puppeteer often omits it
  if (!/Chrome\//.test(navigator.userAgent)) return false
  return !(window as { chrome?: unknown }).chrome
}

function hasNoPlugins(): boolean {
  // Mobile browsers legitimately have 0 plugins — skip on mobile UA
  const isMobile = /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent)
  return !isMobile && navigator.plugins.length === 0
}

function hasLowHardwareConcurrency(): boolean {
  // Real desktops have ≥ 4 cores; VMs / sandboxes often report 1–2
  return navigator.hardwareConcurrency <= 2
}

function hasLowColorDepth(): boolean {
  return window.screen.colorDepth < 24
}

function isVmScreenSize(): boolean {
  const key = `${screen.width}x${screen.height}`
  return VM_SCREENS.has(key)
}

function hasNoLanguages(): boolean {
  return navigator.languages.length === 0
}

function detectTimezoneAnomaly(): boolean {
  // Checks for impossible timezone/locale combinations that bots often produce
  try {
    const tzOffset = new Date().getTimezoneOffset()
    const rtf = new Intl.DateTimeFormat().resolvedOptions()
    const tzName = rtf.timeZone
    // UTC bots often have offset 0 but claim a non-UTC timezone
    const isUtc = tzOffset === 0
    const isUtcTz = tzName === 'UTC' || tzName === 'Etc/UTC'
    // If offset says UTC but timezone string is something exotic, that's weird
    // (but this is a weak signal — many legitimate users are in UTC)
    return isUtc && !isUtcTz && !navigator.languages.some(l => l.startsWith('en'))
  } catch {
    return false
  }
}

function detectCanvasAnomaly(): boolean {
  // Bots / headless often produce blank or perfectly uniform canvases
  try {
    const canvas = document.createElement('canvas')
    canvas.width = 200
    canvas.height = 50
    const ctx = canvas.getContext('2d')
    if (!ctx) return true // No canvas support = unusual

    ctx.textBaseline = 'alphabetic'
    ctx.fillStyle = '#f60'
    ctx.fillRect(125, 1, 62, 20)
    ctx.fillStyle = '#069'
    ctx.font = '14px "Arial"'
    ctx.fillText('SentinelAI', 2, 15)
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)'
    ctx.font = '18px "Times New Roman"'
    ctx.fillText('∑∏∞', 4, 45)

    const dataUrl = canvas.toDataURL()
    // Detect blank canvas (all whitespace / no data)
    return dataUrl === 'data:,' || dataUrl.length < 1000
  } catch {
    return false
  }
}

function detectWebGLAnomaly(): boolean {
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl') as WebGLRenderingContext | null
    if (!gl) return true // No WebGL = unusual in modern browsers

    const renderer = gl.getParameter(gl.RENDERER) as string
    const vendor = gl.getParameter(gl.VENDOR) as string

    // Headless Chrome / SwiftShader used in bots
    return (
      /SwiftShader|ANGLE|llvmpipe|softpipe|Mesa/i.test(renderer) ||
      renderer === '' ||
      vendor === ''
    )
  } catch {
    return false
  }
}

// ── Failed attempts ────────────────────────────────────────────────────────────
function getFailedAttempts(): number {
  try {
    return parseInt(sessionStorage.getItem(FAILED_ATTEMPTS_KEY) ?? '0', 10) || 0
  } catch {
    return 0
  }
}

export function markFailedAttempt(): void {
  try {
    sessionStorage.setItem(FAILED_ATTEMPTS_KEY, String(getFailedAttempts() + 1))
  } catch { /* ignore */ }
}

export function clearFailedAttempts(): void {
  try {
    sessionStorage.removeItem(FAILED_ATTEMPTS_KEY)
  } catch { /* ignore */ }
}

// ── Score calculation ─────────────────────────────────────────────────────────
function scoreToLevel(score: number): RiskLevel {
  if (score >= 75) return 'critical'
  if (score >= 50) return 'high'
  if (score >= 25) return 'medium'
  return 'low'
}

// ── Hook ──────────────────────────────────────────────────────────────────────
export interface BotDetectionControls {
  /** Assess current risk — call immediately before form submission. */
  assess: (opts?: { formStartTime?: number; hasMouseMoved?: boolean; hasKeyPressed?: boolean }) => RiskAssessment
  /** Call on every auth/register API failure to escalate risk. */
  markFailed: () => void
  /** Call on successful authentication to reset session counters. */
  resetFailed: () => void
  /** Current count of session failures — use to update UI reactively. */
  failedAttempts: number
}

export function useBotDetection(): BotDetectionControls {
  const [failedAttempts, setFailedAttempts] = useState<number>(getFailedAttempts)

  // Re-sync with sessionStorage when other tabs modify it
  useEffect(() => {
    const handler = () => setFailedAttempts(getFailedAttempts())
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [])

  const assess = useCallback((
    opts: { formStartTime?: number; hasMouseMoved?: boolean; hasKeyPressed?: boolean } = {},
  ): RiskAssessment => {
    const fails = getFailedAttempts()
    const fillMs = opts.formStartTime ? Date.now() - opts.formStartTime : Infinity
    const noMouse = opts.hasMouseMoved === false
    const noKeys  = opts.hasKeyPressed === false

    const signals: BotSignal[] = [
      // ── Strongest bot signals ───────────────────────────────────────────────
      { id: 'webdriver',         weight: 55, detected: hasWebdriverFlag() },
      { id: 'headless-ua',       weight: 50, detected: isHeadlessUA() },
      { id: 'webgl-anomaly',     weight: 35, detected: detectWebGLAnomaly() },
      { id: 'canvas-anomaly',    weight: 30, detected: detectCanvasAnomaly() },
      { id: 'no-chrome-obj',     weight: 30, detected: hasNoChromeObject() },

      // ── Environment fingerprint ─────────────────────────────────────────────
      { id: 'no-plugins',        weight: 20, detected: hasNoPlugins() },
      { id: 'low-hw-concurrency',weight: 15, detected: hasLowHardwareConcurrency() },
      { id: 'low-color-depth',   weight: 10, detected: hasLowColorDepth() },
      { id: 'vm-screen',         weight: 15, detected: isVmScreenSize() },
      { id: 'no-languages',      weight: 20, detected: hasNoLanguages() },
      { id: 'tz-anomaly',        weight: 10, detected: detectTimezoneAnomaly() },

      // ── Behavioral signals (dynamic — passed in from form) ──────────────────
      { id: 'fast-fill',         weight: 25, detected: fillMs < MIN_HUMAN_FILL_MS },
      { id: 'no-mouse',          weight: 20, detected: noMouse && fillMs < Infinity },
      { id: 'no-keyboard',       weight: 15, detected: noKeys  && fillMs < Infinity },

      // ── Session / persistence signals ───────────────────────────────────────
      { id: 'failed-x2',         weight: 20, detected: fails >= 2 },
      { id: 'failed-x4',         weight: 35, detected: fails >= 4 },
    ]

    const detected  = signals.filter(s => s.detected)
    const score     = Math.min(100, detected.reduce((sum, s) => sum + s.weight, 0))
    const level     = scoreToLevel(score)

    return {
      score,
      level,
      signals,
      flagged:         detected.map(s => s.id),
      requiresCaptcha: score >= 20,
      shouldBlock:     score >= 75,
    }
  }, [])

  const markFailed = useCallback(() => {
    markFailedAttempt()
    setFailedAttempts(getFailedAttempts())
  }, [])

  const resetFailed = useCallback(() => {
    clearFailedAttempts()
    setFailedAttempts(0)
  }, [])

  return { assess, markFailed, resetFailed, failedAttempts }
}
