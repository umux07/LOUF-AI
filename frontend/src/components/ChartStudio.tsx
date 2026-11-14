import { useState } from 'react'
import type { FormEvent } from 'react'
import { BarChart3 } from 'lucide-react'
import { parseChartData } from './chartData'
import type { ChartDatum } from './chartData'

const chartExample = `[
  { "label": "January", "value": 18 },
  { "label": "February", "value": 27 },
  { "label": "March", "value": 22 }
]`

const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 })

export function ChartStudio() {
  const [title, setTitle] = useState('')
  const [rawData, setRawData] = useState('')
  const [chart, setChart] = useState<ChartDatum[] | null>(null)
  const [error, setError] = useState('')

  function createChart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const result = parseChartData(rawData)
    if (!result.ok) {
      setChart(null)
      setError(result.error)
      return
    }
    setChart(result.data)
    setError('')
  }

  const values = chart?.map((point) => point.value) ?? []
  const minimum = Math.min(0, ...values)
  const maximum = Math.max(0, ...values)
  const range = maximum - minimum || 1
  const plot = { x: 54, y: 42, width: 672, height: 204 }
  const zeroY = plot.y + (maximum / range) * plot.height

  return (
    <section className="feature-page chart-page">
      <div className="feature-heading">
        <div className="welcome-icon"><BarChart3 size={20} /></div>
        <span className="eyebrow">YOUR DATA, VISUALIZED</span>
        <h1>Charts</h1>
        <p>Turn a small set of your own numbers into a clear bar chart. Your data stays in this browser session.</p>
      </div>

      <form className="chart-input-card" onSubmit={createChart}>
        <label htmlFor="chart-title">Chart title</label>
        <input
          id="chart-title"
          value={title}
          maxLength={80}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="e.g. Monthly signups"
        />
        <label htmlFor="chart-data">Data as JSON</label>
        <textarea
          id="chart-data"
          value={rawData}
          maxLength={5000}
          onChange={(event) => setRawData(event.target.value)}
          placeholder={chartExample}
          aria-describedby="chart-data-help"
          spellCheck={false}
          required
        />
        <div className="chart-form-footer">
          <span id="chart-data-help">Use 1–12 entries, each with a text label and a finite numeric value.</span>
          <span>{rawData.length}/5000</span>
        </div>
        {error && <p className="chart-error" role="alert">{error}</p>}
        <button className="primary-button chart-create-button" type="submit" disabled={!rawData.trim()}>
          <BarChart3 size={15} /> Create chart
        </button>
      </form>

      {chart ? (
        <section className="chart-result-card" aria-label="Chart result">
          <h2>{title.trim() || 'Untitled chart'}</h2>
          <div className="chart-visual">
            <svg
              viewBox="0 0 760 310"
              role="img"
              aria-labelledby="chart-svg-title chart-svg-description"
            >
              <title id="chart-svg-title">{title.trim() || 'Untitled chart'}</title>
              <desc id="chart-svg-description">
                Bar chart for {chart.length} user-provided data points. A data table follows.
              </desc>
              <line
                x1={plot.x}
                x2={plot.x + plot.width}
                y1={zeroY}
                y2={zeroY}
                className="chart-axis"
              />
              {chart.map((point, index) => {
                const slot = plot.width / chart.length
                const barWidth = Math.min(44, slot * 0.58)
                const valueY = plot.y + ((maximum - point.value) / range) * plot.height
                const barHeight = Math.abs((point.value / range) * plot.height)
                const barX = plot.x + slot * index + (slot - barWidth) / 2
                const barY = point.value >= 0 ? valueY : zeroY
                const valueLabelY = point.value >= 0
                  ? Math.max(plot.y - 5, barY - 8)
                  : Math.min(plot.y + plot.height + 16, barY + barHeight + 15)

                return (
                  <g key={`${point.label}-${index}`}>
                    <rect
                      x={barX}
                      y={barY}
                      width={barWidth}
                      height={barHeight}
                      rx="4"
                      className="chart-bar"
                    >
                      <title>{`${point.label}: ${numberFormat.format(point.value)}`}</title>
                    </rect>
                    <text
                      x={barX + barWidth / 2}
                      y={valueLabelY}
                      textAnchor="middle"
                      className="chart-value"
                    >
                      {numberFormat.format(point.value)}
                    </text>
                    <text
                      x={plot.x + slot * index + slot / 2}
                      y="278"
                      textAnchor="middle"
                      className="chart-label"
                    >
                      {point.label.length > 12 ? `${point.label.slice(0, 11)}…` : point.label}
                      <title>{point.label}</title>
                    </text>
                  </g>
                )
              })}
            </svg>
          </div>
          <table className="chart-data-table">
            <caption>Chart data</caption>
            <thead><tr><th scope="col">Label</th><th scope="col">Value</th></tr></thead>
            <tbody>
              {chart.map((point, index) => (
                <tr key={`${point.label}-${index}`}>
                  <th scope="row">{point.label}</th>
                  <td>{numberFormat.format(point.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : (
        <div className="chart-empty">
          <BarChart3 size={20} />
          <strong>No chart yet</strong>
          <span>Enter your data above and choose “Create chart” to visualize it.</span>
        </div>
      )}
    </section>
  )
}
