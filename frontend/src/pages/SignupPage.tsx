import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { useAuth } from '@/context/AuthContext'
import MarketPanel from '@/components/auth/MarketPanel'
import SignupForm from '@/components/auth/SignupForm'
import EmailVerificationModal from '@/components/auth/EmailVerificationModal'
import Logo from '@/components/ui/Logo'
import { cn } from '@/lib/utils'

export default function SignupPage() {
  const navigate = useNavigate()
  const { isAuthenticated, isLoading, pendingVerification, clearPending } = useAuth()

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      navigate('/dashboard', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  if (isLoading) {
    return (
      <div className="min-h-dvh bg-dark-surface flex items-center justify-center">
        <div className="btn-spinner" style={{ width: 24, height: 24 }} />
      </div>
    )
  }

  const handleVerificationSuccess = () => {
    clearPending()
    navigate('/login', {
      state: { message: 'Email verified! You can now log in.' },
    })
  }

  return (
    <div className="auth-split min-h-dvh">
      <MarketPanel />

      <div className={cn('relative flex flex-col min-h-dvh', 'bg-dark-surface')}>
        {/* Top bar */}
        <div className="flex items-center justify-between px-8 py-5 border-b border-dark-border">
          <div className="lg:hidden">
            <Logo size="sm" />
          </div>
          <div className="ml-auto" />
        </div>

        {/* Form area */}
        <div className="flex flex-1 items-center justify-center px-6 py-12">
          <motion.div
            className="w-full max-w-md"
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
          >
            <AnimatePresence mode="wait">
              <motion.div
                key="form-card"
                initial={{ opacity: 0, x: 0 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -24 }}
                className={cn('rounded-xl', 'bg-dark-card border border-dark-border shadow-card-dark')}
              >
                <div className="h-[2px] rounded-t-xl bg-gradient-to-r from-transparent via-sentinel-green-neon/50 to-transparent" />

                <div className="px-8 py-8">
                  <div className="mb-7">
                    <h1 className="font-display italic text-3xl text-dark-text-primary leading-tight mb-2">
                      Create your account.
                    </h1>
                    <p className="font-sans text-sm text-dark-text-secondary">
                      Join SentinelAI and start your first intelligence analysis in minutes.
                    </p>
                  </div>

                  <SignupForm onSuccess={() => {}} />
                </div>
              </motion.div>
            </AnimatePresence>

            <p className="mt-5 text-center font-sans text-xs text-dark-text-muted">
              End-to-end encrypted · bcrypt · JWT
            </p>
          </motion.div>
        </div>

        {/* Bottom status bar */}
        <div className="px-8 py-4 border-t border-dark-border">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-sentinel-green-neon animate-pulse-dot" />
            <span className="font-sans text-xs text-dark-text-muted">
              Registration open
            </span>
          </div>
        </div>
      </div>

      <AnimatePresence>
        {pendingVerification && (
          <EmailVerificationModal
            email={pendingVerification.email}
            onSuccess={handleVerificationSuccess}
            onClose={() => { clearPending() }}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
