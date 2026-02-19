import { useEffect, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import { authApi } from '@/services/api'
import Logo from '@/components/ui/Logo'
import { cn } from '@/lib/utils'

type VerifyState = 'verifying' | 'success' | 'error'

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [state, setState] = useState<VerifyState>('verifying')
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    const token = searchParams.get('token')

    if (!token) {
      setState('error')
      setErrorMsg('No verification token found in the link. Please use the button from your email.')
      return
    }

    authApi
      .verifyEmail(token)
      .then(() => {
        setState('success')
        setTimeout(() => {
          navigate('/login', { state: { message: 'Email verified! You can now log in.' } })
        }, 2500)
      })
      .catch((err) => {
        setState('error')
        const detail = err?.response?.data?.detail
        setErrorMsg(
          typeof detail === 'string'
            ? detail
            : 'Verification link is invalid or has expired. Please request a new one.',
        )
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className={cn('min-h-dvh flex flex-col', 'bg-dark-bg bg-grid-dark')}>
      {/* Top bar */}
      <div className="flex items-center justify-between px-8 py-5 border-b border-dark-border">
        <Logo size="sm" />
      </div>

      {/* Content */}
      <div className="flex flex-1 items-center justify-center p-6">
        <motion.div
          className="w-full max-w-sm"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        >
          <div className={cn('rounded-xl text-center', 'bg-dark-card border border-dark-border shadow-card-dark')}>
            <div className="h-[2px] rounded-t-xl bg-gradient-to-r from-transparent via-sentinel-green-neon/50 to-transparent" />

            <div className="px-8 py-10 flex flex-col items-center gap-6">
              {/* Icon */}
              {state === 'verifying' && (
                <div className="w-16 h-16 rounded-full flex items-center justify-center bg-dark-elevated border border-dark-border">
                  <Loader2 size={28} className="animate-spin text-sentinel-green-neon" />
                </div>
              )}
              {state === 'success' && (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 20 }}
                  className="w-16 h-16 rounded-full flex items-center justify-center bg-sentinel-green-neon/10"
                >
                  <CheckCircle2 size={32} className="text-sentinel-green-neon" />
                </motion.div>
              )}
              {state === 'error' && (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 20 }}
                  className="w-16 h-16 rounded-full flex items-center justify-center bg-sentinel-red-neon/10"
                >
                  <XCircle size={32} className="text-sentinel-red-neon" />
                </motion.div>
              )}

              {/* Text */}
              <div className="flex flex-col gap-2">
                <h1 className="font-display italic text-2xl text-dark-text-primary">
                  {state === 'verifying' && 'Verifying your email…'}
                  {state === 'success' && 'Email verified!'}
                  {state === 'error' && 'Verification failed.'}
                </h1>
                <p className="font-sans text-sm text-dark-text-secondary leading-relaxed">
                  {state === 'verifying' && 'Please wait a moment.'}
                  {state === 'success' && 'Your account is active. Redirecting to login…'}
                  {state === 'error' && errorMsg}
                </p>
              </div>

              {/* Actions */}
              {state === 'error' && (
                <div className="flex flex-col items-center gap-2 pt-2 border-t border-dark-border w-full">
                  <button
                    onClick={() => navigate('/signup')}
                    className="font-sans text-sm text-sentinel-green-neon hover:underline transition-colors"
                  >
                    Request a new verification email
                  </button>
                  <button
                    onClick={() => navigate('/login')}
                    className="font-sans text-sm text-dark-text-muted hover:text-dark-text-secondary transition-colors"
                  >
                    Back to login
                  </button>
                </div>
              )}
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  )
}
