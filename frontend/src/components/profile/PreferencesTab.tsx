/**
 * PreferencesTab — curated asset watchlist manager.
 *
 * Security: no free-text input — all tickers come from a fixed catalogue.
 * Users toggle assets on/off; the list is saved to the backend via PATCH /auth/me.
 */
import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { AlertCircle, CheckCircle2, Check, X } from 'lucide-react'
import { useAuth, parseApiError } from '@/context/AuthContext'
import Button from '@/components/ui/Button'
import { cn } from '@/lib/utils'

// ── Full asset catalogue ───────────────────────────────────────────────────────
const CATALOGUE = [
  {
    group: 'Crypto', color: '#f59e0b',
    assets: [
      { ticker: 'BTC-USD',   name: 'Bitcoin'   },
      { ticker: 'ETH-USD',   name: 'Ethereum'  },
      { ticker: 'SOL-USD',   name: 'Solana'    },
      { ticker: 'BNB-USD',   name: 'BNB'       },
      { ticker: 'XRP-USD',   name: 'XRP'       },
      { ticker: 'ADA-USD',   name: 'Cardano'   },
      { ticker: 'AVAX-USD',  name: 'Avalanche' },
      { ticker: 'DOGE-USD',  name: 'Dogecoin'  },
      { ticker: 'DOT-USD',   name: 'Polkadot'  },
      { ticker: 'LINK-USD',  name: 'Chainlink' },
      { ticker: 'MATIC-USD', name: 'Polygon'   },
      { ticker: 'UNI-USD',   name: 'Uniswap'   },
      { ticker: 'ATOM-USD',  name: 'Cosmos'    },
      { ticker: 'LTC-USD',   name: 'Litecoin'  },
      { ticker: 'BCH-USD',   name: 'Bitcoin Cash' },
      { ticker: 'ARB-USD',   name: 'Arbitrum'  },
      { ticker: 'OP-USD',    name: 'Optimism'  },
      { ticker: 'INJ-USD',   name: 'Injective' },
      { ticker: 'SUI20947-USD', name: 'Sui'   },
      { ticker: 'TIA-USD',   name: 'Celestia'  },
    ],
  },
  {
    group: 'US Equities', color: '#60a5fa',
    assets: [
      { ticker: 'AAPL',  name: 'Apple'         },
      { ticker: 'NVDA',  name: 'NVIDIA'         },
      { ticker: 'MSFT',  name: 'Microsoft'      },
      { ticker: 'TSLA',  name: 'Tesla'          },
      { ticker: 'GOOGL', name: 'Alphabet'       },
      { ticker: 'META',  name: 'Meta'           },
      { ticker: 'AMZN',  name: 'Amazon'         },
      { ticker: 'NFLX',  name: 'Netflix'        },
      { ticker: 'AMD',   name: 'AMD'            },
      { ticker: 'INTC',  name: 'Intel'          },
      { ticker: 'JPM',   name: 'JPMorgan'       },
      { ticker: 'BAC',   name: 'Bank of America'},
      { ticker: 'GS',    name: 'Goldman Sachs'  },
      { ticker: 'MS',    name: 'Morgan Stanley' },
      { ticker: 'BRK-B', name: 'Berkshire B'   },
      { ticker: 'XOM',   name: 'ExxonMobil'    },
      { ticker: 'CVX',   name: 'Chevron'        },
      { ticker: 'JNJ',   name: 'Johnson & J.'  },
      { ticker: 'V',     name: 'Visa'           },
      { ticker: 'MA',    name: 'Mastercard'     },
    ],
  },
  {
    group: 'Indices & ETFs', color: '#c084fc',
    assets: [
      { ticker: 'SPY',   name: 'S&P 500 ETF'   },
      { ticker: 'QQQ',   name: 'Nasdaq 100'     },
      { ticker: 'IWM',   name: 'Russell 2000'   },
      { ticker: 'DIA',   name: 'Dow Jones ETF'  },
      { ticker: '^VIX',  name: 'VIX Volatility' },
      { ticker: 'TLT',   name: '20Y US Bonds'   },
      { ticker: 'GLD',   name: 'Gold ETF'       },
      { ticker: 'SLV',   name: 'Silver ETF'     },
      { ticker: 'EFA',   name: 'EAFE (Intl Dev)'},
      { ticker: 'EEM',   name: 'Emerging Mkts'  },
      { ticker: 'VTI',   name: 'Total US Mkt'   },
      { ticker: 'ARKK',  name: 'ARK Innovation' },
    ],
  },
  {
    group: 'Commodities', color: '#fb923c',
    assets: [
      { ticker: 'GC=F',  name: 'Gold'           },
      { ticker: 'SI=F',  name: 'Silver'         },
      { ticker: 'CL=F',  name: 'Crude Oil (WTI)'},
      { ticker: 'BZ=F',  name: 'Brent Crude'    },
      { ticker: 'NG=F',  name: 'Natural Gas'    },
      { ticker: 'HG=F',  name: 'Copper'         },
      { ticker: 'PL=F',  name: 'Platinum'       },
      { ticker: 'PA=F',  name: 'Palladium'      },
      { ticker: 'ZC=F',  name: 'Corn'           },
      { ticker: 'ZW=F',  name: 'Wheat'          },
    ],
  },
  {
    group: 'FX & Rates', color: '#34d399',
    assets: [
      { ticker: 'DX-Y.NYB', name: 'USD Index'  },
      { ticker: 'EUR=X',    name: 'EUR / USD'  },
      { ticker: 'JPY=X',    name: 'USD / JPY'  },
      { ticker: 'GBP=X',    name: 'GBP / USD'  },
      { ticker: 'CHF=X',    name: 'USD / CHF'  },
      { ticker: 'AUD=X',    name: 'AUD / USD'  },
      { ticker: 'CAD=X',    name: 'USD / CAD'  },
      { ticker: 'CNY=X',    name: 'USD / CNY'  },
      { ticker: '^TNX',     name: '10Y US Yield'},
      { ticker: '^TYX',     name: '30Y US Yield'},
    ],
  },
] as const

