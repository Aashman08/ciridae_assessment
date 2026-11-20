import { useState } from 'react'
import type { ReactNode } from 'react'
import { AssistantContext } from '../lib/assistant'
import type { AssistantView } from '../lib/assistant'

/** Holds what the side pane is showing, so any page can open it. */
export function AssistantProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<AssistantView | null>(null)
  return <AssistantContext value={{ view, show: setView, close: () => setView(null) }}>{children}</AssistantContext>
}
