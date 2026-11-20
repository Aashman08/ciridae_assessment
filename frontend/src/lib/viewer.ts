import { createContext, useContext } from 'react'

// Who is signed in. There is no sign-in in the demo, so the sidebar lets you
// switch between the people it was built for. What a person can see
// follows from who they are, as it would with a real sign-in.
export interface Viewer {
  key: 'rachel' | 'luis' | 'tasha'
  name: string
  role: string
  /** Set for someone who only sees their own jobs. Sent to the API as `owner`. */
  owner?: string
  /** What they see, said in a few words under their name. */
  sees: string
  /** The heading over the navigation: exactly what every page below it covers. */
  scope: string
  /** Whether they can change how issues are detected. */
  managesChecks: boolean
  /** What their first screen is about: the ledger, every job's problems, or their own to-do list. */
  home: 'finance' | 'operations' | 'own'
}

export const VIEWERS: Viewer[] = [
  {
    key: 'rachel',
    name: 'Rachel Kim',
    role: 'Finance',
    sees: 'Finance, every job',
    scope: 'All Harborstone jobs',
    managesChecks: true,
    home: 'finance',
  },
  {
    key: 'luis',
    name: 'Luis Ortega',
    role: 'Operations',
    sees: 'Operations, every job',
    scope: 'All Harborstone jobs',
    managesChecks: false,
    home: 'operations',
  },
  {
    key: 'tasha',
    name: 'Tasha Green',
    role: 'Operations',
    owner: 'Tasha Green',
    sees: 'Operations, her jobs only',
    scope: 'Tasha Green\'s jobs',
    managesChecks: false,
    home: 'own',
  },
]

export const ViewerContext = createContext<{ viewer: Viewer; setViewer: (viewer: Viewer) => void } | null>(null)

export function useViewer() {
  const context = useContext(ViewerContext)
  if (!context) throw new Error('useViewer must be used inside ViewerProvider')
  return context
}
