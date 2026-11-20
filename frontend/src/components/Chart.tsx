import { useEffect, useId, useRef, useState } from 'react'
import type { PointerEvent, ReactNode } from 'react'
import { money, moneyShort } from '../lib/format'
import { Card } from './ui'

export interface ChartProps {
  kind: 'line' | 'area' | 'bar'
  title: string
  unit: 'money' | 'number' | 'percent'
  /** The labels along the bottom, in order. */
  points: string[]
  /** Up to four series, each with one value per point. */
  series: { label: string; values: number[] }[]
  /** Something the reader needs to know to read the chart rightly, said under it. */
  note?: string
  /** Controls for the chart, such as what it shows, at the right of its title. */
  aside?: ReactNode
}

// One colour per series, always in this order, so a series keeps its colour.
const COLOURS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)']

const plain = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 })
const short = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 })

function written(value: number, unit: ChartProps['unit']): string {
  if (unit === 'money') return money(value)
  return unit === 'percent' ? `${plain.format(value)}%`.replace('-', '−') : plain.format(value).replace('-', '−')
}

function onAxis(value: number, unit: ChartProps['unit']): string {
  if (unit === 'money') return moneyShort(value)
  return unit === 'percent' ? `${short.format(value)}%`.replace('-', '−') : short.format(value).replace('-', '−')
}

/** Round axis values that cover the data and always include zero. */
function scale(values: number[]): number[] {
  const low = Math.min(0, ...values)
  const high = Math.max(0, ...values)
  const rough = (high - low || 1) / 4
  const power = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? rough
  const ticks: number[] = []
  for (let tick = Math.floor(low / step) * step; tick <= Math.ceil(high / step) * step + step / 2; tick += step) {
    ticks.push(Number(tick.toPrecision(12)))
  }
  return ticks
}

/**
 * A smooth line through the points that never overshoots them, so a curve
 * between two equal months stays flat and never dips below zero (monotone cubic).
 */
function smooth(xs: number[], ys: number[]): string {
  const n = xs.length
  if (n === 0) return ''
  if (n === 1) return `M${xs[0]},${ys[0]}`
  const slope = xs.slice(1).map((x, i) => (ys[i + 1] - ys[i]) / (x - xs[i]))
  const tangent = xs.map((_, i) => {
    if (i === 0) return slope[0]
    if (i === n - 1) return slope[n - 2]
    const [a, b] = [slope[i - 1], slope[i]]
    // Flat at a peak or a trough; otherwise the harmonic mean of the slopes either side.
    return a * b <= 0 ? 0 : (2 * a * b) / (a + b)
  })
  let d = `M${xs[0]},${ys[0]}`
  for (let i = 0; i < n - 1; i++) {
    const h = (xs[i + 1] - xs[i]) / 3
    d += ` C${xs[i] + h},${ys[i] + tangent[i] * h} ${xs[i + 1] - h},${ys[i + 1] - tangent[i + 1] * h} ${xs[i + 1]},${ys[i + 1]}`
  }
  return d
}

/** A bar from the zero line to its value, rounded at the value end only. */
function bar(x: number, zero: number, y: number, width: number, radius: number): string {
  const r = Math.min(radius, width / 2, Math.abs(zero - y))
  const turn = y <= zero ? r : -r
  return `M${x},${zero} V${y + turn} Q${x},${y} ${x + r},${y} H${x + width - r} Q${x + width},${y} ${x + width},${y + turn} V${zero} Z`
}

