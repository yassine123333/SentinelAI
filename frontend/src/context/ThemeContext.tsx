import { createContext, useContext, useEffect, type ReactNode } from 'react'

interface ThemeContextValue {
  theme: 'dark'
  isDark: true
}

const ThemeContext = createContext<ThemeContextValue>({ theme: 'dark', isDark: true })

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.classList.add('dark')
  }, [])

  return (
    <ThemeContext.Provider value={{ theme: 'dark', isDark: true }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext)
}
