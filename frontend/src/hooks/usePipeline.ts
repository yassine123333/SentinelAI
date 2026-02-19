/**
 * usePipeline — state machine for the full query → poll → report flow.
 *
 * Phases:
 *   idle          → waiting for user input
 *   submitting    → POST /query in flight
 *   polling       → GET /pipeline/{runId}/status every 2 s
 *   loading_report→ run is done, fetching full report
 *   done          → report loaded, ready to display
 *   error         → terminal failure
 *
 * Security:
 *   - Client-side injection guard (same regex as backend) — gives instant UX
 *     feedback before the network round-trip; backend validates independently.
 *   - Ticker whitelist regex applied when input looks like a symbol.
 *   - Max query length enforced before submission.
 *   - No sensitive data persisted to localStorage.
 *   - Polling uses setTimeout (not setInterval) — no stacking even if slow.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { pipelineApi } from '@/services/api'
import type { PipelineReport, PipelineStatus, RunStatus, UserRunItem } from '@/types/pipeline'

// ── Client-side validation constants (mirrors backend) ───────────────────────

const _TICKER_RE = /^[A-Z0-9^=.\-]{1,12}$/
const _INJECTION_RE =
  /(ignore\s+previous\s+instructions|disregard\s+all|system\s*:|<\|im_end\|>|<\/s>|act\s+as\s+.*(different|new)\s+(ai|llm|model))/i

// ── Phase type ────────────────────────────────────────────────────────────────

export type PipelinePhase = 'idle' | 'submitting' | 'polling' | 'loading_report' | 'done' | 'error'

export interface UsePipelineReturn {
  phase: PipelinePhase
  runId: string | null
  statusData: PipelineStatus | null
  report: PipelineReport | null
  error: string | null
  elapsedMs: number
  history: UserRunItem[]
  historyLoading: boolean
  /** Submit a new query. rawQuery may be a ticker symbol or natural language. */
  submit: (rawQuery: string) => Promise<void>
  /** Load a report for an existing completed run (from history). */
  viewReport: (runId: string, knownStatus?: RunStatus) => Promise<void>
  /** Return to idle (keeps history intact). */
  dismiss: () => void
  /** Refresh the history list. */
  loadHistory: () => Promise<void>
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parseApiError(err: unknown): string {
  if (err && typeof err === 'object') {
    const e = err as Record<string, unknown>
    // Axios error shape
    if (e.response && typeof e.response === 'object') {
      const res = e.response as Record<string, unknown>
      if (res.status === 429) return 'Rate limit reached — please wait a moment before submitting again.'
      if (res.status === 422) {
        const detail = (res.data as Record<string, unknown>)?.detail
        if (Array.isArray(detail)) {
          return detail.map((d: Record<string, unknown>) => d.msg ?? d).join(', ')
        }
        return String(detail ?? 'Validation error — please check your query.')
      }
      if (res.status === 202) return '' // still in progress — not an error
      const detail = (res.data as Record<string, unknown>)?.detail
      if (detail) return String(detail)
    }
    if (typeof e.message === 'string') return e.message
  }
  return 'An unexpected error occurred. Please try again.'
}

function isTicker(input: string): boolean {
  return _TICKER_RE.test(input.trim().toUpperCase())
}

