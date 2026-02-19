import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  type ReactNode,
} from 'react'
import { authApi, tokenStore } from '@/services/api'
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

// ── Provider ───────────────────────────────────────────────────────────────────
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(authReducer, {
    user: null,
    isAuthenticated: false,
    isLoading: true,
    pendingVerification: null,
  })

  // On mount: attempt silent refresh only when the user opted into being remembered.
  // Without the flag we skip the cookie entirely — forces a new login each session.
  // Uses a module-level promise so StrictMode's double-mount shares one request.
  useEffect(() => {
    let cancelled = false

    const tryRefresh = async () => {
      if (!rememberMeStore.get()) {
        dispatch({ type: 'LOGOUT' })
        return
      }

      const data = await getOrStartRefresh()
      if (cancelled) return

      if (!data) {
        dispatch({ type: 'LOGOUT' })
        return
      }

      tokenStore.set(data.access_token)
      try {
        const { data: user } = await authApi.me()
        if (!cancelled) dispatch({ type: 'LOGIN_SUCCESS', user })
      } catch {
        if (!cancelled) dispatch({ type: 'LOGOUT' })
      }
    }

    tryRefresh()
    return () => { cancelled = true }
  }, [])

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
