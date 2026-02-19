import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Copy, Mail, RefreshCw, CheckCircle2, X, AlertCircle } from 'lucide-react'
import { useAuth, parseApiError } from '@/context/AuthContext'
import Button from '@/components/ui/Button'
import { cn } from '@/lib/utils'

interface EmailVerificationModalProps {
  email: string
  onSuccess: () => void
  onClose?: () => void
}

const RESEND_COOLDOWN = 60 // seconds

export default function EmailVerificationModal({
  email,
  onSuccess,
  onClose,
}: EmailVerificationModalProps) {
  const { verifyEmail, resendVerification } = useAuth()

  const [token, setToken] = useState('')
  const [error, setError] = useState('')
  const [isVerifying, setIsVerifying] = useState(false)
  const [isResending, setIsResending] = useState(false)
  const [resendCooldown, setResendCooldown] = useState(0)
  const [verified, setVerified] = useState(false)
  const [pasteSuccess, setPasteSuccess] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Resend countdown timer
  useEffect(() => {
    if (resendCooldown <= 0) return
    const t = setInterval(() => setResendCooldown((c) => c - 1), 1000)
    return () => clearInterval(t)
  }, [resendCooldown])

  const handleVerify = async () => {
    const trimmed = token.trim()
    if (!trimmed) {
      setError('Please paste your verification token.')
      return
    }
    if (trimmed.length < 32) {
      setError('Token appears too short. Please copy the full token from your email.')
      return
    }

    setError('')
    setIsVerifying(true)
    try {
      await verifyEmail(trimmed)
      setVerified(true)
      setTimeout(onSuccess, 1800)
    } catch (err) {
      setError(parseApiError(err))
    } finally {
      setIsVerifying(false)
    }
  }

  const handleResend = async () => {
    if (resendCooldown > 0 || isResending) return
    setIsResending(true)
    setError('')
    try {
      await resendVerification(email)
      setResendCooldown(RESEND_COOLDOWN)
    } catch (err) {
      setError(parseApiError(err))
    } finally {
      setIsResending(false)
    }
  }

  /** Extract bare token from clipboard — handles raw token or full verify URL. */
  const extractToken = (raw: string): string => {
    const trimmed = raw.trim()
    try {
      const url = new URL(trimmed)
      const t = url.searchParams.get('token')
      if (t) return t
    } catch {
      // Not a URL — use as-is
    }
    return trimmed
  }

  const handlePaste = async () => {
    try {
      const text = await navigator.clipboard.readText()
      if (text) {
        const extracted = extractToken(text)
        setToken(extracted)
        setPasteSuccess(true)
        setError('')
        setTimeout(() => setPasteSuccess(false), 2000)
        inputRef.current?.focus()
      }
    } catch {
      // Clipboard API unavailable — user will paste manually
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !isVerifying) handleVerify()
    if (e.key === 'Escape' && onClose) onClose()
  }

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
      >
        {/* Backdrop */}
        <motion.div
          className="absolute inset-0 bg-dark-void/80 backdrop-blur-sm"
          onClick={onClose}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        />

        {/* Modal card */}
        <motion.div
          className={cn(
            'relative z-10 w-full max-w-md rounded-xl',
            'bg-dark-card border border-dark-border shadow-card-dark',
          )}
          initial={{ opacity: 0, scale: 0.92, y: 16 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 8 }}
          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
          role="dialog"
          aria-modal="true"
          aria-labelledby="verify-modal-title"
        >
          {/* Top accent bar */}
          <div className="absolute top-0 left-0 right-0 h-[2px] rounded-t-xl bg-gradient-to-r from-transparent via-sentinel-green-neon/60 to-transparent" />

          {/* Close button */}
          {onClose && (
            <button
              onClick={onClose}
              aria-label="Close"
              className={cn(
                'absolute top-4 right-4 w-7 h-7 flex items-center justify-center rounded',
                'text-dark-text-muted hover:text-dark-text-primary',
                'transition-colors focus-visible:outline-none',
              )}
            >
              <X size={15} />
            </button>
          )}

          <div className="p-8">
            {/* Header */}
            <div className="flex flex-col items-center text-center gap-4 mb-8">
              <AnimatePresence mode="wait">
                {verified ? (
                  <motion.div
                    key="success-icon"
                    initial={{ scale: 0, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    className="w-14 h-14 rounded-full flex items-center justify-center bg-sentinel-green-neon/10"
                  >
                    <CheckCircle2
                      size={28}
                      className="text-sentinel-green-neon"
                    />
                  </motion.div>
                ) : (
                  <motion.div
                    key="mail-icon"
                    className="w-14 h-14 rounded-full flex items-center justify-center bg-dark-elevated border border-dark-border"
                    animate={{ y: [0, -4, 0] }}
                    transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
                  >
                    <Mail size={24} className="text-sentinel-green-neon" />
                  </motion.div>
                )}
              </AnimatePresence>

              <div>
                <h2
                  id="verify-modal-title"
                  className="font-display italic text-2xl text-dark-text-primary"
                >
                  {verified ? 'Email verified.' : 'Check your inbox.'}
                </h2>
              </div>

              {!verified && (
                <p className="text-sm text-dark-text-secondary leading-relaxed">
                  We sent a link to{' '}
                  <span className="font-medium text-dark-text-primary">
                    {email}
                  </span>
                  . Paste the verification link or token from your email below.
                </p>
              )}

              {verified && (
                <motion.p
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="text-sm text-sentinel-green-neon font-mono"
                >
                  Email verified — redirecting to login...
                </motion.p>
              )}
            </div>

            {/* Form */}
            {!verified && (
              <div className="flex flex-col gap-5">
                {/* Token input */}
                <div className="flex flex-col gap-2">
                  <label
                    htmlFor="verify-token"
                    className="font-mono text-[11px] uppercase tracking-[0.18em] flex items-center gap-2 text-dark-text-secondary"
                  >
                    <span className="text-sentinel-green-neon opacity-70" aria-hidden>
                      &gt;_
                    </span>
                    Verification Token
                  </label>

                  <div
                    className={cn(
                      'relative flex items-center gap-2',
                      'rounded-md border transition-all duration-200',
                      'bg-dark-surface border-dark-border',
                      'focus-within:border-sentinel-green-neon focus-within:shadow-[0_0_0_3px_rgba(0,232,123,0.15)]',
                      error && '!border-sentinel-red-neon !shadow-[0_0_0_3px_rgba(255,45,74,0.15)]',
                    )}
                  >
                    <input
                      ref={inputRef}
                      id="verify-token"
                      type="text"
                      value={token}
                      onChange={(e) => {
                        setToken(extractToken(e.target.value))
                        setError('')
                      }}
                      onKeyDown={handleKeyDown}
                      placeholder="Paste token from email..."
                      autoComplete="off"
                      spellCheck={false}
                      className={cn(
                        'flex-1 bg-transparent px-4 py-3',
                        'font-mono text-sm',
                        'text-dark-text-primary placeholder:text-dark-text-muted',
                        'placeholder:italic focus:outline-none',
                      )}
                    />

                    {/* Paste button */}
                    <button
                      type="button"
                      onClick={handlePaste}
                      className={cn(
                        'flex items-center gap-1.5 px-3 py-2 mr-1 rounded',
                        'font-mono text-[10px] uppercase tracking-wider',
                        'transition-all duration-200',
                        pasteSuccess
                          ? 'text-sentinel-green-neon'
                          : 'text-dark-text-secondary hover:text-dark-text-primary',
                      )}
                      aria-label="Paste from clipboard"
                    >
                      {pasteSuccess
                        ? <CheckCircle2 size={12} />
                        : <Copy size={12} />
                      }
                      <span>{pasteSuccess ? 'Pasted' : 'Paste'}</span>
                    </button>
                  </div>

                  {/* Error */}
                  {error && (
                    <motion.p
                      initial={{ opacity: 0, y: -4 }}
                      animate={{ opacity: 1, y: 0 }}
                      role="alert"
                      className="flex items-center gap-1.5 font-mono text-xs text-sentinel-red-neon"
                    >
                      <AlertCircle size={11} aria-hidden />
                      {error}
                    </motion.p>
                  )}

                  <p className="font-sans text-xs text-dark-text-muted">
                    You can paste the full link from the email — the token will be extracted automatically.
                  </p>
                </div>

                {/* Verify button */}
                <Button
                  variant="primary"
                  fullWidth
                  isLoading={isVerifying}
                  onClick={handleVerify}
                  disabled={!token.trim()}
                >
                  Verify Identity
                </Button>

                {/* Resend section */}
                <div className="flex items-center justify-center gap-2 pt-2 border-t border-dark-border">
                  <span className="font-mono text-xs text-dark-text-muted">
                    Didn't receive it?
                  </span>
                  <button
                    type="button"
                    onClick={handleResend}
                    disabled={resendCooldown > 0 || isResending}
                    className={cn(
                      'flex items-center gap-1.5 font-mono text-xs transition-colors',
                      resendCooldown > 0 || isResending
                        ? 'text-dark-text-muted cursor-default'
                        : 'text-sentinel-green-neon hover:underline cursor-pointer',
                    )}
                  >
                    {isResending && <RefreshCw size={11} className="animate-spin" />}
                    {resendCooldown > 0
                      ? `Resend in ${resendCooldown}s`
                      : isResending
                        ? 'Sending...'
                        : 'Resend email'
                    }
                  </button>
                </div>
              </div>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