function buildQuery(rawInput: string): { raw_query: string; asset_hint?: string } {
  const trimmed = rawInput.trim()
  if (isTicker(trimmed)) {
    const ticker = trimmed.toUpperCase()
    return {
      raw_query: `Analyse ${ticker} — provide a full risk and scenario outlook`,
      asset_hint: ticker,
    }
  }
  return { raw_query: trimmed }
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function usePipeline(): UsePipelineReturn {
  const [phase, setPhase] = useState<PipelinePhase>('idle')
  const [runId, setRunId] = useState<string | null>(null)
  const [statusData, setStatusData] = useState<PipelineStatus | null>(null)
  const [report, setReport] = useState<PipelineReport | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsedMs, setElapsedMs] = useState(0)
  const [history, setHistory] = useState<UserRunItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  // Refs hold mutable values that don't trigger re-renders
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startedAtRef = useRef<number | null>(null)
  const activeRunIdRef = useRef<string | null>(null)  // prevents stale closures

  // ── Cleanup on unmount ──────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
      if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current)
    }
  }, [])

  // ── Elapsed timer ───────────────────────────────────────────────────────────
  const startElapsedTimer = useCallback(() => {
    if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current)
    startedAtRef.current = Date.now()
    setElapsedMs(0)
    elapsedTimerRef.current = setInterval(() => {
      if (startedAtRef.current !== null) {
        setElapsedMs(Date.now() - startedAtRef.current)
      }
    }, 500)
  }, [])

  const stopElapsedTimer = useCallback(() => {
    if (elapsedTimerRef.current) {
      clearInterval(elapsedTimerRef.current)
      elapsedTimerRef.current = null
    }
  }, [])

  // ── Load history ────────────────────────────────────────────────────────────
  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const { data } = await pipelineApi.getHistory(20)
      setHistory(data)
    } catch {
      // History load failure is non-fatal — silently ignore
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  // Load on mount
  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  // ── Poll a single run ───────────────────────────────────────────────────────
  const doPoll = useCallback(async (rid: string) => {
    // Guard: abort if a newer run was started
    if (activeRunIdRef.current !== rid) return

    try {
      const { data: status } = await pipelineApi.getStatus(rid)
      if (activeRunIdRef.current !== rid) return  // stale

      setStatusData(status)

      if (status.status === 'done') {
        stopElapsedTimer()
        setPhase('loading_report')
        try {
          const { data: rep } = await pipelineApi.getReport(rid)
          setReport(rep)
          setPhase('done')
        } catch (repErr) {
          setError(parseApiError(repErr) || 'Failed to load report after pipeline completed.')
          setPhase('error')
        }
        await loadHistory()
        return
      }

      if (status.status === 'failed') {
        stopElapsedTimer()
        setError(status.error_message || 'Pipeline analysis failed. Please try again.')
        setPhase('error')
        await loadHistory()
        return
      }

      // Still running — schedule next poll in 2 s
      pollTimerRef.current = setTimeout(() => doPoll(rid), 2_000)
    } catch (pollErr) {
      stopElapsedTimer()
      setError(parseApiError(pollErr))
      setPhase('error')
    }
  }, [loadHistory, stopElapsedTimer])

  // ── Submit a new query ──────────────────────────────────────────────────────
  const submit = useCallback(async (rawInput: string) => {
    const trimmed = rawInput.trim()

    // 1. Client-side validation (backend validates independently)
    if (trimmed.length < 3) {
      setError('Query is too short. Enter a ticker symbol or a question about an asset.')
      setPhase('error')
      return
    }
    if (trimmed.length > 500) {
      setError('Query is too long (max 500 characters).')
      setPhase('error')
      return
    }
    if (_INJECTION_RE.test(trimmed)) {
      setError('Query contains a forbidden pattern.')
      setPhase('error')
      return
    }

    // 2. Clear prior state
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
    stopElapsedTimer()
    setError(null)
    setReport(null)
    setStatusData(null)
    setElapsedMs(0)
    setPhase('submitting')

    try {
      const { raw_query, asset_hint } = buildQuery(trimmed)
      const { data } = await pipelineApi.submit({ raw_query, asset_hint })

      const rid = data.run_id
      setRunId(rid)
      activeRunIdRef.current = rid
      startElapsedTimer()
      setPhase('polling')

      // First poll after 1 s
      pollTimerRef.current = setTimeout(() => doPoll(rid), 1_000)
    } catch (submitErr) {
      stopElapsedTimer()
      setError(parseApiError(submitErr))
      setPhase('error')
    }
  }, [doPoll, startElapsedTimer, stopElapsedTimer])

  // ── View a report from history ──────────────────────────────────────────────
  const viewReport = useCallback(async (rid: string, knownStatus?: RunStatus) => {
    if (knownStatus && knownStatus !== 'done') return  // can't view non-done run

    setRunId(rid)
    setReport(null)
    setError(null)
    setPhase('loading_report')

    try {
      const { data } = await pipelineApi.getReport(rid)
      setReport(data)
      setPhase('done')
    } catch (err) {
      setError(parseApiError(err))
      setPhase('error')
    }
  }, [])

  // ── Dismiss: return to idle ─────────────────────────────────────────────────
  const dismiss = useCallback(() => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
    stopElapsedTimer()
    activeRunIdRef.current = null
    setPhase('idle')
    setRunId(null)
    setReport(null)
    setStatusData(null)
    setError(null)
    setElapsedMs(0)
  }, [stopElapsedTimer])

  return {
    phase,
    runId,
    statusData,
    report,
    error,
    elapsedMs,
    history,
    historyLoading,
    submit,
    viewReport,
    dismiss,
    loadHistory,
  }
}
