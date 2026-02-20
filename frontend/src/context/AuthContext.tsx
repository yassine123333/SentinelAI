import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { Turnstile } from '@marsidev/react-turnstile'
import { authApi, tokenStore, pendingHeaders } from '@/services/api'
import { useTurnstile } from '@/hooks/useTurnstile'
import { useRecaptcha } from '@/hooks/useRecaptcha'
import type {
  ChangePasswordRequest,
  LoginRequest,
  PendingVerification,
  RegisterRequest,
  UpdateProfileRequest,
  User,
} from '@/types/auth'
import axios from 'axios'

// ── State shape ────────────────────────────────────────────────────────────────
interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  /** Set right after registration until email is verified */
  pendingVerification: PendingVerification | null
}

type AuthAction =
  | { type: 'LOADING' }
  | { type: 'LOGIN_SUCCESS'; user: User }
  | { type: 'SET_USER'; user: User }
  | { type: 'LOGOUT' }
  | { type: 'SET_PENDING'; pending: PendingVerification }
  | { type: 'CLEAR_PENDING' }
  | { type: 'VERIFIED' }

function authReducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case 'LOADING':
      return { ...state, isLoading: true }
    case 'LOGIN_SUCCESS':
      return { ...state, user: action.user, isAuthenticated: true, isLoading: false, pendingVerification: null }
    case 'SET_USER':
      return { ...state, user: action.user }
    case 'LOGOUT':
      return { user: null, isAuthenticated: false, isLoading: false, pendingVerification: null }
    case 'SET_PENDING':
      return { ...state, isLoading: false, pendingVerification: action.pending }
    case 'CLEAR_PENDING':
      return { ...state, pendingVerification: null }
    case 'VERIFIED':
      return { ...state, pendingVerification: null, isLoading: false }
    default:
      return state
  }
}

// ── Remember-me store ───────────────────────────────────────────────────────────
// Stored in localStorage so it survives browser restarts.
// Controls whether the mount-time refresh is attempted.
const REMEMBER_KEY = 'sentinel-remember'

const rememberMeStore = {
  get: (): boolean => {
    try { return localStorage.getItem(REMEMBER_KEY) === 'true' } catch { return false }
  },
  set: (val: boolean): void => {
    try { val ? localStorage.setItem(REMEMBER_KEY, 'true') : localStorage.removeItem(REMEMBER_KEY) } catch {}
  },
  clear: (): void => {
    try { localStorage.removeItem(REMEMBER_KEY) } catch {}
  },
}

// ── Context ────────────────────────────────────────────────────────────────────
interface AuthContextValue extends AuthState {
  login: (data: LoginRequest, rememberMe?: boolean) => Promise<void>
  register: (data: RegisterRequest) => Promise<void>
  logout: () => Promise<void>
  verifyEmail: (token: string) => Promise<void>
  resendVerification: (email: string) => Promise<void>
  clearPending: () => void
  updateProfile: (data: UpdateProfileRequest) => Promise<void>
  changePassword: (data: ChangePasswordRequest) => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

// Module-level singleton: prevents StrictMode's double-mount from firing two
// concurrent refresh requests with the same JTI (which would cause a race condition
// where both succeed and create duplicate tokens in the database).
let _refreshPromise: Promise<{ access_token: string } | null> | null = null

function getOrStartRefresh() {
  if (_refreshPromise) return _refreshPromise
  _refreshPromise = authApi
    .refresh()
    .then((res) => res.data)
    .catch(() => null)
    .finally(() => { _refreshPromise = null })
  return _refreshPromise
}

// ── Security Gate overlay ──────────────────────────────────────────────────────
// Shown when auto-login is pending and Cloudflare + reCAPTCHA verification is in
// progress. For most real users the Turnstile managed challenge auto-passes in
// under a second so the overlay is barely visible.
const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY as string

interface SecurityGateProps {
  onTurnstileSuccess: (token: string) => void
  onTurnstileError: () => void
  onTurnstileExpire: () => void
  widgetRef: React.RefObject<import('@marsidev/react-turnstile').TurnstileInstance | undefined>
}

function SecurityGateOverlay({ onTurnstileSuccess, onTurnstileError, onTurnstileExpire, widgetRef }: SecurityGateProps) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '1.5rem',
        background: '#060b18',
      }}
    >
      {/* Sentinel logo mark */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
          <path d="M14 2L3 8v12l11 6 11-6V8L14 2z" stroke="#00e87b" strokeWidth="1.5" fill="none" />
          <path d="M14 7l-7 4v6l7 4 7-4v-6l-7-4z" fill="#00e87b" fillOpacity="0.15" stroke="#00e87b" strokeWidth="1" />
        </svg>
        <span style={{ fontFamily: 'DM Serif Display, serif', fontStyle: 'italic', fontSize: '1.25rem', color: '#eef2ff', letterSpacing: '-0.01em' }}>
          SentinelAI
        </span>
      </div>

      {/* Status */}
      <div style={{ textAlign: 'center' }}>
        <p style={{ fontFamily: 'DM Sans, sans-serif', fontSize: '0.875rem', color: '#8b9dc3', margin: 0 }}>
          Verifying session security…
        </p>
      </div>

      {/* Turnstile widget — visible so interactive challenges can be solved */}
      <div style={{ minHeight: 65 }}>
        <Turnstile
          ref={widgetRef}
          siteKey={TURNSTILE_SITE_KEY}
          onSuccess={onTurnstileSuccess}
          onError={onTurnstileError}
          onExpire={onTurnstileExpire}
          options={{ theme: 'dark', size: 'normal' }}
        />
      </div>

      {/* Spinner */}
      <div style={{
        width: 20, height: 20,
        border: '2px solid rgba(0,232,123,0.2)',
        borderTop: '2px solid #00e87b',
        borderRadius: '50%',
        animation: 'spin 0.8s linear infinite',
      }} />

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}

