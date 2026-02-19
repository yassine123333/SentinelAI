/**
 * Axios API client for SentinelAI backend.
 *
 * Security notes:
 *  - Access token stored only in memory (never localStorage) to prevent XSS theft.
 *  - Refresh token lives in HttpOnly cookie managed by the browser.
 *  - Interceptor transparently rotates the access token on 401.
 *  - All requests go through the Vite proxy → backend (avoids CORS in dev).
 */
import axios, {
  type AxiosInstance,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import type {
  ChangePasswordRequest,
  LoginRequest,
  LoginResponse,
  RegisterRequest,
  RegisterResponse,
  UpdateProfileRequest,
  User,
  VerifyEmailResponse,
} from '@/types/auth'
import type {
  PipelineReport,
  PipelineStatus,
  QueryRequest,
  QueryResponse,
  UserRunItem,
} from '@/types/pipeline'

const BASE_URL = '/api/v1'

// ── In-memory token store ─────────────────────────────────────────────────────
// Never stored in localStorage/sessionStorage — XSS-safe.
let _accessToken: string | null = null

export const tokenStore = {
  get: () => _accessToken,
  set: (token: string | null) => { _accessToken = token },
  clear: () => { _accessToken = null },
}

// ── One-shot header injector ──────────────────────────────────────────────────
// Allows security hooks (reCAPTCHA, bot-detection) to inject headers for the
// next request without changing AuthContext or authApi function signatures.
// Headers are consumed once and then cleared.
let _pendingHeaders: Record<string, string> = {}

export const pendingHeaders = {
  set: (headers: Record<string, string>) => { _pendingHeaders = { ..._pendingHeaders, ...headers } },
  consume: (): Record<string, string> => {
    const h = _pendingHeaders
    _pendingHeaders = {}
    return h
  },
}

// ── Axios instance ────────────────────────────────────────────────────────────
const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,   // Required: sends HttpOnly refresh_token cookie
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
})

// ── Request interceptor: attach Bearer token + pending security headers ────────
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.get()
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  // Inject any pending security headers (reCAPTCHA token, risk score)
  const extra = pendingHeaders.consume()
  if (config.headers && Object.keys(extra).length > 0) {
    Object.entries(extra).forEach(([k, v]) => {
      config.headers.set(k, v)
    })
  }
  return config
})

// ── Response interceptor: silent token refresh on 401 ────────────────────────
let _refreshing = false
let _refreshQueue: Array<{
  resolve: (token: string) => void
  reject: (err: unknown) => void
}> = []

api.interceptors.response.use(
  (res: AxiosResponse) => res,
  async (err) => {
    const original = err.config as AxiosRequestConfig & { _retry?: boolean }

    // Only retry once; skip if:
    //  - the failing request IS /refresh (would loop)
    //  - the request had NO Authorization header, meaning it was unauthenticated
    //    (e.g. /auth/login, /auth/register). Those legitimately return 401 for bad
    //    credentials — retrying them triggers a cascade refresh + hard reload.
    const hadBearerToken = !!(original.headers?.['Authorization'])
    if (
      err.response?.status === 401 &&
      !original._retry &&
      !original.url?.includes('/auth/refresh') &&
      hadBearerToken
    ) {
      original._retry = true

      if (_refreshing) {
        // Queue this request until the refresh completes
        return new Promise((resolve, reject) => {
          _refreshQueue.push({ resolve, reject })
        }).then((token) => {
          if (original.headers) {
            original.headers['Authorization'] = `Bearer ${token}`
          }
          return api(original)
        })
      }

      _refreshing = true

      try {
        const { data } = await api.post<{ access_token: string; token_type: string; expires_in: number }>(
          '/auth/refresh',
        )
        tokenStore.set(data.access_token)

        _refreshQueue.forEach(({ resolve }) => resolve(data.access_token))
        _refreshQueue = []

        if (original.headers) {
          original.headers['Authorization'] = `Bearer ${data.access_token}`
        }
        return api(original)
      } catch (refreshErr) {
        tokenStore.clear()
        _refreshQueue.forEach(({ reject }) => reject(refreshErr))
        _refreshQueue = []
        // Redirect to login — safe because we're not inside a component
        window.location.href = '/login'
        return Promise.reject(refreshErr)
      } finally {
        _refreshing = false
      }
    }

    return Promise.reject(err)
  },
)

// ── Auth endpoints ────────────────────────────────────────────────────────────

export const authApi = {
  /**
   * Register a new user. Returns user_id on success.
   * Does NOT issue tokens — email must be verified first.
   */
  register: (data: RegisterRequest) =>
    api.post<RegisterResponse>('/auth/register', data),

  /**
   * Authenticate with email + password.
   * Access token returned in body; refresh token set as HttpOnly cookie.
   */
  login: (data: LoginRequest) =>
    api.post<LoginResponse>('/auth/login', data),

  /**
   * Verify email using the raw token from the verification email.
   */
  verifyEmail: (token: string) =>
    api.post<VerifyEmailResponse>('/auth/verify-email', { token }),

  /**
   * Re-send the verification email.
   * Always returns 200 (prevents user enumeration).
   */
  resendVerification: (email: string) =>
    api.post<{ message: string }>('/auth/resend-verification', { email }),

  /**
   * Silently rotate the access token using the HttpOnly refresh cookie.
   */
  refresh: () =>
    api.post<{ access_token: string; token_type: string; expires_in: number }>('/auth/refresh'),

  /**
   * Revoke the refresh token and clear the cookie.
   */
  logout: () =>
    api.post<{ message: string }>('/auth/logout'),

  /**
   * Fetch the current user's profile (requires valid access token).
   */
  me: () =>
    api.get<User>('/auth/me'),

  /**
   * Partially update the authenticated user's profile.
   * Only fields that are present in the payload are written.
   */
  updateProfile: (data: UpdateProfileRequest) =>
    api.patch<User>('/auth/me', data),

  /**
   * Change the authenticated user's password.
   * Requires the current password for verification.
   */
  changePassword: (data: ChangePasswordRequest) =>
    api.post<{ message: string }>('/auth/me/change-password', data),
}

// ── Pipeline endpoints ────────────────────────────────────────────────────────

export const pipelineApi = {
  /**
   * Submit a new analysis query. Returns run_id immediately (202 Accepted).
   * The pipeline executes asynchronously — poll getStatus() for progress.
   */
  submit: (body: QueryRequest) =>
    api.post<QueryResponse>('/query', body),

  /**
   * Lightweight poll: returns run status without the full report payload.
   */
  getStatus: (runId: string) =>
    api.get<PipelineStatus>(`/pipeline/${runId}/status`),

  /**
   * Fetch the completed report. Returns 202 if still in progress.
   */
  getReport: (runId: string) =>
    api.get<PipelineReport>(`/report/${runId}`),

  /**
   * Download PDF bytes for a completed run.
   * Returns the raw ArrayBuffer so the caller can build a Blob URL.
   */
  downloadPdf: (runId: string) =>
    api.get<ArrayBuffer>(`/report/${runId}/pdf`, { responseType: 'arraybuffer' }),

  /**
   * List the authenticated user's recent pipeline runs (newest first).
   */
  getHistory: (limit = 20, skip = 0) =>
    api.get<UserRunItem[]>('/history', { params: { limit, skip } }),
}

export default api
