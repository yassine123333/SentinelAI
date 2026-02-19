import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertCircle, Check, CheckCircle2, ShieldCheck } from 'lucide-react'
import { useAuth, parseApiError } from '@/context/AuthContext'
import Input from '@/components/ui/Input'
import Button from '@/components/ui/Button'
import { cn } from '@/lib/utils'

// ── Avatar asset imports ───────────────────────────────────────────────────────
import avatar1 from '@/assets/avatar-1.png'
import avatar2 from '@/assets/avatar-2.png'
import avatar3 from '@/assets/avatar-3.png'
import avatar4 from '@/assets/avatar-4.png'
import avatar5 from '@/assets/avatar-5.png'
import avatar6 from '@/assets/avatar-6.png'
import avatar7 from '@/assets/avatar-7.png'
import avatar8 from '@/assets/avatar-8.png'

export const AVATAR_MAP: Record<number, string> = {
  1: avatar1,
  2: avatar2,
  3: avatar3,
  4: avatar4,
  5: avatar5,
  6: avatar6,
  7: avatar7,
  8: avatar8,
}

const AVATAR_LABELS: Record<number, string> = {
  1: 'Analyst',
  2: 'Crypto Specialist',
  3: 'Senior Analyst',
  4: 'Portfolio Manager',
  5: 'Director',
  6: 'Market Analyst',
  7: 'Trading Specialist',
  8: 'Anonymous',
}

