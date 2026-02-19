import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertCircle, CheckCircle2, Clock, Mail, ShieldCheck } from 'lucide-react'
import { useAuth, parseApiError } from '@/context/AuthContext'
import Input from '@/components/ui/Input'
import Button from '@/components/ui/Button'
import { cn } from '@/lib/utils'

// ── Password strength ─────────────────────────────────────────────────────────
interface Criterion { label: string; check: (p: string) => boolean }
const CRITERIA: Criterion[] = [
  { label: '8+ chars',  check: (p) => p.length >= 8 },
  { label: 'Uppercase', check: (p) => /[A-Z]/.test(p) },
  { label: 'Lowercase', check: (p) => /[a-z]/.test(p) },
  { label: 'Number',    check: (p) => /\d/.test(p) },
  { label: 'Symbol',    check: (p) => /[!@#$%^&*()\-_=+[\]{};:'",.<>?/\\|`~]/.test(p) },
]

const STRENGTH_LABELS  = ['', 'Weak', 'Fair', 'Strong', 'Very Strong']
const STRENGTH_COLORS  = ['', '#ff2d4a', '#f5a623', '#00e87b', '#00e87b']

function getStrengthLevel(password: string): 0 | 1 | 2 | 3 | 4 {
  if (!password) return 0
  const met = CRITERIA.filter((c) => c.check(password)).length
  if (met <= 1) return 1
  if (met === 2) return 2
  if (met === 3 || met === 4) return 3
  return 4
}

function PasswordStrength({ password }: { password: string }) {
  const level = getStrengthLevel(password)
  if (!password) return null
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="flex flex-col gap-2"
    >
      <div className="flex gap-1">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-1 flex-1 rounded-full bg-dark-border overflow-hidden">
            {level >= i && (
              <motion.div
                className="h-full rounded-full"
                initial={{ width: 0 }}
                animate={{ width: '100%' }}
                style={{ backgroundColor: STRENGTH_COLORS[level] }}
              />
            )}
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] font-medium" style={{ color: STRENGTH_COLORS[level] || undefined }}>
          {STRENGTH_LABELS[level]}
        </span>
        <div className="flex gap-2 flex-wrap justify-end">
          {CRITERIA.map((c) => (
            <span
              key={c.label}
              className={cn(
                'font-mono text-[9px] transition-all duration-200',
                c.check(password)
                  ? 'text-sentinel-green-neon'
                  : 'text-dark-text-muted',
              )}
            >
              {c.check(password) ? '✓' : '○'} {c.label}
            </span>
          ))}
        </div>
      </div>
    </motion.div>
  )
}

// ── Form schema ───────────────────────────────────────────────────────────────
const schema = z
  .object({
    current_password:    z.string().min(1, 'Current password is required').max(128),
    new_password:        z.string()
      .min(8, 'Password must be at least 8 characters')
      .max(128)
      .regex(/[a-z]/, 'Must contain a lowercase letter')
      .regex(/[A-Z]/, 'Must contain an uppercase letter')
      .regex(/\d/, 'Must contain a number')
      .regex(/[!@#$%^&*()\-_=+[\]{};:'",.<>?/\\|`~]/, 'Must contain a special character'),
    confirm_new_password: z.string(),
  })
  .refine((d) => d.new_password === d.confirm_new_password, {
    message: 'Passwords do not match',
    path: ['confirm_new_password'],
  })
  .refine((d) => d.current_password !== d.new_password, {
    message: 'New password must differ from the current one',
    path: ['new_password'],
  })

type FormValues = z.infer<typeof schema>

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatDate(iso?: string): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(iso))
}

