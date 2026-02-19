import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertCircle, ArrowRight } from 'lucide-react'
import { Turnstile } from '@marsidev/react-turnstile'
import { useAuth, parseApiError } from '@/context/AuthContext'
import { useBotDetection } from '@/hooks/useBotDetection'
import { useRecaptcha } from '@/hooks/useRecaptcha'
import { useTurnstile } from '@/hooks/useTurnstile'
import { pendingHeaders } from '@/services/api'
import Input from '@/components/ui/Input'
import Button from '@/components/ui/Button'
import SecurityBadge from './SecurityBadge'
import EmailVerificationModal from './EmailVerificationModal'
import { cn } from '@/lib/utils'

const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY as string

const schema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required').max(128),
  rememberMe: z.boolean().optional(),
})

type LoginFormValues = z.infer<typeof schema>

interface LoginFormProps {
  onSuccess?: () => void
}

export default function LoginForm({ onSuccess }: LoginFormProps) {
  const { login } = useAuth()
  const [serverError, setServerError]         = useState('')
  const [showVerifyModal, setShowVerifyModal] = useState(false)
  const [unverifiedEmail, setUnverifiedEmail] = useState('')
  const [overridden, setOverridden]           = useState(false)

  // ── Security hooks ────────────────────────────────────────────────────────────
  const bot       = useBotDetection()
  const captcha   = useRecaptcha()
  const turnstile = useTurnstile()

  // Behavioral tracking — managed locally so they don't cause re-renders
  const formStartTime = useRef<number>(0)
  const hasMouseMoved = useRef(false)
  const hasKeyPressed = useRef(false)

  // Reactive risk state for SecurityBadge — re-evaluated after each failure
  const [risk, setRisk] = useState(() =>
    bot.assess({ hasMouseMoved: false, hasKeyPressed: false }),
  )

  useEffect(() => {
    setRisk(bot.assess({
      formStartTime: formStartTime.current || undefined,
      hasMouseMoved: hasMouseMoved.current,
      hasKeyPressed: hasKeyPressed.current,
    }))
  }, [bot.failedAttempts]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Form setup ────────────────────────────────────────────────────────────────
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({
    resolver: zodResolver(schema),
    defaultValues: { rememberMe: false },
  })

  // Lazy-load reCAPTCHA on first user interaction with the form
  const handleFirstInteraction = () => {
    if (formStartTime.current === 0) {
      formStartTime.current = Date.now()
      captcha.load()
    }
  }

  // ── Submit handler ─────────────────────────────────────────────────────────────
  const onSubmit = async (data: LoginFormValues) => {
    setServerError('')

    // Re-assess risk with all behavioral signals collected so far
    const assessment = bot.assess({
      formStartTime: formStartTime.current || undefined,
      hasMouseMoved: hasMouseMoved.current,
      hasKeyPressed: hasKeyPressed.current,
    })
    setRisk(assessment)

    // Block CRITICAL submissions unless manually overridden
    if (assessment.shouldBlock && !overridden) {
      setServerError(
        'Automated behavior detected. If you are a human, click "Override" below and try again.',
      )
      return
    }

    // Require a valid Turnstile challenge token before hitting the backend.
    // The widget resets automatically after 15 min of inactivity (useTurnstile).
    if (!turnstile.isVerified || !turnstile.token) {
      setServerError('Please complete the security challenge above.')
      return
    }

    // Stage reCAPTCHA token + Turnstile token + risk score headers for the next API call.
    // The axios interceptor will pick them up and clear them after one use.
    const rcHeaders = await captcha.injectHeader('login')
    pendingHeaders.set({
      ...rcHeaders,
      // Obfuscated so attackers cannot trivially self-report a low score
      'X-Client-Risk':    btoa(String(Math.round(assessment.score))),
      'X-CF-Turnstile':   turnstile.token,
    })

    try {
      await login({ email: data.email, password: data.password }, data.rememberMe ?? false)
      bot.resetFailed()
      onSuccess?.()
    } catch (err) {
      bot.markFailed()
      const msg = parseApiError(err)

      if (msg.toLowerCase().includes('not verified') || msg.toLowerCase().includes('verify')) {
        setUnverifiedEmail(data.email)
        setShowVerifyModal(true)
      } else {
        setServerError(msg)
      }

      // Re-assess after failure (bumped counter)
      setRisk(bot.assess({
        formStartTime: formStartTime.current || undefined,
        hasMouseMoved: hasMouseMoved.current,
        hasKeyPressed: hasKeyPressed.current,
      }))
    }
  }

  const isBlockedByCritical = risk.shouldBlock && !overridden

  return (
    <>
      <form
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="flex flex-col gap-5"
        aria-label="Login form"
        onFocus={handleFirstInteraction}
        onMouseMove={() => { hasMouseMoved.current = true }}
        onKeyDown={() => { hasKeyPressed.current = true }}
      >
        {/* Server error */}
        <AnimatePresence>
          {serverError && (
            <motion.div
              initial={{ opacity: 0, y: -8, height: 0 }}
              animate={{ opacity: 1, y: 0, height: 'auto' }}
              exit={{ opacity: 0, y: -4, height: 0 }}
              role="alert"
              className={cn(
                'flex items-start gap-3 px-4 py-3 rounded-md',
                'bg-sentinel-red-neon/8',
                'border border-sentinel-red-neon/20',
              )}
            >
              <AlertCircle size={14} className="mt-0.5 flex-shrink-0 text-sentinel-red-neon" aria-hidden />
              <p className="font-mono text-xs text-sentinel-red-neon leading-relaxed">
                {serverError}
              </p>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Email */}
        <Input
          label="Email Address"
          type="email"
          placeholder="analyst@institution.com"
          autoComplete="email"
          error={errors.email?.message}
          {...register('email')}
        />

        {/* Password */}
        <div className="flex flex-col gap-1">
          <Input
            label="Password"
            type="password"
            placeholder="Enter your password"
            autoComplete="current-password"
            showPasswordToggle
            error={errors.password?.message}
            {...register('password')}
          />
          <div className="flex justify-end">
            <Link
              to="/forgot-password"
              className="font-mono text-[10px] uppercase tracking-wider text-dark-text-secondary hover:text-sentinel-green-neon transition-colors"
            >
              Forgot password?
            </Link>
          </div>
        </div>

        {/* Remember me */}
        <label className="flex items-center gap-3 cursor-pointer group">
          <div className="relative flex-shrink-0">
            <input type="checkbox" className="sr-only" {...register('rememberMe')} />
            <div className={cn(
              'w-4 h-4 rounded border transition-all duration-150',
              'border-dark-border bg-dark-surface',
              'group-hover:border-sentinel-green-neon',
            )}>
              <svg viewBox="0 0 16 16" className="w-full h-full text-sentinel-green-neon opacity-0 group-has-[:checked]:opacity-100 transition-opacity">
                <path d="M3 8l3.5 3.5L13 4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          </div>
          <span className="font-mono text-xs text-dark-text-secondary">
            Keep me authenticated
          </span>
        </label>

        {/* ── Security Badge ────────────────────────────────────────────────────── */}
        <SecurityBadge
          level={risk.level}
          score={risk.score}
          flagged={risk.flagged}
          failedAttempts={bot.failedAttempts}
          isRecaptchaReady={captcha.isReady}
          onOverride={() => {
            setOverridden(true)
            setServerError('')
          }}
        />

        {/* ── Cloudflare Turnstile challenge ────────────────────────────────────── */}
        <div className="flex flex-col gap-1.5">
          <Turnstile
            ref={turnstile.widgetRef}
            siteKey={TURNSTILE_SITE_KEY}
            onSuccess={turnstile.onSuccess}
            onError={turnstile.onError}
            onExpire={turnstile.onExpire}
            options={{
              theme: 'auto',
              size: 'normal',
              language: 'auto',
            }}
            style={{ borderRadius: '6px' }}
          />
          {!turnstile.isVerified && (
            <p className="font-mono text-[10px] text-dark-text-muted">
              Complete the security check to proceed.
            </p>
          )}
        </div>

        {/* Submit */}
        <Button
          type="submit"
          variant="primary"
          size="lg"
          fullWidth
          isLoading={isSubmitting}
          disabled={isBlockedByCritical}
          className="mt-1"
          title={isBlockedByCritical ? 'Automated behavior detected — use Override below' : undefined}
        >
          <span>Authenticate</span>
          {!isSubmitting && <ArrowRight size={16} aria-hidden />}
        </Button>

        {/* Signup link */}
        <p className="text-center font-mono text-xs text-dark-text-muted">
          No access?{' '}
          <Link to="/signup" className="text-sentinel-green-neon hover:underline font-medium">
            Request credentials
          </Link>
        </p>
      </form>

      {/* Email verification modal */}
      {showVerifyModal && unverifiedEmail && (
        <EmailVerificationModal
          email={unverifiedEmail}
          onSuccess={() => {
            setShowVerifyModal(false)
            const values = getValues()
            login({ email: values.email, password: values.password }, values.rememberMe ?? false)
              .then(() => onSuccess?.())
              .catch((err) => setServerError(parseApiError(err)))
          }}
          onClose={() => setShowVerifyModal(false)}
        />
      )}
    </>
  )
}
