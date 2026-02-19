import { forwardRef, useState, type InputHTMLAttributes, type ReactNode } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { cn } from '@/lib/utils'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  hint?: string
  prefix?: string
  suffix?: ReactNode
  showPasswordToggle?: boolean
  containerClassName?: string
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  (
    {
      label,
      error,
      hint,
      prefix = '>_',
      suffix,
      showPasswordToggle = false,
      containerClassName,
      className,
      type,
      id,
      ...props
    },
    ref,
  ) => {
    const [showPassword, setShowPassword] = useState(false)
    const inputType = showPasswordToggle && type === 'password'
      ? (showPassword ? 'text' : 'password')
      : type

    const inputId = id || label?.toLowerCase().replace(/\s+/g, '-')

    return (
      <div className={cn('flex flex-col gap-1.5', containerClassName)}>
        {/* Label */}
        {label && (
          <label
            htmlFor={inputId}
            className={cn(
              'font-mono text-[11px] font-medium uppercase tracking-[0.18em]',
              'flex items-center gap-2',
              error
                ? 'text-sentinel-red-neon'
                : 'text-dark-text-secondary',
            )}
          >
            <span
              className={cn(
                'opacity-60',
                error
                  ? 'text-sentinel-red-neon'
                  : 'text-sentinel-green-neon',
              )}
              aria-hidden="true"
            >
              {prefix}
            </span>
            {label}
          </label>
        )}

        {/* Input wrapper */}
        <div
          className={cn(
            'relative flex items-center',
            'rounded-md border transition-all duration-200',
            'bg-dark-surface border-dark-border',
            // Focus state
            'focus-within:border-sentinel-green-neon focus-within:shadow-[0_0_0_3px_rgba(0,232,123,0.15)]',
            // Error state
            error && '!border-sentinel-red-neon !shadow-[0_0_0_3px_rgba(255,45,74,0.15)]',
          )}
        >
          <input
            ref={ref}
            id={inputId}
            type={inputType}
            className={cn(
              'w-full bg-transparent px-4 py-3',
              'font-mono text-sm',
              'text-dark-text-primary placeholder:text-dark-text-muted',
              'focus:outline-none',
              'placeholder:italic',
              showPasswordToggle && 'pr-12',
              suffix && 'pr-12',
              className,
            )}
            aria-invalid={!!error}
            aria-describedby={
              [error && `${inputId}-error`, hint && `${inputId}-hint`]
                .filter(Boolean)
                .join(' ') || undefined
            }
            {...props}
          />

          {/* Password toggle */}
          {showPasswordToggle && (
            <button
              type="button"
              onClick={() => setShowPassword((p) => !p)}
              className={cn(
                'absolute right-3 flex items-center justify-center w-8 h-8 rounded',
                'text-dark-text-secondary hover:text-dark-text-primary',
                'transition-colors focus-visible:outline-none',
              )}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              tabIndex={-1}
            >
              {showPassword
                ? <EyeOff size={15} aria-hidden="true" />
                : <Eye size={15} aria-hidden="true" />
              }
            </button>
          )}

          {/* Suffix */}
          {!showPasswordToggle && suffix && (
            <div className="absolute right-3 flex items-center">
              {suffix}
            </div>
          )}
        </div>

        {/* Error message */}
        {error && (
          <p
            id={`${inputId}-error`}
            role="alert"
            className="flex items-center gap-1.5 text-xs font-mono text-sentinel-red-neon"
          >
            <span aria-hidden="true">!</span>
            {error}
          </p>
        )}

        {/* Hint */}
        {hint && !error && (
          <p
            id={`${inputId}-hint`}
            className="text-xs font-mono text-dark-text-muted"
          >
            {hint}
          </p>
        )}
      </div>
    )
  },
)

Input.displayName = 'Input'
export default Input
