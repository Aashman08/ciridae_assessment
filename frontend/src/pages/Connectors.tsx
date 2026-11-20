import { useQuery } from '@tanstack/react-query'
import { HardHat, Landmark, Users } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button, Card, CardHead, Loaded, PageHead } from '../components/ui'
import { api } from '../lib/api'
import type { SourceSystem } from '../lib/api'
import { dateTime } from '../lib/format'
import { DEFAULT_MAIL, MAIL_APPS, useMailApp } from '../lib/mail'

// Harborstone's brief does not name the products behind its three systems, so each gets a plain mark.
const SYSTEMS: Record<SourceSystem['system'], { name: string; holds: string; icon: LucideIcon }> = {
  crm: { name: 'CRM', holds: 'Customers, contacts, opportunities and bids', icon: Users },
  project: { name: 'Project system', holds: 'Projects, budgets, cost entries and the people on each job', icon: HardHat },
  accounting: { name: 'Accounting', holds: 'Customer invoices, payments, vendor bills and the ledger', icon: Landmark },
}

/** A connector's name with its mark in front, the same size for every row. */
function Named({ mark, children }: { mark: ReactNode; children: ReactNode }) {
  return (
    <span className="flex items-center gap-3 font-medium">
      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-raised ring-1 ring-hair ring-inset">{mark}</span>
      {children}
    </span>
  )
}

function Mark({ icon: Icon }: { icon: LucideIcon }) {
  return <Icon size="1rem" strokeWidth={1.5} aria-hidden className="text-ink-2" />
}

const count = new Intl.NumberFormat('en-US')

/** The three systems the figures come from. They are read on a schedule and never written to. */
function Sources() {
  const sources = useQuery({ queryKey: ['sources'], queryFn: api.sources })

  return (
    <Card>
      <CardHead title="Where the figures come from" />
      <Loaded query={sources}>
        {(data) => (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>System</th>
                  <th>What it holds</th>
                  <th>Access</th>
                  <th className="num">Tables</th>
                  <th className="num">Records</th>
                  <th>Last read</th>
                </tr>
              </thead>
              <tbody>
                {data.map((source) => (
                  <tr key={source.system}>
                    <td>
                      <Named mark={<Mark icon={SYSTEMS[source.system].icon} />}>{SYSTEMS[source.system].name}</Named>
                    </td>
                    <td className="text-ink-2">{SYSTEMS[source.system].holds}</td>
                    <td className="text-ink-2">Read only</td>
                    <td className="num">{count.format(source.tables)}</td>
                    <td className="num">{count.format(source.records)}</td>
                    <td className="text-ink-2">{source.last_read_at ? dateTime(source.last_read_at) : 'Not yet'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loaded>
    </Card>
  )
}

/** The account a drafted follow-up is sent with. */
function Email() {
  const [mail, choose] = useMailApp()

  return (
    <Card>
      <CardHead title="Email, for sending follow-ups" />
      <p className="px-5 pb-3 text-[0.8125rem] text-ink-2">
        {mail.key === 'default'
          ? `No account is connected, so ${DEFAULT_MAIL.does.toLowerCase()}`
          : `${mail.name} is connected. Disconnect it to go back to this computer's own mail app`}
      </p>
      <div className="overflow-x-auto">
        <table className="data-table">
          <thead>
            <tr>
              <th>Account</th>
              <th>What connecting does</th>
              <th>Status</th>
              <th>
                <span className="sr-only">Connect</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {MAIL_APPS.map((app) => {
              const connected = mail.key === app.key
              return (
                <tr key={app.key}>
                  <td>
                    <Named mark={<img src={app.logo} alt="" className="size-5 object-contain" />}>{app.name}</Named>
                  </td>
                  <td className="text-ink-2 whitespace-normal!">{app.does}</td>
                  <td className={connected ? '' : 'text-ink-2'}>{connected ? 'Connected' : 'Not connected'}</td>
                  <td className="w-36 text-right">
                    <Button
                      className="w-28"
                      variant={connected ? 'quiet' : 'primary'}
                      onClick={() => choose(connected ? 'default' : app.key)}
                    >
                      {connected ? 'Disconnect' : 'Connect'}
                    </Button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <p className="border-t border-hair px-5 py-3 text-xs leading-4 text-muted">
        Connecting here does not sign in to the mailbox or read it. The message opens in that account for you to send, so
        it goes from your own address and nothing is sent without you
      </p>
    </Card>
  )
}

export function Connectors() {
  return (
    <>
      <PageHead title="Connectors" sub="What this app reads from, and the account it hands messages to" />
      <Sources />
      <Email />
    </>
  )
}
