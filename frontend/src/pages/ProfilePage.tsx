import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowLeft, BarChart2, Settings, Shield, User } from 'lucide-react'
import { useAuth } from '@/context/AuthContext'
import Logo from '@/components/ui/Logo'
import ProfileInfoTab, { AVATAR_MAP } from '@/components/profile/ProfileInfoTab'
import PreferencesTab from '@/components/profile/PreferencesTab'
import SecurityTab from '@/components/profile/SecurityTab'
import { cn } from '@/lib/utils'

// ── Types ─────────────────────────────────────────────────────────────────────
type Tab = 'profile' | 'preferences' | 'security'

const TABS: { id: Tab; label: string; icon: React.ReactNode; description: string }[] = [
  {
    id: 'profile',
    label: 'Profile',
    icon: <User size={15} />,
    description: 'Avatar & display name',
  },
  {
    id: 'preferences',
    label: 'Preferences',
    icon: <BarChart2 size={15} />,
    description: 'Ticker watchlist',
  },
  {
    id: 'security',
    label: 'Security',
    icon: <Shield size={15} />,
    description: 'Password & account',
  },
]

// ── Avatar display helper ─────────────────────────────────────────────────────
function UserAvatarDisplay({
  avatarId,
  name,
  size = 'lg',
}: {
  avatarId?: number
  name: string
  size?: 'md' | 'lg' | 'xl'
}) {
  const src = avatarId ? AVATAR_MAP[avatarId] : null
  const initials = name
    .split(' ')
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase()

  const sizeClasses = {
    md: 'w-12 h-12 text-base',
    lg: 'w-20 h-20 text-xl',
    xl: 'w-24 h-24 text-2xl',
  }

  return (
    <div
      className={cn(
        'relative rounded-2xl overflow-hidden flex-shrink-0',
        'ring-2 ring-sentinel-green-neon/40',
        sizeClasses[size],
      )}
    >
      {src ? (
        <img
          src={src}
          alt={`${name}'s avatar`}
          className="w-full h-full object-cover object-top"
          draggable={false}
        />
      ) : (
        <div className={cn(
          'w-full h-full flex items-center justify-center',
          'bg-gradient-to-br from-sentinel-green-neon/20 to-sentinel-green-mid/10',
        )}>
          <span className={cn('font-display italic font-bold', 'text-sentinel-green-neon')}>
            {initials}
          </span>
        </div>
      )}
    </div>
  )
}

