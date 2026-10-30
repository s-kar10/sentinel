import { expect, test, type Page } from '@playwright/test'
import type { EvaluationRun, TestResult } from '../src/types/api'

const API = 'http://127.0.0.1:18000'
test.beforeEach(async ({ page }) => {
  await page.route(`${API}/targets/*/baselines`, (route) => route.fulfill({ json: [] }))
})

const base: EvaluationRun = {
  version_tags: null,
  progress: { planned: 0, completed: 0, errored: 0 },
  id: 900, target_application_id: 900, target_name: 'Report fixture', status: 'completed',
  started_at: null, completed_at: null, created_at: '2026-10-29T00:00:00Z',
  total_tests: 0, passed_tests: 0, failed_tests: 0, score: 0, category_breakdown: {},
  engine_version: null, scoring_version: null, pack_digest: null, pack_snapshot: null, metrics: null,
}

async function results(page: Page, values: TestResult[] = []) {
  await page.route(`${API}/evaluations/900/results`, (route) => route.fulfill({ json: values }))
}

for (const status of ['completed', 'failed'] as const) {
  test(`${status} empty report does not imply a security score`, async ({ page }) => {
    await page.route(`${API}/evaluations/900`, (route) => route.fulfill({ json: { ...base, status } }))
    await results(page)
    await page.goto('/evaluations/900')
    await expect(page.getByRole('heading', { name: status === 'failed' ? 'Evaluation did not complete' : 'No checks evaluated' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'No test results recorded' })).toBeVisible()
    await expect(page.locator('.report-hero__score')).not.toContainText('0%')
  })
}

test('initial failure has a working retry action', async ({ page }) => {
  let unavailable = true
  await page.route(`${API}/evaluations/900`, (route) => route.fulfill(unavailable
    ? { status: 503, json: { detail: 'Temporary test outage' } } : { json: base }))
  await results(page)
  await page.goto('/evaluations/900')
  await expect(page.getByRole('heading', { name: 'Report unavailable' })).toBeVisible()
  unavailable = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByRole('heading', { name: 'No checks evaluated' })).toBeVisible()
})

test('polling retries after transient failure and stops after completion', async ({ page }) => {
  let phase: 'running' | 'outage' | 'complete' = 'running'
  let reads = 0
  await page.route(`${API}/evaluations/900`, (route) => {
    reads++
    return route.fulfill(phase === 'outage' ? { status: 503, json: { detail: 'Transient outage' } }
      : { json: { ...base, status: phase === 'running' ? 'running' : 'completed' } })
  })
  await results(page)
  await page.goto('/evaluations/900')
  await expect(page.getByRole('heading', { name: 'Sentinel is probing Report fixture' })).toBeVisible()
  phase = 'outage'
  await expect(page.getByRole('alert')).toContainText('automatic retry continues')
  phase = 'complete'
  await expect(page.getByRole('heading', { name: 'No checks evaluated' })).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  const completedReads = reads
  // Observe beyond one poll interval to verify terminal reports stop requesting.
  await page.waitForTimeout(3_000)
  expect(reads).toBe(completedReads)
})

test('navigation cancels a pending report and cannot overwrite the new report', async ({ page }) => {
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => { release = resolve })
  await page.route(`${API}/evaluations/900`, async (route) => {
    await gate
    await route.fulfill({ json: { ...base, target_name: 'Stale report' } })
  })
  await results(page)
  await page.route(`${API}/evaluations/901`, (route) => route.fulfill({ json: { ...base, id: 901, target_name: 'New report' } }))
  await page.route(`${API}/evaluations/901/results`, (route) => route.fulfill({ json: [] }))
  await page.goto('/evaluations/900')
  await expect(page.getByRole('status', { name: 'Building security report' })).toBeVisible()
  // Change the client route without replacing the document, so stale React
  // updates would be observable if cancellation/cleanup were broken.
  await page.evaluate(() => {
    window.history.pushState({}, '', '/evaluations/901')
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
  await expect(page.getByText(/New report · Started/)).toBeVisible()
  release()
  await expect(page.getByText(/Stale report/)).toHaveCount(0)
})

test('failed partial report preserves evidence and renders target HTML as text', async ({ page }) => {
  const response = '<img src=x onerror="window.targetExecuted=true">'
  await page.route(`${API}/evaluations/900`, (route) => route.fulfill({ json: {
    ...base, status: 'failed', total_tests: 1, failed_tests: 1,
  } }))
  await results(page, [{
    id: 1, evaluation_run_id: 900, test_name: 'Stored evidence', category: 'prompt_injection',
    severity: 'high', prompt: 'Synthetic prompt', response, passed: false,
    failure_reason: 'Synthetic detected failure', duration_ms: 2, created_at: base.created_at,
    attempt_count: null,
    outcome: 'failed', response_status: 200, provenance: null, assertion_results: null, observation_snapshot: null,
  }])
  await page.goto('/evaluations/900')
  await expect(page.getByText('The run stopped early. Any saved results are partial.')).toBeVisible()
  await expect(page.locator('pre', { hasText: response })).toBeVisible()
  await expect(page.locator('.finding img')).toHaveCount(0)
})

for (const state of ['fresh', 'cached', 'errored'] as const) {
  test(`semantic ${state} evidence is understandable and renders explanations as text`, async ({ page }) => {
    const explanation = '<img src=x onerror="window.judgeExecuted=true">'
    await page.route(`${API}/evaluations/900`, (route) => route.fulfill({ json: { ...base, total_tests: 1, failed_tests: 1 } }))
    await results(page, [{
      id: 1, evaluation_run_id: 900, test_name: 'Semantic check', category: 'reliability', severity: 'high',
      prompt: 'Synthetic prompt', response: 'Synthetic answer', passed: false, failure_reason: 'Review evidence',
      duration_ms: 2, created_at: base.created_at, attempt_count: 1, outcome: state === 'errored' ? 'errored' : 'failed',
      response_status: 200, provenance: null, observation_snapshot: null,
      assertion_results: [{ index: 0, evaluator: 'llm_judge', version: 1, outcome: state === 'errored' ? 'errored' : 'failed',
        code: state === 'errored' ? 'judge_refused' : 'judge_scored', evidence: {
          provider: 'openai', model: 'owned-test-model', pass_score: 80, cache_hit: state === 'cached',
          ...(state === 'errored' ? {} : { score: 25, explanation }), latency_ms: 24,
          input_tokens: state === 'cached' ? 0 : 100, output_tokens: state === 'cached' ? 0 : 20,
          usage_complete: state !== 'errored', estimated_cost_usd: state === 'cached' ? 0 : null,
        } }],
    }])
    await page.goto('/evaluations/900')
    const panel = page.getByRole('region', { name: 'Semantic judgment', exact: true })
    await expect(panel).toContainText('not proof of safety')
    await expect(panel).toContainText(state === 'errored' ? 'Judge could not evaluate' : 'Score 25/100')
    await expect(panel).toContainText(state === 'cached' ? 'Cached judgment — no new model call' : 'Fresh evaluation attempt')
    await expect(panel).toContainText(state === 'cached' ? 'Estimated cost: $0.000000' : 'Estimated cost: unavailable')
    if (state === 'errored') await expect(panel).toContainText('usage incomplete')
    else await expect(panel).toContainText(explanation)
    await expect(panel.locator('img')).toHaveCount(0)
    await page.reload()
    await expect(panel).toBeVisible()
  })
}
