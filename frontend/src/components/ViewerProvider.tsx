import { useState } from 'react'
import type { ReactNode } from 'react'
import { ViewerContext, VIEWERS } from '../lib/viewer'
import type { Viewer } from '../lib/viewer'

const STORAGE_KEY = 'viewer'

function remembered(): Viewer {
  try {
    const key = localStorage.getItem(STORAGE_KEY)
    return VIEWERS.find((v) => v.key === key) ?? VIEWERS[0]
  } catch {
    return VIEWERS[0]
  }
}

/** Holds who is looking, and remembers the choice between visits. */
export function ViewerProvider({ children }: { children: ReactNode }) {
  const [viewer, setCurrent] = useState<Viewer>(remembered)

  function setViewer(next: Viewer) {
    setCurrent(next)
    try {
      localStorage.setItem(STORAGE_KEY, next.key)
    } catch {
      // Storage can be blocked. The choice then lasts until the page reloads.
    }
  }

  return <ViewerContext value={{ viewer, setViewer }}>{children}</ViewerContext>
}
