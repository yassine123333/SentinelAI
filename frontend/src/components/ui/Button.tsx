import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md' | 'lg'
  isLoading?: boolean
  isSuccess?: boolean
  fullWidth?: boolean
}

const variants = {
  primary: cn(
    'bg-gradient-to-r from-sentinel-green-neon to-sentinel-green-mid',
    'text-dark-void hover:shadow-glow-green-md',
    'disabled:from-dark-surface disabled:to-dark-surface disabled:text-dark-text-secondary',
  ),
  secondary: cn(
    'border border-dark-border text-dark-text-primary',
    'hover:border-sentinel-green-neon hover:text-sentinel-green-neon',
    'bg-dark-surface',
  ),
  ghost: cn(
    'text-dark-text-secondary hover:text-dark-text-primary hover:bg-dark-surface',
  ),
  danger: cn(
    'bg-sentinel-red-neon text-dark-void hover:shadow-glow-red-md',
  ),
}

const sizes = {
  sm: 'px-4 py-2 text-xs gap-1.5',
  md: 'px-6 py-3 text-sm gap-2',
  lg: 'px-8 py-4 text-base gap-2.5',
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'md',
      isLoading = false,
      isSuccess = false,
      fullWidth = false,
      disabled,
      children,
      className,
      ...props
    },
    ref,
  ) => {
    const isDisabled = disabled || isLoading

    return (
      <motion.button
        ref={ref}
        whileTap={isDisabled ? {} : { scale: 0.97 }}
        whileHover={isDisabled ? {} : { scale: 1.01 }}
        transition={{ type: 'spring', stiffness: 400, damping: 25 }}
        disabled={isDisabled}
        className={cn(
          'relative inline-flex items-center justify-center',
          'font-mono font-medium tracking-wider uppercase',
          'rounded-md transition-all duration-200',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2',
          'focus-visible:ring-sentinel-green-neon focus-visible:ring-offset-dark-bg',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'select-none',
          variants[variant],
          sizes[size],
          fullWidth && 'w-full',
          className,
        )}
        {...(props as React.ComponentProps<typeof motion.button>)}
      >
        {/* Loading spinner */}
        {isLoading && (
          <span className="btn-spinner" aria-hidden="true" />
        )}

        {/* Success checkmark */}
        {isSuccess && !isLoading && (
          <svg
            className="w-4 h-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2.5}
            aria-hidden="true"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        )}

        {/* Children */}
        {!isLoading && children}
      </motion.button>
    )
  },
)

Button.displayName = 'Button'
export default Button
