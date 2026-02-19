import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertCircle, ArrowRight, CheckCircle2 } from 'lucide-react'
import { useAuth, parseApiError } from '@/context/AuthContext'
import { useBotDetection } from '@/hooks/useBotDetection'
import { useRecaptcha } from '@/hooks/useRecaptcha'
import { pendingHeaders } from '@/services/api'
import Input from '@/components/ui/Input'
import Button from '@/components/ui/Button'
import SecurityBadge from './SecurityBadge'
import { cn } from '@/lib/utils'

const schema = z
  .object({
    fullname: z.string().min(2, 'Name must be at least 2 characters').max(100)
      .regex(/^[\w\s\-'.]{2,100}$/u, 'Name may only contain letters, spaces, hyphens, apostrophes, or dots'),
    email: z.string().email('Enter a valid email address'),
    password: z.string().min(8, 'Password must be at least 8 characters').max(128)
      .regex(/[a-z]/, 'Must contain a lowercase letter')
      .regex(/[A-Z]/, 'Must contain an uppercase letter')
      .regex(/\d/, 'Must contain a number')
      .regex(/[!@#$%^&*()\-_=+[\]{};:'",.<>?/\\|`~]/, 'Must contain a special character'),
    confirm_password: z.string(),
  })
  .refine((d) => d.password === d.confirm_password, {
    message: 'Passwords do not match',
    path: ['confirm_password'],
  })

type SignupFormValues = z.infer<typeof schema>

interface Criterion { label: string; check: (p: string) => boolean }
const CRITERIA: Criterion[] = [
  { label: '8+ chars',  check: (p) => p.length >= 8 },
  { label: 'Uppercase', check: (p) => /[A-Z]/.test(p) },
  { label: 'Lowercase', check: (p) => /[a-z]/.test(p) },
  { label: 'Number',    check: (p) => /\d/.test(p) },
  { label: 'Symbol',    check: (p) => /[!@#$%^&*()\-_=+[\]{};:'",.<>?/\\|`~]/.test(p) },
]

function getStrengthLevel(password: string): 0 | 1 | 2 | 3 | 4 {
  if (!password) return 0
  const met = CRITERIA.filter((c) => c.check(password)).length
  if (met <= 1) return 1
  if (met === 2) return 2
  if (met === 3 || met === 4) return 3
  return 4
}

const STRENGTH_LABELS  = ['', 'Weak', 'Fair', 'Strong', 'Very Strong']
const STRENGTH_COLORS  = ['', '#ff2d4a', '#f5a623', '#00e87b', '#00e87b']

function PasswordStrength({ password }: { password: string }) {
  const level  = getStrengthLevel(password)
  if (!password) return null
  return (
    <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="flex flex-col gap-2">
      <div className="flex gap-1">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-1 flex-1 rounded-full bg-dark-border overflow-hidden">
            {level >= i && <motion.div className="h-full rounded-full" initial={{ width: 0 }} animate={{ width: '100%' }} style={{ backgroundColor: STRENGTH_COLORS[level] }} />}
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] font-medium" style={{ color: STRENGTH_COLORS[level] || undefined }}>{STRENGTH_LABELS[level]}</span>
        <div className="flex gap-2">
          {CRITERIA.map((c) => (
            <span key={c.label} className={cn('font-mono text-[9px] transition-all duration-200', c.check(password) ? 'text-sentinel-green-neon' : 'text-dark-text-muted')}>
              {c.check(password) ? '✓' : '○'} {c.label}
            </span>
          ))}
        </div>
      </div>
    </motion.div>
  )
}

interface SignupFormProps { onSuccess: (email: string) => void }

export default function SignupForm({ onSuccess }: SignupFormProps) {
  const { register: registerUser } = useAuth()
  const [serverError, setServerError] = useState('')
  const [overridden, setOverridden]   = useState(false)

  const bot     = useBotDetection()
  const captcha = useRecaptcha()

  const formStartTime = useRef<number>(0)
  const hasMouseMoved = useRef(false)
  const hasKeyPressed = useRef(false)

  const [risk, setRisk] = useState(() => bot.assess({ hasMouseMoved: false, hasKeyPressed: false }))

  useEffect(() => {
    setRisk(bot.assess({
      formStartTime: formStartTime.current || undefined,
      hasMouseMoved: hasMouseMoved.current,
      hasKeyPressed: hasKeyPressed.current,
    }))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bot.failedAttempts])

  const { register, handleSubmit, watch, formState: { errors, isSubmitting } } = useForm<SignupFormValues>({
    resolver: zodResolver(schema),
    mode: 'onTouched',
  })

  const passwordValue = watch('password') ?? ''

  const handleFirstInteraction = () => {
    if (formStartTime.current === 0) {
      formStartTime.current = Date.now()
      captcha.load()
    }
  }

  const onSubmit = async (data: SignupFormValues) => {
    setServerError('')
    const assessment = bot.assess({
      formStartTime: formStartTime.current || undefined,
      hasMouseMoved: hasMouseMoved.current,
      hasKeyPressed: hasKeyPressed.current,
    })
    setRisk(assessment)

    if (assessment.shouldBlock && !overridden) {
      setServerError('Automated behavior detected. If you are a human, click "Override" below and try again.')
      return
    }

    const rcHeaders = await captcha.injectHeader('register')
    pendingHeaders.set({ ...rcHeaders, 'X-Client-Risk': btoa(String(Math.round(assessment.score))) })

    try {
      await registerUser({
        fullname: data.fullname.trim(),
        email: data.email.toLowerCase(),
        password: data.password,
        confirm_password: data.confirm_password,
      })
      onSuccess(data.email.toLowerCase())
    } catch (err) {
      bot.markFailed()
      setServerError(parseApiError(err))
      setRisk(bot.assess({
        formStartTime: formStartTime.current || undefined,
        hasMouseMoved: hasMouseMoved.current,
        hasKeyPressed: hasKeyPressed.current,
      }))
    }
  }

  const isBlockedByCritical = risk.shouldBlock && !overridden

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4" aria-label="Registration form"
      onFocus={handleFirstInteraction}
      onMouseMove={() => { hasMouseMoved.current = true }}
      onKeyDown={() => { hasKeyPressed.current = true }}
    >
      <AnimatePresence>
        {serverError && (
          <motion.div initial={{ opacity: 0, y: -8, height: 0 }} animate={{ opacity: 1, y: 0, height: 'auto' }} exit={{ opacity: 0, y: -4, height: 0 }} role="alert"
            className={cn('flex items-start gap-3 px-4 py-3 rounded-md', 'bg-sentinel-red-neon/8', 'border border-sentinel-red-neon/20')}
          >
            <AlertCircle size={14} className="mt-0.5 flex-shrink-0 text-sentinel-red-neon" aria-hidden />
            <p className="font-mono text-xs text-sentinel-red-neon leading-relaxed">{serverError}</p>
          </motion.div>
        )}
      </AnimatePresence>

      <Input label="Full Name" type="text" placeholder="Jane Doe" autoComplete="name" error={errors.fullname?.message} {...register('fullname')} />
      <Input label="Email Address" type="email" placeholder="analyst@institution.com" autoComplete="email" error={errors.email?.message} {...register('email')} />

      <div className="flex flex-col gap-2">
        <Input label="Password" type="password" placeholder="Create a strong password" autoComplete="new-password" showPasswordToggle error={errors.password?.message} {...register('password')} />
        <AnimatePresence>{passwordValue && <PasswordStrength password={passwordValue} />}</AnimatePresence>
      </div>

      <Input
        label="Confirm Password" type="password" placeholder="Repeat your password"
        autoComplete="new-password" showPasswordToggle error={errors.confirm_password?.message}
        suffix={passwordValue && watch('confirm_password') === passwordValue
          ? <CheckCircle2 size={14} className="text-sentinel-green-neon" />
          : undefined}
        {...register('confirm_password')}
      />

      <SecurityBadge
        level={risk.level} score={risk.score} flagged={risk.flagged}
        failedAttempts={bot.failedAttempts} isRecaptchaReady={captcha.isReady}
        onOverride={() => { setOverridden(true); setServerError('') }}
      />

      <Button type="submit" variant="primary" size="lg" fullWidth isLoading={isSubmitting} disabled={isBlockedByCritical} className="mt-1">
        <span>Create Account</span>
        {!isSubmitting && <ArrowRight size={16} aria-hidden />}
      </Button>

      <p className="text-center font-mono text-xs text-dark-text-muted">
        Already have access?{' '}
        <Link to="/login" className="text-sentinel-green-neon hover:underline font-medium">Authenticate</Link>
      </p>
    </form>
  )
}
