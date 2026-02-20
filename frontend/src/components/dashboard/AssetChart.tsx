/**
 * AssetChart — SVG price chart with historical line + Chronos-2 forecast band.
 *
 * No external charting library required — pure SVG + Framer Motion.
 * Renders:
 *  • Gradient-filled historical close-price line
 *  • Animated stroke-draw on load
 *  • Dashed forecast median line with p10–p90 confidence band
 *  • Price axis (right), date axis (bottom), current-price crosshair
 */
import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { TrendingDown, TrendingUp, Zap } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ChartData } from '@/types/pipeline'

// ── Layout constants ──────────────────────────────────────────────────────────
const W = 800          // viewBox width
const H = 220          // viewBox height
const PAD_L = 12
const PAD_R = 58       // space for y-axis labels
const PAD_T = 16
const PAD_B = 28       // space for x-axis labels
const CHART_W = W - PAD_L - PAD_R
const CHART_H = H - PAD_T - PAD_B

// ── Helpers ───────────────────────────────────────────────────────────────────

function lerp(value: number, inMin: number, inMax: number, outMin: number, outMax: number) {
  if (inMax === inMin) return (outMin + outMax) / 2
  return outMin + ((value - inMin) / (inMax - inMin)) * (outMax - outMin)
}

function toX(i: number, total: number) {
  return PAD_L + lerp(i, 0, total - 1, 0, CHART_W)
}

function toY(price: number, min: number, max: number) {
  return PAD_T + lerp(price, max, min, 0, CHART_H)   // inverted: high price = low y
}

function buildPath(points: [number, number][]): string {
  if (points.length === 0) return ''
  const [first, ...rest] = points
  const d = [`M ${first[0].toFixed(1)} ${first[1].toFixed(1)}`]
  for (let i = 0; i < rest.length; i++) {
    const prev = i === 0 ? first : rest[i - 1]
    const cur  = rest[i]
    const cpx  = (prev[0] + cur[0]) / 2
    d.push(`C ${cpx.toFixed(1)} ${prev[1].toFixed(1)}, ${cpx.toFixed(1)} ${cur[1].toFixed(1)}, ${cur[0].toFixed(1)} ${cur[1].toFixed(1)}`)
  }
  return d.join(' ')
}

function formatPrice(p: number) {
  if (p >= 10_000) return `$${(p / 1000).toFixed(1)}k`
  if (p >= 1_000)  return `$${p.toFixed(0)}`
  if (p >= 10)     return `$${p.toFixed(2)}`
  return `$${p.toFixed(4)}`
}

