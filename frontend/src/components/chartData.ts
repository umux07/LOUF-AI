export type ChartDatum = {
  label: string
  value: number
}

export type ChartDataResult =
  | { ok: true; data: ChartDatum[] }
  | { ok: false; error: string }

const MAX_DATA_POINTS = 12
const MAX_LABEL_LENGTH = 24
const MAX_VALUE = 1_000_000_000

export function parseChartData(raw: string): ChartDataResult {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return { ok: false, error: 'Enter valid JSON data.' }
  }

  if (!Array.isArray(parsed) || parsed.length === 0 || parsed.length > MAX_DATA_POINTS) {
    return {
      ok: false,
      error: `Provide an array with 1 to ${MAX_DATA_POINTS} data points.`,
    }
  }

  const data: ChartDatum[] = []
  for (const [index, item] of parsed.entries()) {
    if (typeof item !== 'object' || item === null || Array.isArray(item)) {
      return { ok: false, error: `Data point ${index + 1} must be an object.` }
    }

    const { label, value } = item as Record<string, unknown>
    if (typeof label !== 'string' || !label.trim() || label.trim().length > MAX_LABEL_LENGTH) {
      return {
        ok: false,
        error: `Data point ${index + 1} needs a label of 1 to ${MAX_LABEL_LENGTH} characters.`,
      }
    }
    if (typeof value !== 'number' || !Number.isFinite(value) || Math.abs(value) > MAX_VALUE) {
      return {
        ok: false,
        error: `Data point ${index + 1} needs a finite number between -${MAX_VALUE} and ${MAX_VALUE}.`,
      }
    }

    data.push({ label: label.trim(), value })
  }

  return { ok: true, data }
}
