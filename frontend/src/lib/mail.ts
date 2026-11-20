import { useSyncExternalStore } from 'react'
import gmailLogo from '../assets/logos/gmail.svg'
import outlookLogo from '../assets/logos/outlook.svg'

/** Where "Send" on a drafted message opens it. */
export interface MailApp {
  key: 'gmail' | 'outlook' | 'default'
  name: string
  /** The account's own logo, so it is recognised at a glance. None for the computer's mail app. */
  logo?: string
  /** What Send does with this account, in the words shown on the Connectors page. */
  does: string
}

export const MAIL_APPS: MailApp[] = [
  { key: 'gmail', name: 'Gmail', logo: gmailLogo, does: 'Send opens the message in Gmail, addressed and written, for you to send' },
  { key: 'outlook', name: 'Outlook', logo: outlookLogo, does: 'Send opens the message in Outlook on the web, addressed and written, for you to send' },
]

/** Used until an account is connected: whatever this computer opens email links with. */
export const DEFAULT_MAIL: MailApp = {
  key: 'default',
  name: 'your mail app',
  does: "Send opens the message in this computer's own mail app",
}

const STORAGE_KEY = 'mail-app'
const listeners = new Set<() => void>()

function read(): MailApp['key'] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored === 'gmail' || stored === 'outlook' ? stored : 'default'
  } catch {
    return 'default'
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** The account messages are sent with, and a way to change it that sticks between visits. */
export function useMailApp(): [MailApp, (key: MailApp['key']) => void] {
  const key = useSyncExternalStore(subscribe, read)

  function choose(next: MailApp['key']) {
    try {
      if (next === 'default') localStorage.removeItem(STORAGE_KEY)
      else localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // Storage can be blocked. Sending then falls back to the computer's own mail app.
    }
    listeners.forEach((listener) => listener())
  }

  return [MAIL_APPS.find((app) => app.key === key) ?? DEFAULT_MAIL, choose]
}

/** The address that opens a new message in the chosen account, already filled in. */
export function composeUrl(app: MailApp['key'], message: { to: string; cc?: string; subject: string; body: string }): string {
  const to = encodeURIComponent(message.to)
  const cc = message.cc ? encodeURIComponent(message.cc) : ''
  const subject = encodeURIComponent(message.subject)
  const body = encodeURIComponent(message.body)
  if (app === 'gmail') return `https://mail.google.com/mail/?view=cm&fs=1&to=${to}${cc && `&cc=${cc}`}&su=${subject}&body=${body}`
  if (app === 'outlook') return `https://outlook.office.com/mail/deeplink/compose?to=${to}${cc && `&cc=${cc}`}&subject=${subject}&body=${body}`
  return `mailto:${to}?${cc && `cc=${cc}&`}subject=${subject}&body=${body}`
}
