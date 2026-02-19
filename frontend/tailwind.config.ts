import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        serif: ['"DM Serif Display"', 'Georgia', 'serif'],
        sans: ['"DM Sans"', 'system-ui', 'sans-serif'],
        mono: ['"DM Mono"', '"Fira Code"', 'monospace'],
      },
      colors: {
        sentinel: {
          'green-neon': '#00e87b',
          'green-mid': '#00c06a',
          'green-dark': '#16a34a',
          'green-forest': '#166534',
          'red-neon': '#ff2d4a',
          'red-mid': '#ef4444',
          'red-dark': '#dc2626',
          'red-deep': '#991b1b',
          gold: '#f5a623',
          'gold-dark': '#d97706',
          blue: '#4d9cff',
          'blue-dark': '#2563eb',
        },
        dark: {
          void: '#020510',
          deep: '#040916',
          bg: '#060b18',
          surface: '#0d1425',
          card: '#131c33',
          elevated: '#1a2540',
          border: 'rgba(148,163,210,0.10)',
          'border-subtle': 'rgba(148,163,210,0.06)',
          'text-primary': '#eef2ff',
          'text-secondary': '#8b9dc3',
          'text-muted': '#5a6a8a',
        },
      },
      animation: {
        'ticker-scroll': 'tickerScroll 40s linear infinite',
        'pulse-dot': 'pulseDot 2s cubic-bezier(0.4,0,0.6,1) infinite',
        'blink-cursor': 'blinkCursor 1.1s step-end infinite',
        'price-up': 'priceUp 0.4s ease-out',
        'price-down': 'priceDown 0.4s ease-out',
        'glow-green': 'glowGreen 2.5s ease-in-out infinite alternate',
        'glow-red': 'glowRed 2.5s ease-in-out infinite alternate',
        'scan-line': 'scanLine 4s ease-in-out infinite',
        'float-y': 'floatY 6s ease-in-out infinite',
        'shimmer': 'shimmer 2s linear infinite',
        'fade-in-up': 'fadeInUp 0.5s ease-out forwards',
        'slide-in-right': 'slideInRight 0.4s ease-out forwards',
        'agent-flow': 'agentFlow 3s ease-in-out infinite',
      },
      keyframes: {
        tickerScroll: {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
        pulseDot: {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.4', transform: 'scale(0.85)' },
        },
        blinkCursor: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0' },
        },
        priceUp: {
          '0%': { color: '#00e87b', transform: 'translateY(-4px)' },
          '100%': { color: 'inherit', transform: 'translateY(0)' },
        },
        priceDown: {
          '0%': { color: '#ff2d4a', transform: 'translateY(4px)' },
          '100%': { color: 'inherit', transform: 'translateY(0)' },
        },
        glowGreen: {
          '0%': { textShadow: '0 0 8px rgba(0,232,123,0.4)' },
          '100%': { textShadow: '0 0 24px rgba(0,232,123,0.8), 0 0 48px rgba(0,232,123,0.3)' },
        },
        glowRed: {
          '0%': { textShadow: '0 0 8px rgba(255,45,74,0.4)' },
          '100%': { textShadow: '0 0 24px rgba(255,45,74,0.8), 0 0 48px rgba(255,45,74,0.3)' },
        },
        scanLine: {
          '0%': { top: '-2px', opacity: '0' },
          '10%': { opacity: '1' },
          '90%': { opacity: '1' },
          '100%': { top: '100%', opacity: '0' },
        },
        floatY: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% center' },
          '100%': { backgroundPosition: '200% center' },
        },
        fadeInUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(24px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        agentFlow: {
          '0%, 100%': { opacity: '0.3' },
          '50%': { opacity: '1' },
        },
      },
      boxShadow: {
        'glow-green-sm': '0 0 12px rgba(0,232,123,0.25)',
        'glow-green-md': '0 0 24px rgba(0,232,123,0.3)',
        'glow-green-lg': '0 0 48px rgba(0,232,123,0.2)',
        'glow-red-sm': '0 0 12px rgba(255,45,74,0.25)',
        'glow-red-md': '0 0 24px rgba(255,45,74,0.3)',
        'card-dark': '0 4px 40px rgba(0,0,0,0.5), 0 1px 0 rgba(148,163,210,0.04) inset',
        'input-focus-green': '0 0 0 2px rgba(0,232,123,0.25)',
        'input-focus-red': '0 0 0 2px rgba(255,45,74,0.25)',
      },
      backgroundImage: {
        'grid-dark': 'radial-gradient(circle, rgba(139,157,195,0.10) 1px, transparent 1px)',
        'gradient-sentinel': 'linear-gradient(135deg, #00e87b 0%, #00c06a 50%, #16a34a 100%)',
        'shimmer-gradient': 'linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.08) 50%, transparent 100%)',
      },
      backgroundSize: {
        'grid-30': '30px 30px',
        'grid-40': '40px 40px',
      },
    },
  },
  plugins: [],
}

export default config
