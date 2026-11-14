import assert from 'node:assert/strict'
import test from 'node:test'
import { parseChartData } from '../src/components/chartData.ts'

test('parses valid labeled numbers and trims labels', () => {
  assert.deepEqual(parseChartData('[{"label":"  January ","value":12.5}]'), {
    ok: true,
    data: [{ label: 'January', value: 12.5 }],
  })
})

test('supports negative values', () => {
  assert.deepEqual(parseChartData('[{"label":"Loss","value":-4}]'), {
    ok: true,
    data: [{ label: 'Loss', value: -4 }],
  })
})

test('rejects malformed, oversized, and invalid point data', () => {
  assert.equal(parseChartData('{').ok, false)
  assert.equal(parseChartData('[]').ok, false)
  assert.equal(parseChartData(JSON.stringify(Array.from({ length: 13 }, (_, index) => ({
    label: `Point ${index}`,
    value: index,
  })))).ok, false)
  assert.equal(parseChartData('[{"label":"Bad","value":null}]').ok, false)
  assert.equal(parseChartData('[{"label":"   ","value":1}]').ok, false)
})
