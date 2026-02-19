import { useState, useRef, KeyboardEvent } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertCircle, CheckCircle2, Plus, X, Zap } from 'lucide-react'
import { useAuth, parseApiError } from '@/context/AuthContext'
import Button from '@/components/ui/Button'
import { cn } from '@/lib/utils'

// ── Popular tickers grouped by asset class ─────────────────────────────────────
const POPULAR = [
  { group: 'Crypto',      tickers: ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD'] },
  { group: 'Indices',     tickers: ['SPY', 'QQQ', '^GSPC', '^DJI', '^VIX'] },
  { group: 'Tech',        tickers: ['AAPL', 'NVDA', 'MSFT', 'TSLA', 'GOOGL', 'META', 'AMZN'] },
  { group: 'Commodities', tickers: ['GC=F', 'CL=F', 'SI=F', 'NG=F'] },
  { group: 'FX',          tickers: ['EUR=X', 'JPY=X', 'GBP=X', 'CHF=X'] },
]

const MAX_TICKERS = 20

// Matches backend: [A-Z0-9^=.-]{1,12}
const TICKER_RE = /^[A-Z0-9^=.\-]{1,12}$/

export default function PreferencesTab() {
  const { user, updateProfile } = useAuth()

  const [tickers, setTickers] = useState<string[]>(user?.ticker_preferences ?? [])
  const [input, setInput]     = useState('')
  const [inputError, setInputError] = useState('')
  const [serverError, setServerError] = useState('')
  const [saved, setSaved]     = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  // ── Ticker management ────────────────────────────────────────────────────────
  const addTicker = (raw: string) => {
    const t = raw.trim().toUpperCase()
    if (!t) return
    if (!TICKER_RE.test(t)) {
      setInputError(`"${t}" is not a valid ticker symbol`)
      return
    }
    if (tickers.includes(t)) {
      setInputError(`${t} is already in your list`)
      return
    }
    if (tickers.length >= MAX_TICKERS) {
      setInputError(`Maximum ${MAX_TICKERS} tickers allowed`)
      return
    }
    setTickers((prev) => [...prev, t])
    setInput('')
    setInputError('')
  }

  const removeTicker = (t: string) => setTickers((prev) => prev.filter((x) => x !== t))

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',' || e.key === ' ') {
      e.preventDefault()
      addTicker(input)
    }
    if (e.key === 'Backspace' && input === '' && tickers.length > 0) {
      setTickers((prev) => prev.slice(0, -1))
    }
  }

  // ── Save ─────────────────────────────────────────────────────────────────────
  const handleSave = async () => {
    setServerError('')
    setSaved(false)
    setIsSaving(true)
    try {
      await updateProfile({ ticker_preferences: tickers })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (err) {
      setServerError(parseApiError(err))
    } finally {
      setIsSaving(false)
    }
  }

  const hasChanges = JSON.stringify(tickers) !== JSON.stringify(user?.ticker_preferences ?? [])

  return (
    <div className="flex flex-col gap-8">
      {/* Header */}
      <div>
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-sentinel-green-neon flex items-center gap-2">
          <span className="opacity-60">&gt;_</span> TICKER_PREFERENCES
        </p>
        <p className="font-sans text-xs text-dark-text-muted mt-1">
          Add up to {MAX_TICKERS} instruments to personalise your intelligence feed.
          Accepts stocks, ETFs, crypto pairs, indices, FX, and commodities.
        </p>
      </div>

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

      {/* Tag input area */}
      <div className="flex flex-col gap-2">
        <label className="font-mono text-[11px] font-medium uppercase tracking-[0.18em] flex items-center gap-2 text-dark-text-secondary">
          <span className="opacity-60 text-sentinel-green-neon">&gt;_</span>
          Watchlist ({tickers.length}/{MAX_TICKERS})
        </label>

        {/* Tag chip container + input */}
        <div
          onClick={() => inputRef.current?.focus()}
          className={cn(
            'min-h-[3.5rem] flex flex-wrap gap-2 px-3 py-2.5 rounded-md border cursor-text',
            'transition-all duration-200',
            'bg-dark-surface border-dark-border',
            'focus-within:border-sentinel-green-neon focus-within:shadow-[0_0_0_3px_rgba(0,232,123,0.15)]',
            inputError && '!border-sentinel-red-neon',
            inputError && '!shadow-[0_0_0_3px_rgba(255,45,74,0.15)]',
          )}
        >
          <AnimatePresence initial={false}>
            {tickers.map((t) => (
              <motion.span
                key={t}
                layout
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.8, opacity: 0 }}
                transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                className={cn(
                  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md',
                  'font-mono text-[11px] font-medium tracking-wider',
                  'bg-sentinel-green-neon/10 text-sentinel-green-neon border border-sentinel-green-neon/20',
                )}
              >
                {t}
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); removeTicker(t) }}
                  className={cn(
                    'rounded-sm transition-colors',
                    'hover:text-dark-text-primary',
                  )}
                  aria-label={`Remove ${t}`}
                >
                  <X size={10} strokeWidth={2.5} />
                </button>
              </motion.span>
            ))}
          </AnimatePresence>

          {tickers.length < MAX_TICKERS && (
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => {
                setInput(e.target.value.toUpperCase())
                setInputError('')
              }}
              onKeyDown={handleKeyDown}
              onBlur={() => { if (input) addTicker(input) }}
              placeholder={tickers.length === 0 ? 'Type a ticker and press Enter…' : ''}
              className={cn(
                'flex-1 min-w-[140px] bg-transparent outline-none',
                'font-mono text-sm text-dark-text-primary',
                'placeholder:text-dark-text-muted placeholder:italic',
              )}
              aria-label="Add ticker symbol"
            />
          )}
        </div>

        {inputError ? (
          <p className="flex items-center gap-1.5 text-xs font-mono text-sentinel-red-neon">
            <span aria-hidden>!</span>{inputError}
          </p>
        ) : (
          <p className="text-xs font-mono text-dark-text-muted">
            Press <kbd className="px-1 py-0.5 rounded bg-dark-elevated font-mono text-[10px]">Enter</kbd>,{' '}
            <kbd className="px-1 py-0.5 rounded bg-dark-elevated font-mono text-[10px]">Space</kbd> or{' '}
            <kbd className="px-1 py-0.5 rounded bg-dark-elevated font-mono text-[10px]">,</kbd> to add.
            Backspace removes the last entry.
          </p>
        )}
      </div>

      {/* Divider */}
      <div className="h-px bg-dark-border" />

      {/* Quick-add popular tickers */}
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <Zap size={13} className="text-dark-text-secondary" />
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-dark-text-secondary">
            Quick Add
          </p>
        </div>

        {POPULAR.map(({ group, tickers: suggestions }) => (
          <div key={group} className="flex flex-col gap-2">
            <p className="font-mono text-[10px] uppercase tracking-widest text-dark-text-muted">
              {group}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((t) => {
                const already = tickers.includes(t)
                const full    = tickers.length >= MAX_TICKERS && !already
                return (
                  <button
                    key={t}
                    type="button"
                    disabled={full}
                    onClick={() => already ? removeTicker(t) : addTicker(t)}
                    className={cn(
                      'inline-flex items-center gap-1 px-2.5 py-1 rounded-md border transition-all duration-150',
                      'font-mono text-[10px] tracking-wider',
                      already
                        ? 'bg-sentinel-green-neon/12 border-sentinel-green-neon/30 text-sentinel-green-neon'
                        : 'bg-dark-elevated border-dark-border text-dark-text-secondary hover:border-sentinel-green-neon/40 hover:text-sentinel-green-neon',
                      full && 'opacity-40 cursor-not-allowed',
                    )}
                    aria-pressed={already}
                    aria-label={already ? `Remove ${t}` : `Add ${t}`}
                  >
                    {already ? <X size={9} strokeWidth={2.5} /> : <Plus size={9} strokeWidth={2.5} />}
                    {t}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Divider */}
      <div className="h-px bg-dark-border" />

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button
          type="button"
          variant="primary"
          size="md"
          isLoading={isSaving}
          isSuccess={saved}
          disabled={!hasChanges}
          onClick={handleSave}
        >
          {saved ? (
            <>
              <CheckCircle2 size={14} />
              <span>Saved</span>
            </>
          ) : (
            <span>Save Preferences</span>
          )}
        </Button>
        {!hasChanges && !saved && (
          <span className="font-mono text-[10px] text-dark-text-muted">
            No changes to save
          </span>
        )}
      </div>
    </div>
  )
}
