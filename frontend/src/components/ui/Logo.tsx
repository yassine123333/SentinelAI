import { cn } from '@/lib/utils'

interface LogoProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
  showTagline?: boolean
}

const sizes = {
  sm: { text: 'text-lg', tag: 'text-[10px]', iconSize: 20 },
  md: { text: 'text-2xl', tag: 'text-xs', iconSize: 28 },
  lg: { text: 'text-4xl', tag: 'text-sm', iconSize: 40 },
}

export default function Logo({ size = 'md', className, showTagline = false }: LogoProps) {
  const s = sizes[size]

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <div className="flex items-center gap-2.5">
        {/* Hexagonal icon mark */}
        <div
          className="relative flex items-center justify-center flex-shrink-0"
          style={{ width: s.iconSize, height: s.iconSize }}
        >
          <svg
            width={s.iconSize}
            height={s.iconSize}
            viewBox="0 0 40 40"
            fill="none"
            className="drop-shadow-[0_0_8px_rgba(0,232,123,0.5)]"
          >
            {/* Hexagon outline */}
            <polygon
              points="20,2 36,11 36,29 20,38 4,29 4,11"
              stroke="currentColor"
              strokeWidth="1.5"
              fill="none"
              className="text-sentinel-green-neon"
            />
            {/* Inner shield */}
            <polygon
              points="20,8 30,13.5 30,26.5 20,32 10,26.5 10,13.5"
              fill="currentColor"
              opacity="0.12"
              className="text-sentinel-green-neon"
            />
            {/* S mark */}
            <text
              x="20"
              y="25"
              textAnchor="middle"
              fontFamily="DM Serif Display, serif"
              fontStyle="italic"
              fontSize="16"
              fontWeight="400"
              fill="currentColor"
              className="text-sentinel-green-neon"
            >
              S
            </text>
          </svg>
        </div>

        {/* Wordmark */}
        <div className={cn('font-mono font-medium tracking-tight leading-none', s.text)}>
          <span className="text-dark-text-primary">
            Sentinel
          </span>
          <span className="font-display italic text-sentinel-green-neon">
            AI
          </span>
          <span className="text-dark-text-secondary opacity-50">_</span>
        </div>
      </div>

      {showTagline && (
        <p className={cn(
          'font-mono uppercase tracking-[0.2em] font-light pl-[calc(var(--icon-size,28px)+10px)]',
          s.tag,
          'text-dark-text-secondary',
        )}
          style={{ paddingLeft: s.iconSize + 10 }}
        >
          Geopolitical Risk Intelligence
        </p>
      )}
    </div>
  )
}