const MAX_TICKERS = 20

export default function PreferencesTab() {
  const { user, updateProfile } = useAuth()
  const [tickers, setTickers] = useState<string[]>(user?.ticker_preferences ?? [])
  const [serverError, setServerError] = useState('')
  const [saved, setSaved] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [activeGroup, setActiveGroup] = useState<string>(CATALOGUE[0].group)

  const toggle = (ticker: string) => {
    setTickers(prev => {
      if (prev.includes(ticker)) return prev.filter(t => t !== ticker)
      if (prev.length >= MAX_TICKERS) return prev   // silently ignore when full
      return [...prev, ticker]
    })
  }

  const remove = (ticker: string) => setTickers(prev => prev.filter(t => t !== ticker))

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
  const isFull = tickers.length >= MAX_TICKERS

  return (
    <div className="flex flex-col gap-6">

      {/* Header */}
      <div>
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-sentinel-green-neon flex items-center gap-2">
          <span className="opacity-60">&gt;_</span> WATCHLIST_PREFERENCES
        </p>
        <p className="font-sans text-xs text-dark-text-muted mt-1">
          Select up to {MAX_TICKERS} instruments to monitor. Click any asset to toggle it on or off.
        </p>
      </div>

      {/* Server error */}
      <AnimatePresence>
        {serverError && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            role="alert"
            className="flex items-start gap-3 px-4 py-3 rounded-md bg-sentinel-red-neon/8 border border-sentinel-red-neon/20"
          >
            <AlertCircle size={14} className="mt-0.5 flex-shrink-0 text-sentinel-red-neon" />
            <p className="font-mono text-xs text-sentinel-red-neon">{serverError}</p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Current watchlist chips */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <p className="font-mono text-[10px] uppercase tracking-widest text-dark-text-secondary">
            Your Watchlist ({tickers.length}/{MAX_TICKERS})
          </p>
          {isFull && (
            <span className="font-mono text-[9px] text-amber-400/80 uppercase tracking-widest">
              Limit reached
            </span>
          )}
        </div>

        <div className={cn(
          'min-h-[2.5rem] flex flex-wrap gap-1.5 p-2.5 rounded-lg border',
          'bg-dark-surface border-dark-border',
        )}>
          {tickers.length === 0 ? (
            <span className="font-mono text-[10px] text-dark-text-muted/40 italic self-center ml-1">
              No assets selected — toggle assets below
            </span>
          ) : (
            <AnimatePresence initial={false}>
              {tickers.map(t => (
                <motion.span
                  key={t}
                  layout
                  initial={{ scale: 0.8, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0.8, opacity: 0 }}
                  transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md font-mono text-[10px] font-medium tracking-wider bg-sentinel-green-neon/10 text-sentinel-green-neon border border-sentinel-green-neon/20"
                >
                  {t}
                  <button
                    type="button"
                    onClick={() => remove(t)}
                    className="hover:text-sentinel-red-neon transition-colors rounded-sm"
                    aria-label={`Remove ${t}`}
                  >
                    <X size={9} strokeWidth={2.5} />
                  </button>
                </motion.span>
              ))}
            </AnimatePresence>
          )}
        </div>
      </div>

      <div className="h-px bg-dark-border" />

      {/* Catalogue */}
      <div className="flex flex-col gap-4">
        <p className="font-mono text-[10px] uppercase tracking-widest text-dark-text-muted">
          Asset Catalogue
        </p>

        {/* Group tabs */}
        <div className="flex gap-1 flex-wrap">
          {CATALOGUE.map(cat => (
            <button
              key={cat.group}
              onClick={() => setActiveGroup(cat.group)}
              className={cn(
                'px-2.5 py-1 rounded-md font-mono text-[9px] uppercase tracking-widest transition-all duration-150',
                activeGroup === cat.group
                  ? 'text-dark-void font-bold'
                  : 'bg-dark-surface border border-dark-border text-dark-text-muted hover:text-dark-text-secondary',
              )}
              style={activeGroup === cat.group ? { backgroundColor: cat.color, border: `1px solid ${cat.color}` } : {}}
            >
              {cat.group}
            </button>
          ))}
        </div>

        {/* Asset grid */}
        <AnimatePresence mode="wait">
          {CATALOGUE.filter(c => c.group === activeGroup).map(cat => (
            <motion.div
              key={cat.group}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.15 }}
              className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2"
            >
              {cat.assets.map(({ ticker, name }) => {
                const selected = tickers.includes(ticker)
                const disabled = isFull && !selected
                return (
                  <motion.button
                    key={ticker}
                    type="button"
                    disabled={disabled}
                    onClick={() => toggle(ticker)}
                    whileHover={disabled ? {} : { scale: 1.03 }}
                    whileTap={disabled ? {} : { scale: 0.97 }}
                    className={cn(
                      'relative flex items-center gap-2.5 px-3 py-2.5 rounded-xl border text-left',
                      'transition-all duration-150 overflow-hidden',
                      selected
                        ? 'bg-sentinel-green-neon/10 border-sentinel-green-neon/40'
                        : 'bg-dark-elevated border-dark-border hover:border-dark-text-muted/25',
                      disabled && 'opacity-40 cursor-not-allowed',
                    )}
                    aria-pressed={selected}
                  >
                    {/* Category colour bar */}
                    <div
                      className="absolute left-0 top-0 w-[3px] h-full rounded-l-xl"
                      style={{ backgroundColor: cat.color, opacity: selected ? 1 : 0.3 }}
                    />

                    <div className="flex flex-col min-w-0 pl-1">
                      <span className={cn(
                        'font-mono text-[10px] font-bold truncate',
                        selected ? 'text-sentinel-green-neon' : 'text-dark-text-primary',
                      )}>
                        {ticker}
                      </span>
                      <span className="font-mono text-[8px] text-dark-text-muted truncate leading-none mt-0.5">
                        {name}
                      </span>
                    </div>

                    {selected && (
                      <div className="ml-auto flex-shrink-0 w-4 h-4 rounded-full bg-sentinel-green-neon/20 flex items-center justify-center">
                        <Check size={8} className="text-sentinel-green-neon" strokeWidth={3} />
                      </div>
                    )}
                  </motion.button>
                )
              })}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

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
            <><CheckCircle2 size={14} /><span>Saved</span></>
          ) : (
            <span>Save Watchlist</span>
          )}
        </Button>
        {!hasChanges && !saved && (
          <span className="font-mono text-[10px] text-dark-text-muted">No changes to save</span>
        )}
      </div>
    </div>
  )
}