function formatDate(dateStr: string) {
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function pctChange(prices: { close: number }[]) {
  if (prices.length < 2) return 0
  const first = prices[0].close
  const last  = prices[prices.length - 1].close
  return ((last - first) / first) * 100
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function ChartSkeleton() {
  return (
    <div className="w-full h-[220px] flex items-center justify-center">
      <div className="flex flex-col items-center gap-2">
        <div className="flex gap-1">
          {Array.from({ length: 12 }).map((_, i) => (
            <div
              key={i}
              className="w-1 bg-sentinel-green-neon/20 rounded-full animate-pulse"
              style={{ height: `${30 + Math.sin(i * 0.8) * 20}px`, animationDelay: `${i * 60}ms` }}
            />
          ))}
        </div>
        <span className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted/40 mt-1">
          Loading price data…
        </span>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  data: ChartData | null
  loading: boolean
  error: string | null
}

export default function AssetChart({ data, loading, error }: Props) {
  const pathRef = useRef<SVGPathElement>(null)
  const [pathLen, setPathLen] = useState(0)
  const [drawn, setDrawn] = useState(false)

  // Recalculate path length when data changes
  useEffect(() => {
    setDrawn(false)
    const t = requestAnimationFrame(() => {
      if (pathRef.current) {
        setPathLen(pathRef.current.getTotalLength())
        setDrawn(true)
      }
    })
    return () => cancelAnimationFrame(t)
  }, [data])

  if (loading) return <ChartSkeleton />

  if (error || !data || data.prices.length === 0) {
    return (
      <div className="w-full h-[220px] flex items-center justify-center">
        <span className="font-mono text-[10px] text-dark-text-muted/50">
          {error ?? 'No price data available'}
        </span>
      </div>
    )
  }

  const { prices, forecast } = data
  const closes = prices.map(p => p.close)
  const pctChg  = pctChange(prices)
  const isUp    = pctChg >= 0
  const lineColor = isUp ? '#00e87b' : '#ff2d4a'

  // ── Price extents (historical only for y-axis) ────────────────────────────
  let yMin = Math.min(...closes)
  let yMax = Math.max(...closes)

  // Extend range to include forecast band
  if (forecast) {
    yMin = Math.min(yMin, forecast.p10)
    yMax = Math.max(yMax, forecast.p90)
  }

  const pad = (yMax - yMin) * 0.08
  yMin -= pad
  yMax += pad

  // ── Build historical path ────────────────────────────────────────────────
  const histPoints: [number, number][] = prices.map((p, i) => [
    toX(i, prices.length),
    toY(p.close, yMin, yMax),
  ])
  const histPath = buildPath(histPoints)

  // Area fill: close the path along the bottom
  const areaPath = histPath
    + ` L ${histPoints[histPoints.length - 1][0].toFixed(1)} ${(PAD_T + CHART_H).toFixed(1)}`
    + ` L ${PAD_L.toFixed(1)} ${(PAD_T + CHART_H).toFixed(1)} Z`

  // ── Build forecast path (extends right from last historical point) ─────────
  let forecastMedianPath = ''
  let forecastBandPath   = ''
  let fcX = 0
  if (forecast && histPoints.length > 0) {
    const lastHist = histPoints[histPoints.length - 1]
    fcX = Math.min(lastHist[0] + CHART_W * 0.20, W - PAD_R - 4)    // ~20% extension
    const fcYMedian = toY(forecast.median, yMin, yMax)
    const fcYP10    = toY(forecast.p10,    yMin, yMax)
    const fcYP90    = toY(forecast.p90,    yMin, yMax)

    forecastMedianPath = `M ${lastHist[0].toFixed(1)} ${lastHist[1].toFixed(1)} L ${fcX.toFixed(1)} ${fcYMedian.toFixed(1)}`

    // Confidence band (p10–p90)
    forecastBandPath = [
      `M ${lastHist[0].toFixed(1)} ${toY(forecast.p10, yMin, yMax).toFixed(1)}`,
      `L ${fcX.toFixed(1)} ${fcYP10.toFixed(1)}`,
      `L ${fcX.toFixed(1)} ${fcYP90.toFixed(1)}`,
      `L ${lastHist[0].toFixed(1)} ${toY(forecast.p90, yMin, yMax).toFixed(1)}`,
      'Z',
    ].join(' ')
  }

  // ── Y-axis labels (4 ticks) ───────────────────────────────────────────────
  const yTicks = [0, 0.33, 0.66, 1].map(t => {
    const price = yMin + t * (yMax - yMin)
    const y = toY(price, yMin, yMax)
    return { price, y }
  })

  // ── X-axis labels (show ~4 evenly spaced dates) ──────────────────────────
  const xLabelCount = Math.min(4, Math.floor(prices.length / 10))
  const xLabels = Array.from({ length: xLabelCount + 1 }, (_, k) => {
    const idx = Math.round(k * (prices.length - 1) / xLabelCount)
    return {
      date: prices[idx]?.date ?? '',
      x: toX(idx, prices.length),
    }
  })

  const currentPrice = prices[prices.length - 1].close
  const currentY     = toY(currentPrice, yMin, yMax)
  const chartId      = `chart-${data.ticker.replace(/[^a-z0-9]/gi, '')}`

  return (
    <div className="w-full relative">
      {/* ── Stats row ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-4 mb-3 px-1">
        <div className="flex items-baseline gap-1.5">
          <span className="font-mono text-lg font-bold text-dark-text-primary tabular-nums">
            {formatPrice(currentPrice)}
          </span>
          <span className={cn(
            'flex items-center gap-0.5 font-mono text-[10px] font-semibold',
            isUp ? 'text-sentinel-green-neon' : 'text-sentinel-red-neon',
          )}>
            {isUp ? <TrendingUp size={9} /> : <TrendingDown size={9} />}
            {isUp ? '+' : ''}{pctChg.toFixed(2)}%
          </span>
          <span className="font-mono text-[9px] text-dark-text-muted/50">
            {data.days}d
          </span>
        </div>

        {forecast && (
          <div className="flex items-center gap-1.5 ml-auto">
            <Zap size={9} className="text-amber-400" />
            <span className="font-mono text-[9px] text-amber-400/80">
              Chronos-2 · {forecast.horizon_days}d forecast · {forecast.directional_bias}
            </span>
          </div>
        )}
      </div>

      {/* ── SVG Chart ──────────────────────────────────────────────────── */}
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ height: 220 }}
        aria-label={`Price chart for ${data.ticker}`}
      >
        <defs>
          {/* Historical gradient fill */}
          <linearGradient id={`${chartId}-fill`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor={lineColor} stopOpacity="0.18" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0.01" />
          </linearGradient>
          {/* Forecast band gradient */}
          <linearGradient id={`${chartId}-fc`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%"   stopColor="#fbbf24" stopOpacity="0.12" />
            <stop offset="100%" stopColor="#fbbf24" stopOpacity="0.04" />
          </linearGradient>
          {/* Clip to chart area */}
          <clipPath id={`${chartId}-clip`}>
            <rect x={PAD_L} y={PAD_T} width={CHART_W} height={CHART_H} />
          </clipPath>
        </defs>

        {/* Grid lines */}
        {yTicks.map(({ y }, i) => (
          <line
            key={i}
            x1={PAD_L} y1={y} x2={W - PAD_R} y2={y}
            stroke="rgba(148,163,210,0.07)" strokeWidth="1"
          />
        ))}

        {/* Area fill */}
        <path
          d={areaPath}
          fill={`url(#${chartId}-fill)`}
          clipPath={`url(#${chartId}-clip)`}
        />

        {/* Forecast confidence band */}
        {forecast && forecastBandPath && (
          <path
            d={forecastBandPath}
            fill={`url(#${chartId}-fc)`}
            clipPath={`url(#${chartId}-clip)`}
          />
        )}

        {/* Historical price line — animated draw */}
        <path
          ref={pathRef}
          d={histPath}
          fill="none"
          stroke={lineColor}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          clipPath={`url(#${chartId}-clip)`}
          style={drawn && pathLen > 0 ? {
            strokeDasharray: pathLen,
            strokeDashoffset: 0,
            transition: 'stroke-dashoffset 1.2s cubic-bezier(0.4,0,0.2,1)',
          } : {
            strokeDasharray: pathLen,
            strokeDashoffset: pathLen,
          }}
        />

        {/* Forecast median dashed line */}
        {forecast && forecastMedianPath && (
          <path
            d={forecastMedianPath}
            fill="none"
            stroke="#fbbf24"
            strokeWidth="1.4"
            strokeDasharray="4 3"
            strokeLinecap="round"
            clipPath={`url(#${chartId}-clip)`}
          />
        )}

        {/* Current price crosshair */}
        <line
          x1={PAD_L} y1={currentY}
          x2={W - PAD_R} y2={currentY}
          stroke={lineColor}
          strokeWidth="0.6"
          strokeDasharray="3 4"
          opacity="0.4"
        />

        {/* Current price dot */}
        {histPoints.length > 0 && (
          <>
            <circle
              cx={histPoints[histPoints.length - 1][0]}
              cy={currentY}
              r="4"
              fill={lineColor}
              opacity="0.25"
            />
            <circle
              cx={histPoints[histPoints.length - 1][0]}
              cy={currentY}
              r="2.5"
              fill={lineColor}
            />
          </>
        )}

        {/* Forecast dot */}
        {forecast && fcX > 0 && (
          <circle
            cx={fcX}
            cy={toY(forecast.median, yMin, yMax)}
            r="2.5"
            fill="#fbbf24"
          />
        )}

        {/* Y-axis labels */}
        {yTicks.map(({ price, y }, i) => (
          <text
            key={i}
            x={W - PAD_R + 4}
            y={y + 3.5}
            fontSize="7.5"
            fill="rgba(139,157,195,0.6)"
            fontFamily="DM Mono, monospace"
          >
            {formatPrice(price)}
          </text>
        ))}

        {/* X-axis labels */}
        {xLabels.map(({ date, x }, i) => (
          <text
            key={i}
            x={x}
            y={H - 4}
            textAnchor="middle"
            fontSize="7.5"
            fill="rgba(139,157,195,0.5)"
            fontFamily="DM Mono, monospace"
          >
            {formatDate(date)}
          </text>
        ))}

        {/* Forecast date label */}
        {forecast && fcX > 0 && (
          <text
            x={fcX}
            y={H - 4}
            textAnchor="middle"
            fontSize="7"
            fill="rgba(251,191,36,0.6)"
            fontFamily="DM Mono, monospace"
          >
            {formatDate(forecast.forecast_date)}
          </text>
        )}
      </svg>

      {/* ── Forecast detail strip ──────────────────────────────────── */}
      {forecast && (
        <motion.div
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="mt-2 grid grid-cols-3 gap-2"
        >
          {[
            { label: 'Bear (P10)', value: formatPrice(forecast.p10),    color: 'text-sentinel-red-neon/70' },
            { label: 'Median',     value: formatPrice(forecast.median),  color: 'text-amber-400' },
            { label: 'Bull (P90)', value: formatPrice(forecast.p90),     color: 'text-sentinel-green-neon/70' },
          ].map(({ label, value, color }) => (
            <div key={label} className="flex flex-col items-center py-1.5 rounded-lg bg-dark-surface border border-dark-border">
              <span className="font-mono text-[8px] uppercase tracking-widest text-dark-text-muted/50">{label}</span>
              <span className={cn('font-mono text-[11px] font-bold tabular-nums mt-0.5', color)}>{value}</span>
            </div>
          ))}
        </motion.div>
      )}
    </div>
  )
}