/** How wide the chart is on screen, and how big one rem is, so it is drawn at true size. */
function useMeasure() {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, rem: 16 })
  useEffect(() => {
    const element = ref.current
    if (!element) return
    const read = () =>
      setSize({ width: element.clientWidth, rem: parseFloat(getComputedStyle(document.documentElement).fontSize) || 16 })
    read()
    const observer = new ResizeObserver(read)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return { ref, ...size }
}

/** A line, area or bar chart of up to four series. Hover or tap a point to read its values. */
export function Chart({ kind, title, unit, points, series, note, aside }: ChartProps) {
  const { ref, width, rem } = useMeasure()
  const fade = useId()
  const curve = kind !== 'bar'
  const [active, setActive] = useState<number | null>(null)

  // A series with a missing or unreadable value is left out rather than breaking the
  // whole drawing; the axis and the other series still draw.
  // Each keeps the colour of its place in the list, so a series left out never repaints the others.
  const shown = series
    .slice(0, COLOURS.length)
    .map((s, index) => ({ ...s, colour: COLOURS[index] }))
    .filter((s) => s.values.length === points.length && s.values.every(Number.isFinite))
  const ticks = scale(shown.flatMap((s) => s.values))
  const low = ticks[0]
  const high = ticks[ticks.length - 1]

  const height = 16 * rem
  const left = Math.max(...ticks.map((tick) => onAxis(tick, unit).length)) * 0.5 * rem + 0.75 * rem
  const right = 0.75 * rem
  const top = 0.5 * rem
  const bottom = 1.75 * rem
  const plotWidth = Math.max(0, width - left - right)
  const plotHeight = height - top - bottom
  const band = plotWidth / points.length

  // An area runs edge to edge, first point on the left edge and last on the right, as a
  // trend does. Lines and bars sit in the middle of their slot.
  const edge = kind === 'area' && points.length > 1
  const step = edge ? plotWidth / (points.length - 1) : band
  const x = (index: number) => (edge ? left + index * step : left + (index + 0.5) * band)
  const y = (value: number) => top + ((high - value) / (high - low)) * plotHeight

  // A bottom label that is wider than its slot is cut short; the full name is in the
  // hover. Only when slots are too narrow for even a short label are some left out.
  const letter = 0.4 * rem
  const room = (slots: number) => Math.floor((slots * band - 0.75 * rem) / letter)
  const every = room(1) >= 6 ? 1 : Math.max(1, Math.ceil((6 * letter + 0.75 * rem) / (band || 1)))
  const fits = room(every)
  const cut = (label: string) => (label.length <= fits ? label : `${label.slice(0, Math.max(1, fits - 1)).trimEnd()}…`)

  const gap = 2
  const barWidth = Math.max(2, Math.min(1.5 * rem, (band * 0.72) / shown.length - gap))
  const group = shown.length * barWidth + (shown.length - 1) * gap

  function point(event: PointerEvent<SVGSVGElement>) {
    const box = event.currentTarget.getBoundingClientRect()
    const along = event.clientX - box.left - left
    const index = edge ? Math.round(along / (step || 1)) : Math.floor(along / (band || 1))
    setActive(Math.max(0, Math.min(points.length - 1, index)))
  }

  const legend =
    shown.length > 1 ? (
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem] text-ink-2">
        {shown.map((s, index) => (
          <li key={index} className="flex items-center gap-2">
            <span aria-hidden className={curve ? 'h-0.5 w-4 rounded-full' : 'size-2.5 rounded-xs'} style={{ background: shown[index].colour }} />
            {s.label}
          </li>
        ))}
      </ul>
    ) : null

  return (
    <Card className="flex flex-col gap-3 p-5">
      {/* With controls, the title and controls share the top line and the legend goes under them. */}
      <div className={`flex flex-wrap justify-between gap-x-6 gap-y-2 ${aside ? 'items-center' : 'items-baseline'}`}>
        <h3 className="font-medium">{title}</h3>
        {aside}
        {!aside && legend}
      </div>
      {aside && legend}

      <div ref={ref} className="relative">
        {width > 0 && (
          <svg
            role="img"
            aria-label={title}
            width={width}
            height={height}
            className="block touch-pan-y"
            onPointerMove={point}
            onPointerDown={point}
            onPointerLeave={() => setActive(null)}
          >
            {ticks.map((tick) => (
              <g key={tick}>
                <line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} stroke={tick === 0 ? 'var(--muted)' : 'var(--hair)'} strokeWidth={1} />
                <text x={left - 0.5 * rem} y={y(tick)} dy="0.32em" textAnchor="end" fill="var(--muted)" fontSize={0.75 * rem} className="font-mono">
                  {onAxis(tick, unit)}
                </text>
              </g>
            ))}

            {points.map((label, index) =>
              index % every === 0 ? (
                <text
                  key={index}
                  x={x(index)}
                  y={height - 0.375 * rem}
                  textAnchor={edge && index === 0 ? 'start' : edge && index === points.length - 1 ? 'end' : 'middle'}
                  fill="var(--muted)" fontSize={0.75 * rem}>
                  {cut(label)}
                </text>
              ) : null,
            )}

            {active !== null &&
              (curve ? (
                <line x1={x(active)} x2={x(active)} y1={top} y2={top + plotHeight} stroke="var(--muted)" strokeWidth={1} />
              ) : (
                <rect x={left + active * band} y={top} width={band} height={plotHeight} fill="var(--raised)" />
              ))}

            {kind === 'area' && (
              <defs>
                {shown.map((s, index) => (
                  <linearGradient key={index} id={`${fade}-${index}`} x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor={s.colour} stopOpacity={shown.length > 2 ? 0.08 : shown.length > 1 ? 0.12 : 0.24} />
                    <stop offset="100%" stopColor={s.colour} stopOpacity={0} />
                  </linearGradient>
                ))}
              </defs>
            )}

            {kind === 'area'
              ? shown.map((s, index) => {
                  const xs = s.values.map((_, i) => x(i))
                  const line = smooth(xs, s.values.map(y))
                  return (
                    <g key={index}>
                      <path d={`${line} L${xs[xs.length - 1]},${y(Math.max(0, low))} L${xs[0]},${y(Math.max(0, low))} Z`} fill={`url(#${fade}-${index})`} />
                      <path d={line} fill="none" stroke={shown[index].colour} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                      {active !== null && (
                        <circle cx={x(active)} cy={y(s.values[active])} r={5} fill="var(--card)" stroke={shown[index].colour} strokeWidth={2} />
                      )}
                    </g>
                  )
                })
              : kind === 'line'
              ? shown.map((s, index) => (
                  <g key={index}>
                    <polyline
                      points={s.values.map((value, i) => `${x(i)},${y(value)}`).join(' ')}
                      fill="none"
                      stroke={shown[index].colour}
                      strokeWidth={2}
                      strokeLinejoin="round"
                      strokeLinecap="round"
                    />
                    {s.values.map((value, i) =>
                      // Every point is marked while there is room; past that, only the one being read.
                      points.length <= 12 || i === active ? (
                        <circle key={i} cx={x(i)} cy={y(value)} r={i === active ? 5 : 4} fill={shown[index].colour} stroke="var(--card)" strokeWidth={2} />
                      ) : null,
                    )}
                  </g>
                ))
              : shown.map((s, index) =>
                  s.values.map((value, i) => (
                    <path
                      key={`${index}-${i}`}
                      d={bar(x(i) - group / 2 + index * (barWidth + gap), y(0), y(value), barWidth, 4)}
                      fill={shown[index].colour}
                    />
                  )),
                )}
          </svg>
        )}

        {active !== null && (
          <div
            className="pointer-events-none absolute -top-2 z-10 flex flex-col gap-1 rounded-lg border border-hair bg-card px-3 py-2 text-[0.8125rem] whitespace-nowrap shadow-float w-max"
            // Slides from its left edge to its right edge as the pointer crosses the chart,
            // so it follows the point being read and never leaves the card.
            style={{ left: x(active), transform: `translateX(-${(x(active) / (width || 1)) * 100}%)` }}
          >
            <span className="text-ink-2">{points[active]}</span>
            {shown.map((s, index) => (
              <span key={index} className="grid grid-cols-[auto_1fr_auto] items-center gap-x-2">
                <span aria-hidden className="size-2 rounded-full" style={{ background: shown[index].colour }} />
                {s.label}
                <span className="pl-4 text-right font-mono tabular-nums">{written(s.values[active], unit)}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Notes sit at the foot of the card, so cards side by side end on the same line. */}
      {note && <p className="mt-auto text-xs leading-4 text-muted">{note}</p>}

      {/* The same figures as a table, for anyone who is not reading the picture. */}
      <div className="sr-only">
        <table>
          <caption>{title}</caption>
          <thead>
            <tr>
              <th />
              {shown.map((s, index) => (
                <th key={index}>{s.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {points.map((label, i) => (
              <tr key={i}>
                <th>{label}</th>
                {shown.map((s, index) => (
                  <td key={index}>{written(s.values[i], unit)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