// ── Page component ─────────────────────────────────────────────────────────────
export default function ProfilePage() {
  const { isAuthenticated, isLoading, user } = useAuth()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState<Tab>('profile')

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      navigate('/login', { replace: true })
    }
  }, [isAuthenticated, isLoading, navigate])

  if (isLoading) {
    return (
      <div className="min-h-dvh bg-dark-surface flex items-center justify-center">
        <div className="btn-spinner" style={{ width: 24, height: 24 }} />
      </div>
    )
  }

  if (!isAuthenticated || !user) return null

  const memberSince = new Intl.DateTimeFormat('en-GB', {
    month: 'short',
    year: 'numeric',
  }).format(new Date(user.created_at))

  return (
    <div className={cn('min-h-dvh flex flex-col', 'bg-dark-bg', 'bg-grid-dark bg-grid-40')}>
      {/* ── Top Nav ───────────────────────────────────────────────────────────── */}
      <header className={cn(
        'sticky top-0 z-30 flex items-center justify-between px-6 py-4',
        'bg-dark-bg/80 backdrop-blur-md',
        'border-b border-dark-border',
      )}>
        <div className="flex items-center gap-4">
          <Link
            to="/dashboard"
            className={cn(
              'flex items-center gap-2 font-mono text-xs uppercase tracking-wider',
              'text-dark-text-secondary',
              'hover:text-sentinel-green-neon',
              'transition-colors',
            )}
          >
            <ArrowLeft size={14} />
            Dashboard
          </Link>
          <span className="text-dark-text-muted select-none">/</span>
          <Logo size="sm" />
        </div>

        <div className="flex items-center gap-3">
          <span className={cn(
            'hidden sm:flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest',
            'text-dark-text-muted',
          )}>
            <Settings size={11} />
            Profile Settings
          </span>
        </div>
      </header>

      {/* ── Main content ──────────────────────────────────────────────────────── */}
      <main className="flex-1 w-full max-w-5xl mx-auto px-4 sm:px-6 py-8 lg:py-12">
        <div className="flex flex-col lg:flex-row gap-6 lg:gap-8">

          {/* ── Sidebar ──────────────────────────────────────────────────────── */}
          <aside className="lg:w-64 flex-shrink-0">
            <div className="lg:sticky lg:top-[5.5rem] flex flex-col gap-4">

              {/* User card */}
              <div className={cn(
                'relative rounded-xl overflow-hidden',
                'bg-dark-card border border-dark-border shadow-card-dark',
              )}>
                <div className="h-[2px] bg-gradient-to-r from-transparent via-sentinel-green-neon/50 to-transparent" />

                {/* Background glow behind avatar */}
                <div className="absolute top-0 left-1/2 -translate-x-1/2 w-32 h-32 rounded-full bg-sentinel-green-neon/5 blur-2xl pointer-events-none" />

                <div className="relative px-5 pt-6 pb-5 flex flex-col items-center text-center gap-3">
                  <UserAvatarDisplay
                    avatarId={user.avatar_id}
                    name={user.fullname}
                    size="xl"
                  />

                  <div className="flex flex-col gap-1">
                    <h2 className="font-display italic text-lg text-dark-text-primary leading-tight">
                      {user.fullname}
                    </h2>
                    <p className="font-mono text-[11px] text-dark-text-muted truncate max-w-[11rem]">
                      {user.email}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 flex-wrap justify-center">
                    <span className={cn(
                      'font-mono text-[9px] uppercase tracking-widest px-2 py-0.5 rounded-full',
                      'bg-sentinel-green-neon/10 text-sentinel-green-neon border border-sentinel-green-neon/20',
                    )}>
                      {user.role}
                    </span>
                    <span className="text-dark-text-muted font-mono text-[9px]">
                      · Since {memberSince}
                    </span>
                  </div>

                  {user.ticker_preferences.length > 0 && (
                    <div className="w-full pt-2 border-t border-dark-border">
                      <p className="font-mono text-[9px] uppercase tracking-widest text-dark-text-muted mb-1.5">
                        Watching
                      </p>
                      <div className="flex flex-wrap gap-1 justify-center">
                        {user.ticker_preferences.slice(0, 6).map((t) => (
                          <span
                            key={t}
                            className={cn(
                              'font-mono text-[9px] px-1.5 py-0.5 rounded',
                              'bg-dark-elevated text-dark-text-secondary',
                            )}
                          >
                            {t}
                          </span>
                        ))}
                        {user.ticker_preferences.length > 6 && (
                          <span className="font-mono text-[9px] text-dark-text-muted">
                            +{user.ticker_preferences.length - 6}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Tab navigation */}
              <nav className={cn('rounded-xl overflow-hidden', 'bg-dark-card border border-dark-border')}>
                {TABS.map((tab, idx) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={cn(
                      'w-full flex items-center gap-3 px-4 py-3.5 transition-all duration-150',
                      'relative text-left group',
                      idx !== TABS.length - 1 && 'border-b border-dark-border',
                      activeTab === tab.id
                        ? 'bg-sentinel-green-neon/6'
                        : 'hover:bg-dark-elevated',
                    )}
                    aria-current={activeTab === tab.id ? 'page' : undefined}
                  >
                    {/* Active left bar */}
                    <AnimatePresence>
                      {activeTab === tab.id && (
                        <motion.div
                          layoutId="activeTabBar"
                          className="absolute left-0 inset-y-0 w-[3px] bg-sentinel-green-neon rounded-r-full"
                          transition={{ type: 'spring', stiffness: 500, damping: 40 }}
                        />
                      )}
                    </AnimatePresence>

                    <span className={cn(
                      'transition-colors',
                      activeTab === tab.id
                        ? 'text-sentinel-green-neon'
                        : 'text-dark-text-muted group-hover:text-dark-text-secondary',
                    )}>
                      {tab.icon}
                    </span>

                    <div className="flex flex-col gap-0.5">
                      <span className={cn(
                        'font-mono text-xs font-medium',
                        activeTab === tab.id
                          ? 'text-dark-text-primary'
                          : 'text-dark-text-secondary',
                      )}>
                        {tab.label}
                      </span>
                      <span className="font-mono text-[9px] text-dark-text-muted">
                        {tab.description}
                      </span>
                    </div>
                  </button>
                ))}
              </nav>
            </div>
          </aside>

          {/* ── Content area ─────────────────────────────────────────────────── */}
          <div className="flex-1 min-w-0">
            <div className={cn('rounded-xl', 'bg-dark-card border border-dark-border shadow-card-dark')}>
              <div className="h-[2px] rounded-t-xl bg-gradient-to-r from-transparent via-sentinel-green-neon/50 to-transparent" />

              {/* Tab heading */}
              <div className="px-7 pt-7 pb-5 border-b border-dark-border">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={activeTab}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    transition={{ duration: 0.18 }}
                  >
                    <h1 className="font-display italic text-2xl text-dark-text-primary leading-tight">
                      {activeTab === 'profile'     && 'Profile & Avatar'}
                      {activeTab === 'preferences' && 'Market Preferences'}
                      {activeTab === 'security'    && 'Security Settings'}
                    </h1>
                    <p className="font-sans text-xs text-dark-text-secondary mt-1">
                      {activeTab === 'profile'     && 'Update your display name and choose your analyst persona.'}
                      {activeTab === 'preferences' && 'Configure the instruments your intelligence feed monitors.'}
                      {activeTab === 'security'    && 'Manage your password and review account details.'}
                    </p>
                  </motion.div>
                </AnimatePresence>
              </div>

              {/* Tab content */}
              <div className="px-7 py-7">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={activeTab}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }}
                    transition={{ duration: 0.22, ease: 'easeOut' }}
                  >
                    {activeTab === 'profile'     && <ProfileInfoTab />}
                    {activeTab === 'preferences' && <PreferencesTab />}
                    {activeTab === 'security'    && <SecurityTab />}
                  </motion.div>
                </AnimatePresence>
              </div>
            </div>

            <p className="mt-5 text-center font-mono text-xs text-dark-text-muted">
              End-to-end encrypted · bcrypt · JWT · Changes apply immediately
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}
