import { useState } from 'react'
import { money, percent } from '../lib/format'
import { Card } from './ui'

export interface DonutProps {
  title: string
  /** What the parts are, as the legend's first column heading. */
  heading: string
  /** The parts of the whole, largest first, each with its share as the API gives it. */
  slices: { label: string; amount: string; share_pct: string }[]
  /** The whole, as the API gives it, and what to call it in the middle of the ring. */
  total: { label: string; amount: string }
  /** Something the reader needs to know to read the chart rightly, said under it. */
  note?: string
}

// Every part gets its own colour, in the chart order, so no two parts look alike.
const COLOURS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)', 'var(--series-5)']

function shade(index: number): string {
  return COLOURS[Math.min(index, COLOURS.length - 1)]
}

/** A point on a circle of radius r around the middle, at a turn of 0 (top) to 1. */
function at(turn: number, r: number, middle: number): [number, number] {
  const angle = turn * 2 * Math.PI - Math.PI / 2
  return [middle + r * Math.cos(angle), middle + r * Math.sin(angle)]
}

/** One part of the ring, from one turn to another. */
function arc(from: number, to: number, outer: number, inner: number, middle: number): string {
  // A whole ring cannot be drawn as one arc, so it stops just short of closing.
  const end = Math.min(to, from + 0.99999)
  const large = end - from > 0.5 ? 1 : 0
  const [ax, ay] = at(from, outer, middle)
  const [bx, by] = at(end, outer, middle)
  const [cx, cy] = at(end, inner, middle)
  const [dx, dy] = at(from, inner, middle)
  return `M${ax},${ay} A${outer},${outer} 0 ${large} 1 ${bx},${by} L${cx},${cy} A${inner},${inner} 0 ${large} 0 ${dx},${dy} Z`
}

/**
 * A whole split into its parts, as a ring with the total in the middle and a
 * legend beside it giving each part's amount and share. Hover a part, in the
 * ring or the legend, to pick it out.
 */
export function Donut({ title, heading, slices, total, note }: DonutProps) {
  const [active, setActive] = useState<number | null>(null)
  // Only the drawing needs fractions; every figure shown is the API's.
  const shares = slices.map((slice) => Number(slice.share_pct) / 100)
  const starts = shares.map((_, index) => shares.slice(0, index).reduce((a, b) => a + b, 0))

  const size = 200
  const middle = size / 2
  const outer = 96
  const inner = 72
  const shown = active === null ? null : slices[active]

  return (
    <Card className="flex flex-col gap-4 p-5">
      <h3 className="font-medium">{title}</h3>

      <div className="@container">
        <div className="grid grid-cols-1 items-center gap-6 @[27rem]:grid-cols-[10rem_minmax(0,1fr)]">
          <div className="relative mx-auto size-40">
            <svg role="img" aria-label={title} viewBox={`0 0 ${size} ${size}`} className="block size-full">
              {slices.map((slice, index) =>
                shares[index] > 0 ? (
                  <path
                    key={slice.label}
                    d={arc(starts[index], starts[index] + shares[index], outer, inner, middle)}
                    fill={shade(index)}
                    // A thin line of the card between parts, so neighbours never run together.
                    stroke="var(--card)"
                    strokeWidth={2}
                    strokeLinejoin="round"
                    className="transition-opacity duration-150 ease-out"
                    style={{
                      opacity: active !== null && active !== index ? 0.35 : 1,
                    }}
                    onPointerEnter={() => setActive(index)}
                    onPointerLeave={() => setActive(null)}
                  />
                ) : null,
              )}
            </svg>
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-0.5 text-center">
              <span className="text-xs leading-4 text-ink-2">{shown ? shown.label : total.label}</span>
              <span className="font-mono text-[0.9375rem] font-medium tabular-nums">{money(shown ? shown.amount : total.amount)}</span>
            </div>
          </div>

          {/* The legend is a list, not a table, so it fits beside the ring in a half-width card. */}
          <ul aria-label={heading} className="flex min-w-0 flex-col">
            {slices.map((slice, index) => (
              <li
                key={slice.label}
                onMouseEnter={() => setActive(index)}
                onMouseLeave={() => setActive(null)}
                className={`grid h-10 grid-cols-[0.75rem_minmax(0,1fr)_auto_3.5rem] items-center gap-3 border-b border-hair px-2 last:border-b-0 ${active === index ? 'bg-raised' : ''}`}
              >
                <span aria-hidden className="size-3 rounded-sm ring-1 ring-hair ring-inset" style={{ background: shade(index) }} />
                <span className="truncate">{slice.label}</span>
                <span className="text-right font-mono text-[0.8125rem] tabular-nums">{money(slice.amount)}</span>
                <span className="text-right font-mono text-[0.8125rem] text-ink-2 tabular-nums">{percent(slice.share_pct)}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Notes sit at the foot of the card, so cards side by side end on the same line. */}
      {note && <p className="mt-auto text-xs leading-4 text-muted">{note}</p>}
    </Card>
  )
}
