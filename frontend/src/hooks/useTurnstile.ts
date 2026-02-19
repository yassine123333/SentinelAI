/**
 * useTurnstile — Cloudflare Turnstile (managed checkbox) integration.
 *
 * Strategy:
 *  - Widget renders immediately on page load (visible checkbox, no invisible risk).
 *  - Token is valid for 5 minutes server-side; we enforce a stricter 15-minute
 *    client-side inactivity window — any user who walks away and comes back must
 *    re-complete the challenge before submitting (defeats session-hijack replay).
 *  - Activity tracking resets the idle timer on every meaningful interaction
 *    (mouse, keyboard, scroll, touch) without causing re-renders.
 *  - onError / onExpire both clear the token so the form blocks submission
 *    until the user completes a fresh challenge.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { TurnstileInstance } from '@marsidev/react-turnstile'

const INACTIVITY_MS = 15 * 60 * 1000 // 15 minutes

export interface TurnstileControls {
  /** Valid token returned by Cloudflare after a successful challenge. */
  token: string | null
  /** True once the user has passed the challenge and token is fresh. */
  isVerified: boolean
  /** Ref passed to the <Turnstile> component to allow programmatic resets. */
  widgetRef: React.RefObject<TurnstileInstance | undefined>
  /** Called by <Turnstile onSuccess>. */
  onSuccess: (token: string) => void
  /** Called by <Turnstile onError> — clears token so form is blocked. */
  onError: () => void
  /** Called by <Turnstile onExpire> — token expired, must re-challenge. */
  onExpire: () => void
}

export function useTurnstile(): TurnstileControls {
  const [token, setToken]         = useState<string | null>(null)
  const [isVerified, setIsVerified] = useState(false)
  const widgetRef                 = useRef<TurnstileInstance | undefined>(undefined)
  const timerRef                  = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Inactivity reset ───────────────────────────────────────────────────────
  const resetWidget = useCallback(() => {
    setToken(null)
    setIsVerified(false)
    widgetRef.current?.reset()
  }, [])

  const restartTimer = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(resetWidget, INACTIVITY_MS)
  }, [resetWidget])

  useEffect(() => {
    const EVENTS = ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'] as const
    const handler = () => restartTimer()

    EVENTS.forEach(ev => document.addEventListener(ev, handler, { passive: true }))
    restartTimer() // Start the clock immediately on mount

    return () => {
      EVENTS.forEach(ev => document.removeEventListener(ev, handler))
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [restartTimer])

  // ── Widget callbacks ───────────────────────────────────────────────────────
  const onSuccess = useCallback((t: string) => {
    setToken(t)
    setIsVerified(true)
  }, [])

  const onError = useCallback(() => {
    setToken(null)
    setIsVerified(false)
  }, [])

  const onExpire = useCallback(() => {
    setToken(null)
    setIsVerified(false)
  }, [])

  return { token, isVerified, widgetRef, onSuccess, onError, onExpire }
}
