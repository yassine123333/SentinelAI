/** Auth-related TypeScript types matching the backend Pydantic models */

export interface User {
  _id: string
  fullname: string
  email: string
  role: 'analyst' | 'admin'
  is_verified: boolean
  ticker_preferences: string[]
  avatar_id?: number
  created_at: string
  last_login?: string
}

export interface UpdateProfileRequest {
  fullname?: string
  avatar_id?: number
  ticker_preferences?: string[]
}

export interface ChangePasswordRequest {
  current_password: string
  new_password: string
  confirm_new_password: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  fullname: string
  email: string
  password: string
  confirm_password: string
  ticker_preferences?: string[]
}

export interface VerifyEmailRequest {
  token: string
}

export interface ResendVerificationRequest {
  email: string
}

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

export interface RegisterResponse {
  message: string
  user_id: string
}

export interface VerifyEmailResponse {
  message: string
}

export interface ApiError {
  detail: string | ValidationError[]
}

export interface ValidationError {
  loc: (string | number)[]
  msg: string
  type: string
}

export type Theme = 'dark'

/** Pending verification state stored after registration */
export interface PendingVerification {
  email: string
  userId: string
}