// ── Provider ───────────────────────────────────────────────────────────────────
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(authReducer, {
    user: null,
    isAuthenticated: false,
    isLoading: true,
    pendingVerification: null,
  })

  // showSecurityGate is true only when the user opted into "remember me" and
  // we need to verify Turnstile + reCAPTCHA before the silent token refresh.
  const [showSecurityGate, setShowSecurityGate] = useState(() => rememberMeStore.get())

  // Guard against double-execution in React StrictMode / multiple re-renders
  const autoLoginAttempted = useRef(false)

  const turnstile   = useTurnstile()
  const { execute: executeRecaptcha } = useRecaptcha()

  // ── Case 1: no rememberMe → immediately settle to logged-out ─────────────
  useEffect(() => {
    if (!rememberMeStore.get()) {
      dispatch({ type: 'LOGOUT' })
    }
  }, [])

  // ── Case 2: rememberMe=true → wait for Turnstile + reCAPTCHA, then refresh ─
  // The effect fires whenever Turnstile verification state changes.
  // `isTurnstileErrored` lets us fail open if Cloudflare's widget throws.
  const [isTurnstileErrored, setIsTurnstileErrored] = useState(false)

  const handleTurnstileError = useCallback(() => {
    turnstile.onError()
    setIsTurnstileErrored(true)
  }, [turnstile])

  // Refs to read volatile values inside the effect without adding them to deps.
  // executeRecaptcha gets a new reference every time useRecaptcha's isReady changes,
  // and turnstile.token changes after Turnstile completes — both would re-trigger the
  // effect and cause the cleanup's `cancelled = true` to fire mid-execution.
  const executeRecaptchaRef = useRef(executeRecaptcha)
  executeRecaptchaRef.current = executeRecaptcha

  const turnstileTokenRef = useRef(turnstile.token)
  turnstileTokenRef.current = turnstile.token

  // Prevents a second dispatch if, in StrictMode, the effect somehow runs twice
  // after autoLoginAttempted already guarded the outer gate.
  const authDispatched = useRef(false)

  useEffect(() => {
    if (!showSecurityGate) return
    // Wait until Turnstile either verified (real user) or errored (network/config issue).
    // Either outcome allows us to proceed — Turnstile errors fail open.
    if (!turnstile.isVerified && !isTurnstileErrored) return
    // Prevent double-execution
    if (autoLoginAttempted.current) return
    autoLoginAttempted.current = true

    const tryRefresh = async () => {
      // ① reCAPTCHA v3 — invisible, always runs; fails open on error.
      //    Read via ref so a reference change (isReady flip) doesn't re-trigger this effect.
      const recaptchaToken = await executeRecaptchaRef.current('login')
      if (recaptchaToken) {
        pendingHeaders.set({ 'X-Recaptcha-Token': recaptchaToken })
      }

      // ② Turnstile — inject token if verified; backend reads X-CF-Turnstile.
      //    Read via ref for the same reason.
      if (turnstileTokenRef.current) {
        pendingHeaders.set({ 'X-CF-Turnstile': turnstileTokenRef.current })
      }

      // ③ Silent refresh using the HttpOnly cookie
      const data = await getOrStartRefresh()

      // Guard against a theoretical double-dispatch (StrictMode safety net).
      if (authDispatched.current) return
      authDispatched.current = true

      if (!data) {
        // Refresh failed — session expired or cookie gone.
        // Clear rememberMe so the security gate doesn't loop on next page load.
        rememberMeStore.clear()
        // Batch dispatch + setShowSecurityGate into one React render so there is
        // no intermediate frame where the overlay is gone but isAuthenticated is
        // still false (which briefly shows a blank screen before navigate fires).
        dispatch({ type: 'LOGOUT' })
        setShowSecurityGate(false)
        return
      }

      tokenStore.set(data.access_token)
      try {
        const { data: user } = await authApi.me()
        // Batch: hide overlay and set authenticated state in the same render.
        dispatch({ type: 'LOGIN_SUCCESS', user })
        setShowSecurityGate(false)
      } catch {
        rememberMeStore.clear()
        dispatch({ type: 'LOGOUT' })
        setShowSecurityGate(false)
      }
    }

    tryRefresh()
    // No cleanup / cancelled flag: AuthProvider lives for the entire app lifetime,
    // so the effect never truly unmounts. The autoLoginAttempted + authDispatched
    // refs handle idempotency instead.
  }, [showSecurityGate, turnstile.isVerified, isTurnstileErrored])
  // executeRecaptcha and turnstile.token are intentionally read via refs above
  // to avoid re-triggering this effect when those values change mid-execution.

  // ── Explicit login ────────────────────────────────────────────────────────
  const login = useCallback(async (data: LoginRequest, rememberMe = false) => {
    const { data: res } = await authApi.login(data)
    rememberMeStore.set(rememberMe)
    tokenStore.set(res.access_token)
    dispatch({ type: 'LOGIN_SUCCESS', user: res.user })
  }, [])

  const register = useCallback(async (data: RegisterRequest) => {
    const { data: res } = await authApi.register(data)
    dispatch({
      type: 'SET_PENDING',
      pending: { email: data.email, userId: res.user_id },
    })
  }, [])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // Best-effort — clear client-side state regardless
    }
    tokenStore.clear()
    rememberMeStore.clear()
    dispatch({ type: 'LOGOUT' })
  }, [])

  const verifyEmail = useCallback(async (token: string) => {
    dispatch({ type: 'LOADING' })
    await authApi.verifyEmail(token)
    dispatch({ type: 'VERIFIED' })
  }, [])

  const resendVerification = useCallback(async (email: string) => {
    await authApi.resendVerification(email)
  }, [])

  const clearPending = useCallback(() => {
    dispatch({ type: 'CLEAR_PENDING' })
  }, [])

  const updateProfile = useCallback(async (data: UpdateProfileRequest) => {
    const { data: user } = await authApi.updateProfile(data)
    dispatch({ type: 'SET_USER', user })
  }, [])

  const changePassword = useCallback(async (data: ChangePasswordRequest) => {
    await authApi.changePassword(data)
  }, [])

  return (
    <AuthContext.Provider
      value={{ ...state, login, register, logout, verifyEmail, resendVerification, clearPending, updateProfile, changePassword }}
    >
      {/* Security gate: shown while Cloudflare Turnstile + reCAPTCHA are being
          verified before the silent token refresh. Hidden once verification
          completes (pass or fail-open). */}
      {showSecurityGate && (
        <SecurityGateOverlay
          widgetRef={turnstile.widgetRef}
          onTurnstileSuccess={turnstile.onSuccess}
          onTurnstileError={handleTurnstileError}
          onTurnstileExpire={turnstile.onExpire}
        />
      )}
      {children}
    </AuthContext.Provider>
  )
}