export default function SecurityTab() {
  const { user, changePassword } = useAuth()
  const [serverError, setServerError] = useState('')
  const [saved, setSaved]             = useState(false)

  const {
    register,
    handleSubmit,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), mode: 'onTouched' })

  const newPasswordValue    = watch('new_password') ?? ''
  const confirmPasswordValue = watch('confirm_new_password') ?? ''

  const onSubmit = async (data: FormValues) => {
    setServerError('')
    setSaved(false)
    try {
      await changePassword({
        current_password:    data.current_password,
        new_password:        data.new_password,
        confirm_new_password: data.confirm_new_password,
      })
      setSaved(true)
      reset()
      setTimeout(() => setSaved(false), 4000)
    } catch (err) {
      setServerError(parseApiError(err))
    }
  }

  return (
    <div className="flex flex-col gap-8">
      {/* ── Change password form ─────────────────────────────────────────── */}
      <section>
        <div className="mb-5">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-sentinel-green-neon flex items-center gap-2">
            <span className="opacity-60">&gt;_</span> CHANGE_PASSWORD
          </p>
          <p className="font-sans text-xs text-dark-text-muted mt-1">
            Your new password must meet the same strength requirements as registration.
          </p>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
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

          {/* Success banner */}
          <AnimatePresence>
            {saved && (
              <motion.div
                initial={{ opacity: 0, y: -8, height: 0 }}
                animate={{ opacity: 1, y: 0, height: 'auto' }}
                exit={{ opacity: 0, y: -4, height: 0 }}
                role="status"
                className={cn(
                  'flex items-center gap-3 px-4 py-3 rounded-md',
                  'bg-sentinel-green-neon/8',
                  'border border-sentinel-green-neon/20',
                )}
              >
                <CheckCircle2 size={14} className="flex-shrink-0 text-sentinel-green-neon" />
                <p className="font-mono text-xs text-sentinel-green-neon">
                  Password updated successfully. All other sessions remain active until token expiry.
                </p>
              </motion.div>
            )}
          </AnimatePresence>

          <Input
            label="Current Password"
            type="password"
            placeholder="Your current password"
            autoComplete="current-password"
            showPasswordToggle
            error={errors.current_password?.message}
            {...register('current_password')}
          />

          <div className="flex flex-col gap-2">
            <Input
              label="New Password"
              type="password"
              placeholder="Create a strong password"
              autoComplete="new-password"
              showPasswordToggle
              error={errors.new_password?.message}
              {...register('new_password')}
            />
            <AnimatePresence>
              {newPasswordValue && <PasswordStrength password={newPasswordValue} />}
            </AnimatePresence>
          </div>

          <Input
            label="Confirm New Password"
            type="password"
            placeholder="Repeat your new password"
            autoComplete="new-password"
            showPasswordToggle
            error={errors.confirm_new_password?.message}
            suffix={
              newPasswordValue && confirmPasswordValue === newPasswordValue
                ? <CheckCircle2 size={14} className="text-sentinel-green-neon" />
                : undefined
            }
            {...register('confirm_new_password')}
          />

          <Button
            type="submit"
            variant="primary"
            size="md"
            isLoading={isSubmitting}
            className="self-start"
          >
            Update Password
          </Button>
        </form>
      </section>

      {/* Divider */}
      <div className="h-px bg-dark-border" />

      {/* ── Account information ──────────────────────────────────────────── */}
      <section>
        <div className="mb-4">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-sentinel-green-neon flex items-center gap-2">
            <span className="opacity-60">&gt;_</span> ACCOUNT_INFO
          </p>
        </div>

        <div className={cn(
          'rounded-xl border divide-y overflow-hidden',
          'border-dark-border divide-dark-border',
        )}>
          {[
            {
              icon: <Mail size={14} />,
              label: 'Email Address',
              value: user?.email ?? '—',
              badge: user?.is_verified
                ? { text: 'Verified', green: true }
                : { text: 'Unverified', green: false },
            },
            {
              icon: <ShieldCheck size={14} />,
              label: 'Account Status',
              value: user?.role === 'admin' ? 'Administrator' : 'Analyst',
              badge: { text: user?.role?.toUpperCase() ?? 'ANALYST', green: true },
            },
            {
              icon: <Clock size={14} />,
              label: 'Member Since',
              value: formatDate(user?.created_at),
            },
            {
              icon: <Clock size={14} />,
              label: 'Last Login',
              value: formatDate(user?.last_login),
            },
          ].map(({ icon, label, value, badge }) => (
            <div
              key={label}
              className={cn(
                'flex items-center justify-between px-5 py-3.5',
                'bg-dark-surface/50',
              )}
            >
              <div className="flex items-center gap-3">
                <span className="text-dark-text-muted">{icon}</span>
                <span className="font-mono text-xs text-dark-text-secondary">
                  {label}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-dark-text-primary">
                  {value}
                </span>
                {badge && (
                  <span className={cn(
                    'font-mono text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded',
                    badge.green
                      ? 'bg-sentinel-green-neon/10 text-sentinel-green-neon'
                      : 'bg-sentinel-red-neon/10 text-sentinel-red-neon',
                  )}>
                    {badge.text}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