// ── Form schema ────────────────────────────────────────────────────────────────
const schema = z.object({
  fullname: z
    .string()
    .min(2, 'Name must be at least 2 characters')
    .max(100)
    .regex(
      /^[\w\s\-'.]{2,100}$/u,
      'Name may only contain letters, spaces, hyphens, apostrophes, or dots',
    ),
})

type FormValues = z.infer<typeof schema>

export default function ProfileInfoTab() {
  const { user, updateProfile } = useAuth()
  const [selectedAvatar, setSelectedAvatar] = useState<number>(user?.avatar_id ?? 0)
  const [serverError, setServerError] = useState('')
  const [saved, setSaved] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { fullname: user?.fullname ?? '' },
  })

  const hasChanges = isDirty || selectedAvatar !== (user?.avatar_id ?? 0)

  const onSubmit = async (data: FormValues) => {
    setServerError('')
    setSaved(false)
    try {
      await updateProfile({
        fullname: data.fullname.trim(),
        ...(selectedAvatar > 0 && { avatar_id: selectedAvatar }),
      })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      setServerError(parseApiError(err))
    }
  }

  return (
    <div className="flex flex-col gap-8">
      {/* Section: Avatar */}
      <section>
        <div className="mb-4">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-sentinel-green-neon flex items-center gap-2">
            <span className="opacity-60">&gt;_</span> SELECT_AVATAR
          </p>
          <p className="font-sans text-xs text-dark-text-muted mt-1">
            Choose a persona for your analyst profile.
          </p>
        </div>

        <div className="grid grid-cols-4 gap-3">
          {Object.entries(AVATAR_MAP).map(([idStr, src]) => {
            const id = Number(idStr)
            const isSelected = selectedAvatar === id
            return (
              <motion.button
                key={id}
                type="button"
                onClick={() => setSelectedAvatar(id)}
                whileHover={{ scale: 1.04 }}
                whileTap={{ scale: 0.97 }}
                transition={{ type: 'spring', stiffness: 400, damping: 25 }}
                title={AVATAR_LABELS[id]}
                className={cn(
                  'relative aspect-square rounded-xl overflow-hidden',
                  'transition-all duration-200 focus-visible:outline-none',
                  'focus-visible:ring-2 focus-visible:ring-sentinel-green-neon',
                  isSelected
                    ? 'ring-2 ring-sentinel-green-neon shadow-glow-green-md'
                    : 'ring-1 ring-dark-border hover:ring-sentinel-green-neon/50',
                )}
                aria-pressed={isSelected}
                aria-label={`Select avatar: ${AVATAR_LABELS[id]}`}
              >
                <img
                  src={src}
                  alt={AVATAR_LABELS[id]}
                  className="w-full h-full object-cover object-top"
                  draggable={false}
                />

                {/* Selected overlay */}
                <AnimatePresence>
                  {isSelected && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="absolute inset-0 bg-gradient-to-t from-sentinel-green-neon/20 to-transparent pointer-events-none"
                    />
                  )}
                </AnimatePresence>

                {/* Checkmark badge */}
                <AnimatePresence>
                  {isSelected && (
                    <motion.div
                      initial={{ scale: 0, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      exit={{ scale: 0, opacity: 0 }}
                      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                      className={cn(
                        'absolute top-1.5 right-1.5 w-5 h-5 rounded-full',
                        'bg-sentinel-green-neon',
                        'flex items-center justify-center shadow-glow-green-sm',
                      )}
                    >
                      <Check size={11} className="text-dark-void" strokeWidth={3} />
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* Label on hover */}
                <div className={cn(
                  'absolute bottom-0 inset-x-0 py-1.5 px-2',
                  'bg-gradient-to-t from-black/80 to-transparent',
                  'opacity-0 hover:opacity-100 transition-opacity duration-200',
                )}>
                  <p className="font-mono text-[9px] text-white/90 uppercase tracking-wider truncate text-center">
                    {AVATAR_LABELS[id]}
                  </p>
                </div>
              </motion.button>
            )
          })}
        </div>

        {selectedAvatar === 0 && (
          <p className="font-mono text-[10px] text-dark-text-muted mt-2">
            No avatar selected — your initials will be displayed instead.
          </p>
        )}
      </section>

      {/* Divider */}
      <div className="h-px bg-dark-border" />

      {/* Section: Profile info */}
      <section>
        <div className="mb-4">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-sentinel-green-neon flex items-center gap-2">
            <span className="opacity-60">&gt;_</span> PROFILE_INFO
          </p>
        </div>

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="flex flex-col gap-5">
          {/* Error */}
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

          <Input
            label="Full Name"
            type="text"
            placeholder="Your full name"
            autoComplete="name"
            error={errors.fullname?.message}
            {...register('fullname')}
          />

          {/* Email — read-only */}
          <div className="flex flex-col gap-1.5">
            <label className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] flex items-center gap-2 text-dark-text-secondary">
              <span className="opacity-60 text-sentinel-green-neon">&gt;_</span>
              Email Address
            </label>
            <div className={cn(
              'flex items-center gap-3 px-4 py-3 rounded-md border',
              'bg-dark-surface border-dark-border opacity-70',
            )}>
              <span className="font-mono text-sm text-dark-text-primary flex-1 truncate">
                {user?.email}
              </span>
              {user?.is_verified && (
                <span className="flex items-center gap-1 flex-shrink-0">
                  <ShieldCheck size={13} className="text-sentinel-green-neon" />
                  <span className="font-mono text-[10px] uppercase tracking-wider text-sentinel-green-neon">
                    Verified
                  </span>
                </span>
              )}
            </div>
            <p className="text-xs font-mono text-dark-text-muted">
              Email cannot be changed after registration.
            </p>
          </div>

          {/* Save */}
          <div className="flex items-center gap-3 pt-1">
            <Button
              type="submit"
              variant="primary"
              size="md"
              isLoading={isSubmitting}
              isSuccess={saved}
              disabled={!hasChanges}
            >
              {saved ? (
                <>
                  <CheckCircle2 size={14} />
                  <span>Saved</span>
                </>
              ) : (
                <span>Save Changes</span>
              )}
            </Button>
            {!hasChanges && !saved && (
              <span className="font-mono text-[10px] text-dark-text-muted">
                No changes to save
              </span>
            )}
          </div>
        </form>
      </section>
    </div>
  )
}