// ── Hook ───────────────────────────────────────────────────────────────────────
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within <AuthProvider>')
  return ctx
}

// ── Error parsing helper (exported for forms) ──────────────────────────────────
export function parseApiError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status
    const detail = err.response?.data?.detail

    // Prefer explicit detail message from the backend
    if (typeof detail === 'string' && detail.trim()) return detail
    if (Array.isArray(detail) && detail.length > 0) {
      return detail
        .map((e: { msg?: string; loc?: string[] }) => {
          const field = e.loc?.slice(-1)[0]
          return field && field !== 'body' ? `${field}: ${e.msg}` : e.msg
        })
        .filter(Boolean)
        .join(' · ')
    }

    // Status-code fallbacks when backend sends no detail
    switch (status) {
      case 400: return 'Invalid request. The link may have expired — please request a new one.'
      case 401: return 'Invalid email or password.'
      case 403: return 'Access denied. Your account may be suspended.'
      case 404: return 'Account not found.'
      case 409: return 'An account with this email already exists.'
      case 422: return 'Validation error. Please check your input and try again.'
      case 429: return 'Too many attempts. Please wait a moment before trying again.'
      case 500:
      case 502:
      case 503: return 'Server error. Please try again in a few moments.'
    }

    if (err.code === 'ECONNABORTED') return 'Request timed out. Please check your connection.'
    if (err.message === 'Network Error') return 'Cannot reach the server. Please check your connection.'
  }
  return 'An unexpected error occurred. Please try again.'
}
