import { useState } from 'react'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'theme'

function current(): Theme {
  const chosen = document.documentElement.dataset.theme
  if (chosen === 'light' || chosen === 'dark') return chosen
  // Nothing chosen yet, so report what the system setting is showing.
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** The theme on screen, and a way to change it that sticks between visits. */
export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setCurrent] = useState<Theme>(current)

  function setTheme(next: Theme) {
    document.documentElement.dataset.theme = next
    setCurrent(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Storage can be blocked. The choice then lasts until the page reloads.
    }
  }

  return [theme, setTheme]
}
