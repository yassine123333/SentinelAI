/**
 * useRecaptcha — reCAPTCHA v3 (invisible) integration.
 *
 * Strategy (mirrors SentinelAI presentation defense model):
 *  - Script is loaded LAZILY on first form interaction, not at page load.
 *    This avoids fingerprinting real users before they've opted into the form.
 *  - execute() always resolves — if reCAPTCHA is blocked (ad-blocker, network
 *    error), it returns null and the caller FAILS OPEN to prevent locking out
 *    legitimate users behind broken third-party scripts.
 *  - The token is sent to the backend via X-Recaptcha-Token header.
 *    Backend calls Google's siteverify API and gets a score (0.0–1.0).
 *  - The default badge is hidden via CSS; required attribution is displayed
 *    in the SecurityBadge component (allowed by Google TOS).
 */

import { useCallback, useEffect, useRef, useState } from 'react'

const SITE_KEY = '6LdI9W8sAAAAAHAqrEoAW-r1NGdL26alrMn7_uG9'
const SCRIPT_ID = 'recaptcha-v3-script'
const SCRIPT_SRC = `https://www.google.com/recaptcha/api.js?render=${SITE_KEY}`

// ── Global type augmentation ───────────────────────────────────────────────────
declare global {
  interface Window {
    grecaptcha?: {
      ready: (cb: () => void) => void
      execute: (siteKey: string, opts: { action: string }) => Promise<string>
    }
  }
}

// ── Module-level singleton: one load promise shared across all hook instances ──
let _loadPromise: Promise<void> | null = null

function loadScript(): Promise<void> {
  if (_loadPromise) return _loadPromise

  _loadPromise = new Promise<void>((resolve, reject) => {
    // Already injected by a previous render (e.g. HMR)
    if (document.getElementById(SCRIPT_ID)) {
      window.grecaptcha?.ready(resolve) ?? resolve()
      return
    }

    const script = document.createElement('script')
    script.id   = SCRIPT_ID
    script.src  = SCRIPT_SRC
    script.async = true
    script.defer = true

    script.onload = () => {
      window.grecaptcha?.ready(resolve) ?? resolve()
    }
    script.onerror = () => {
      _loadPromise = null // Allow retry on next call
      reject(new Error('reCAPTCHA script failed to load'))
    }

    document.head.appendChild(script)
  })

  return _loadPromise
}

// ── Hook ──────────────────────────────────────────────────────────────────────
export type RecaptchaAction = 'login' | 'register' | 'verify_email' | 'resend'

export interface RecaptchaControls {
  /** True once the reCAPTCHA script is ready to execute. */
  isReady: boolean
  /** Trigger lazy script loading — call on first user interaction with form. */
  load: () => void
  /**
   * Execute reCAPTCHA for the given action.
   * Returns a token string on success, or null if unavailable (fail-open).
   * Always awaitable — never throws.
   */
  execute: (action: RecaptchaAction) => Promise<string | null>
  /**
   * Injects the reCAPTCHA token into an axios-style headers object.
   * Pass the result to api.ts interceptors or individual request configs.
   */
  injectHeader: (action: RecaptchaAction) => Promise<Record<string, string>>
}

export function useRecaptcha(): RecaptchaControls {
  const [isReady, setIsReady] = useState(false)
  const loadCalled = useRef(false)

  // Warm up: if script was loaded by a prior instance, sync the ready state
  useEffect(() => {
    if (window.grecaptcha) {
      window.grecaptcha.ready(() => setIsReady(true))
    }
  }, [])

  const load = useCallback(() => {
    if (loadCalled.current) return
    loadCalled.current = true

    loadScript()
      .then(() => setIsReady(true))
      .catch(() => {
        // Script blocked or failed — degrade gracefully
        setIsReady(false)
      })
  }, [])

  const execute = useCallback(async (action: RecaptchaAction): Promise<string | null> => {
    // If not yet loaded, attempt to load now (synchronous submit path)
    if (!isReady) {
      try {
        await loadScript()
        setIsReady(true)
      } catch {
        return null // reCAPTCHA unavailable — fail open
      }
    }

    try {
      const token = await window.grecaptcha!.execute(SITE_KEY, { action })
      return token
    } catch {
      return null // Execution error — fail open
    }
  }, [isReady])

  const injectHeader = useCallback(
    async (action: RecaptchaAction): Promise<Record<string, string>> => {
      const token = await execute(action)
      return token ? { 'X-Recaptcha-Token': token } : {}
    },
    [execute],
  )

  return { isReady, load, execute, injectHeader }
}
