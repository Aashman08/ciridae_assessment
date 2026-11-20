import { defineCatalog } from '@json-render/core'
import type { Spec } from '@json-render/core'
import { defineRegistry, JSONUIProvider, Renderer } from '@json-render/react'
import { schema } from '@json-render/react/schema'
import { createContext, useContext } from 'react'
import { useNavigate } from 'react-router-dom'
import { z } from 'zod'
import { Chart } from './Chart'
import { Card } from './ui'

// Everything an answer can be made of. The server sends a spec that names these
// and nothing else, so an answer is drawn with the same parts as the rest of the app.
const catalog = defineCatalog(schema, {
  components: {
    Answer: { props: z.object({}), description: 'The whole answer: its blocks, in order' },
    Text: { props: z.object({ text: z.string() }), description: 'A sentence or short paragraph' },
    Table: {
      props: z.object({
        columns: z.array(z.object({ label: z.string(), kind: z.enum(['text', 'money', 'number', 'date']) })),
        rows: z.array(z.array(z.string())),
      }),
      description: 'Several records, one per row, one fact per column',
    },
    Figures: {
      props: z.object({ items: z.array(z.object({ label: z.string(), value: z.string() })) }),
      description: 'A few headline figures, each with a label',
    },
    Chart: {
      props: z.object({
        kind: z.enum(['line', 'bar']),
        title: z.string(),
        unit: z.enum(['money', 'number', 'percent']),
        points: z.array(z.string()),
        series: z.array(z.object({ label: z.string(), values: z.array(z.number()) })),
      }),
      description: 'A line or bar chart of up to three series over the same points',
    },
  },
  actions: {},
})

/** Where a job, invoice or bill number named in a table leads, keyed by that number. */
const Links = createContext<Record<string, string>>({})

const { registry } = defineRegistry(catalog, {
  components: {
    Answer: ({ children }) => <div className="flex flex-col gap-4">{children}</div>,

    Text: ({ props }) => <p className="whitespace-pre-wrap">{props.text}</p>,

    Table: function AnswerTable({ props }) {
      const links = useContext(Links)
      const navigate = useNavigate()
      const figures = props.columns.map((column) => column.kind === 'money' || column.kind === 'number')
      return (
        <Card className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                {props.columns.map((column, index) => (
                  <th key={index} className={figures[index] ? 'num' : undefined}>
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {props.rows.map((row, rowIndex) => {
                // A row that names a record we can open is clickable across its whole width.
                const to = row.map((cell) => links[cell]).find(Boolean)
                return (
                  <tr key={rowIndex} className={to ? 'clickable' : undefined} onClick={to ? () => navigate(to) : undefined}>
                    {row.map((cell, index) => (
                      <td key={index} className={figures[index] ? 'num' : undefined}>
                        {cell}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </Card>
      )
    },

    Chart: ({ props }) => <Chart {...props} />,

    Figures: ({ props }) => (
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-4">
        {props.items.map((item, index) => (
          <Card key={index} className="flex flex-col gap-2 p-4">
            <dt className="text-[0.8125rem] text-ink-2">{item.label}</dt>
            <dd className="text-xl leading-7 font-medium tabular-nums">{item.value}</dd>
          </Card>
        ))}
      </dl>
    ),
  },
})

/** One answer, drawn from the spec the server sent. */
export function AnswerView({ spec, links }: { spec: Spec; links: Record<string, string> }) {
  return (
    <Links.Provider value={links}>
      <JSONUIProvider registry={registry}>
        <Renderer spec={spec} registry={registry} />
      </JSONUIProvider>
    </Links.Provider>
  )
}
