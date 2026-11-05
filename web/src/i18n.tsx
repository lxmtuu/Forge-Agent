import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'

export type Language = 'vi' | 'en'
export type Translate = (vi: string, en: string) => string

interface LanguageContextValue {
  language: Language
  setLanguage: (next: Language) => void
  t: Translate
}

const LanguageContext = createContext<LanguageContextValue | null>(null)
const STORAGE_KEY = 'forge-language'

function initialLanguage(): Language {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'vi'
  } catch {
    return 'vi'
  }
}

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [language, setLanguageState] = useState<Language>(initialLanguage)

  useEffect(() => {
    document.documentElement.lang = language
  }, [language])

  const value = useMemo<LanguageContextValue>(() => ({
    language,
    setLanguage: (next) => {
      setLanguageState(next)
      try { localStorage.setItem(STORAGE_KEY, next) } catch { /* private browsing may deny storage */ }
    },
    t: (vi, en) => language === 'en' ? en : vi,
  }), [language])

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export function useI18n(): LanguageContextValue {
  const value = useContext(LanguageContext)
  if (!value) throw new Error('useI18n must be used inside LanguageProvider')
  return value
}
