import { expect, test } from '@playwright/test'

const API = 'http://127.0.0.1:18000'
const DEMO = 'http://127.0.0.1:18001/chat'
const canaries = {
  policy: 'INTERNAL_CUSTOMER_SUPPORT_POLICY',
  secret: 'TEST_SECRET_ABC123',
  email: 'demo.customer@example.test',
  customer: 'CUSTOMER_TEST_001',
}

test.afterEach(async ({ request }) => {
  const targets = await (await request.get(`${API}/targets`)).json()
  for (const target of targets) await request.delete(`${API}/targets/${target.id}`)
})

test('register, validate, edit keys, manage canaries, evaluate, filter, and delete', async ({ page, request }) => {
  await page.goto('/targets/new')
  await page.getByRole('button', { name: 'Register target', exact: true }).click()
  await expect(page.getByText('Enter an application name.')).toBeVisible()
  await page.getByLabel('Application name').fill('Browser demo')
  await page.getByLabel('Endpoint URL').fill(DEMO)
  await page.getByLabel('Request JSON template').fill('{')
  await page.getByRole('button', { name: 'Register target', exact: true }).click()
  await expect(page.getByText('Enter valid JSON.')).toBeVisible()
  await page.getByLabel('Request JSON template').fill('{}')
  await page.getByLabel('API key', { exact: false }).first().fill('FAKE_BROWSER_KEY')
  const rejected = page.waitForResponse((response) => response.url() === `${API}/targets` && response.status() === 422)
  await page.getByRole('button', { name: 'Register target', exact: true }).click()
  expect(await (await rejected).text()).not.toContain('FAKE_BROWSER_KEY')
  await expect(page.getByRole('alert')).toContainText('prompt_field is invalid')
  await page.getByLabel('Request JSON template').fill('{"message":""}')
  const created = page.waitForResponse((response) => response.url() === `${API}/targets` && response.status() === 201)
  await page.getByRole('button', { name: 'Register target', exact: true }).click()
  const target = await (await created).json()
  expect(target).not.toHaveProperty('api_key')
  await expect(page).toHaveURL(`/targets/${target.id}`)
  await expect(page.getByText('API key configured', { exact: true })).toBeVisible()

  await page.getByRole('link', { name: 'Edit', exact: true }).click()
  await expect(page.locator('#api-key')).toHaveValue('')
  await page.getByLabel('Application name').fill('Renamed browser demo')
  const preserved = page.waitForRequest((r) => r.method() === 'PUT')
  await page.getByRole('button', { name: 'Save changes' }).click()
  expect((await preserved).postDataJSON()).not.toHaveProperty('api_key')
  await expect(page.getByText('API key configured', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Edit', exact: true }).click()
  await page.locator('#api-key').fill('FAKE_REPLACEMENT_KEY')
  const replaced = page.waitForResponse((r) => r.request().method() === 'PUT')
  await page.getByRole('button', { name: 'Save changes' }).click()
  expect(await (await replaced).text()).not.toContain('FAKE_REPLACEMENT_KEY')
  await page.getByRole('link', { name: 'Edit', exact: true }).click()
  await page.getByLabel('Remove saved API key').check()
  await expect(page.locator('#api-key')).toBeDisabled()
  const cleared = page.waitForRequest((r) => r.method() === 'PUT')
  await page.getByRole('button', { name: 'Save changes' }).click()
  expect((await cleared).postDataJSON().api_key).toBeNull()
  await expect(page.getByText('No API key', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Run evaluation', exact: true }).first().click()
  await expect(page.getByRole('alert')).toContainText('Add at least one protected value')
  await page.getByRole('button', { name: 'Add value', exact: true }).click()
  await expect(page.getByText('Enter both a label and a protected value.')).toBeVisible()
  for (const [name, value] of Object.entries(canaries)) {
    await page.getByLabel('Label', { exact: true }).fill(name)
    await page.getByLabel('Protected value', { exact: true }).fill(value)
    await page.getByRole('button', { name: 'Add value', exact: true }).click()
    await expect(page.getByRole('button', { name: `Remove ${name}`, exact: true })).toBeVisible()
    await expect(page.locator('.protected-list')).not.toContainText(value)
  }
  await page.getByRole('button', { name: 'Remove customer', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Remove value', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Remove customer', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Run evaluation', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: 'Sentinel Security Report' })).toBeVisible()
  const reportURL = page.url()
  await expect(page.locator('.finding')).toHaveCount(8)
  await expect(page.getByText('4 checks detected undesirable behavior; 0 checks had execution errors.')).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: 'Not passed (4)' }).click()
  await expect(page.locator('.finding')).toHaveCount(4)
  await page.getByLabel('Filter by category').selectOption('prompt_injection')
  await expect(page.locator('.finding')).toHaveCount(1)
  await page.getByRole('button', { name: 'Passed (4)', exact: true }).click()
  await expect(page.locator('.finding')).toHaveCount(1)
  await page.reload()
  await expect(page.locator('.finding')).toHaveCount(8)
  await page.getByRole('link', { name: 'All evaluations' }).click()
  await page.getByLabel('Filter by status').selectOption('failed')
  await expect(page.getByText('No matching evaluations')).toBeVisible()
  await page.getByLabel('Filter by status').selectOption('completed')
  await page.getByLabel('Search evaluations').fill('absent target')
  await expect(page.getByText('No matching evaluations')).toBeVisible()
  await page.getByLabel('Search evaluations').fill('Renamed browser demo')
  await expect(page.getByRole('link', { name: 'Renamed browser demo', exact: true })).toBeVisible()
  await page.goto(`/targets/${target.id}`)
  await page.getByRole('button', { name: 'Delete target', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('protected values, evaluation history, and test results')
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Renamed browser demo', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Delete target', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete target', exact: true }).click()
  await expect(page).toHaveURL('/targets')
  expect(await (await request.get(`${API}/evaluations`)).json()).toEqual([])
  await page.goto(reportURL)
  await expect(page.getByRole('heading', { name: 'Report unavailable' })).toBeVisible()
})

test('real extraction errors are not reported as detected target behavior', async ({ page, request }) => {
  const target = await (await request.post(`${API}/targets`, { data: {
    name: 'Broken mapping', endpoint_url: DEMO, request_template: { message: '' },
    prompt_field: 'message', response_field: 'missing',
  } })).json()
  await request.post(`${API}/targets/${target.id}/protected-values`, { data: { name: 'fake', value: canaries.secret } })
  await page.goto(`/targets/${target.id}`)
  await page.getByRole('button', { name: 'Run evaluation', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: 'Some checks could not be evaluated' })).toBeVisible()
  await expect(page.getByText('0 checks detected undesirable behavior; 8 checks had execution errors.')).toBeVisible()
  await expect(page.locator('.result-badge', { hasText: 'Execution error' })).toHaveCount(8)
})

test('target-list deletion states the cascade and removes the target', async ({ page, request }) => {
  await request.post(`${API}/targets`, { data: {
    name: 'List deletion fixture', endpoint_url: DEMO, request_template: { message: '' },
    prompt_field: 'message', response_field: 'response',
  } })
  await page.goto('/targets')
  await page.getByRole('button', { name: 'Delete List deletion fixture', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('protected values, evaluation history, and test results')
  await page.getByRole('dialog').getByRole('button', { name: 'Delete target', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'No targets registered' })).toBeVisible()
})

test('API-submitted custom pack produces a usable browser report', async ({ page, request }) => {
  const target = await (await request.post(`${API}/targets`, { data: {
    name: 'Custom pack demo', endpoint_url: DEMO, request_template: { message: '' },
    prompt_field: 'message', response_field: 'response',
  } })).json()
  const packs = await (await request.get(`${API}/attack-packs`)).json()
  // Select the two fixed injection probes; this pack needs no target canaries.
  const attackPack = { ...packs[0], id: 'browser-custom', name: 'Browser custom', attacks: packs[0].attacks.slice(0, 2) }
  const response = await request.post(`${API}/targets/${target.id}/evaluations`, { data: { attack_pack: attackPack } })
  expect(response.status()).toBe(201)
  const run = await response.json()
  expect(run.total_tests).toBe(2)
  expect(run.score).toBe(50)
  await page.goto(`/evaluations/${run.id}`)
  await expect(page.getByRole('heading', { name: 'Evaluation completed', exact: true })).toBeVisible()
  await expect(page.locator('.finding')).toHaveCount(2)
  await expect(page.getByText('1 checks detected undesirable behavior; 0 checks had execution errors.')).toBeVisible()
  await page.getByRole('button', { name: 'Not passed (1)', exact: true }).click()
  await expect(page.locator('.finding')).toHaveCount(1)
  await expect(page.locator('.finding')).toContainText('Ignore-instructions canary')
})

test('format 2 assertions show explicit outcomes, weighted coverage, and provenance', async ({ page, request }) => {
  const target = await (await request.post(`${API}/targets`, { data: {
    name: 'Engine V2 demo', endpoint_url: DEMO, request_template: { message: '' },
    prompt_field: 'message', response_field: 'missing',
  } })).json()
  const assertion = (evaluator: string, config: Record<string, unknown>, when_status_codes: number[] = []) => ({ evaluator, version: 1, config, when_status_codes })
  const attack = (id: string, severity: string, assertions: ReturnType<typeof assertion>[]) => ({
    id, version: 1, name: id, description: 'Synthetic browser fixture', prompt: 'Say hello', category: 'reliability', severity, assertions,
  })
  const response = await request.post(`${API}/targets/${target.id}/evaluations`, { data: { attack_pack: {
    schema_version: 2, id: 'browser-engine', version: 3, name: 'Browser engine', attacks: [
      attack('metadata-pass', 'low', [assertion('status_code', { allowed: [200] }), assertion('latency', { max_ms: 10000 }), assertion('json_schema', { source: 'document', schema_definition: { type: 'object', required: ['response'] } })]),
      attack('status-fail', 'critical', [assertion('status_code', { allowed: [201] })]),
      attack('text-error', 'high', [assertion('regex_match', { pattern: 'safe' })]),
      attack('status-skip', 'medium', [assertion('status_code', { allowed: [201] }, [201])]),
    ],
  } } })
  expect(response.status()).toBe(201)
  const run = await response.json()
  expect(run.metrics.weighted_score).toBe(20)
  expect(run.metrics.coverage).toBe(66.67)
  await page.goto(`/evaluations/${run.id}`)
  await expect(page.getByRole('heading', { name: 'Some checks could not be evaluated' })).toBeVisible()
  const coverage = page.getByRole('region', { name: 'Evaluation coverage and provenance' })
  await expect(coverage).toContainText('Severity-weighted pass rate: 20%. Coverage: 66.67%.')
  await expect(coverage).toContainText('Pack browser-engine version 3')
  await expect(page.getByText('1 checks detected undesirable behavior; 1 checks had execution errors.')).toBeVisible()
  for (const [outcome, label] of [['passed', 'Pass'], ['failed', 'Fail'], ['errored', 'Execution error'], ['not_applicable', 'Not applicable']]) {
    await page.getByLabel('Filter by outcome').selectOption(outcome)
    await expect(page.locator('.finding')).toHaveCount(1)
    await expect(page.locator('.finding .result-badge')).toHaveText(label)
  }
  await coverage.getByText('Saved definition and fingerprint', { exact: true }).click()
  await expect(coverage.locator('pre').first()).toHaveText(run.pack_digest)
  await page.reload()
  await expect(page.locator('.finding')).toHaveCount(4)
})

test('queued progress and cancellation retain saved evidence', async ({ page, request }) => {
  const target = await (await request.post(`${API}/targets`, { data: {
    name: 'Cancellation fixture', endpoint_url: DEMO, request_template: { message: '' }, prompt_field: 'message', response_field: 'response',
  } })).json()
  const attack = { version: 1, category: 'reliability', description: 'Synthetic check', prompt: 'Hello', severity: 'low', assertions: [{ evaluator: 'status_code', version: 1, config: { allowed: [200] } }] }
  const response = await request.post(`${API}/targets/${target.id}/evaluation-jobs`, { data: { attack_pack: {
    schema_version: 2, id: 'cancellation', version: 1, name: 'Cancellation',
    attacks: Array.from({ length: 50 }, (_, i) => ({ ...attack, id: `check-${i}`, name: `Check ${i}` })),
  } }, headers: { 'Idempotency-Key': 'cancel-browser' } })
  expect(response.status()).toBe(202)
  const run = await response.json()
  await page.goto(`/evaluations/${run.id}`)
  await expect(page.getByRole('progressbar', { name: 'Evaluation progress' })).toBeVisible()
  await expect.poll(async () => (await (await request.get(`${API}/evaluations/${run.id}`)).json()).progress.completed).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Cancel evaluation', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Evaluation cancelled', exact: true })).toBeVisible()
  await expect(page.getByRole('progressbar', { name: 'Evaluation progress' })).toHaveCount(0)
  const stopped = await (await request.get(`${API}/evaluations/${run.id}/results`)).json()
  expect(stopped).toHaveLength(50)
  expect(stopped.some((item: { outcome: string }) => item.outcome === 'untested')).toBeTruthy()
  await page.waitForTimeout(1_000)
  expect(await (await request.get(`${API}/evaluations/${run.id}/results`)).json()).toEqual(stopped)
})

test('save an immutable baseline and compare versioned queued runs', async ({ page, request }) => {
  const target = await (await request.post(`${API}/targets`, { data: {
    name: 'History fixture', endpoint_url: DEMO, request_template: { message: '' }, prompt_field: 'message', response_field: 'response',
  } })).json()
  const attackPack = { schema_version: 2, id: 'history', version: 1, name: 'History', attacks: [{
    id: 'healthy', version: 1, name: 'Healthy response', category: 'reliability', description: 'Synthetic check', prompt: 'Hello', severity: 'low',
    assertions: [{ evaluator: 'status_code', version: 1, config: { allowed: [200] } }],
  }] }
  async function evaluate(version: string) {
    const response = await request.post(`${API}/targets/${target.id}/evaluation-jobs`, { data: { attack_pack: attackPack, versions: { application: version } } })
    expect(response.status()).toBe(202)
    const run = await response.json()
    await expect.poll(async () => (await (await request.get(`${API}/evaluations/${run.id}`)).json()).status).toBe('completed')
    return run.id as number
  }
  const first = await evaluate('v1')
  await page.goto(`/evaluations/${first}`)
  await page.getByLabel('Baseline name', { exact: true }).fill('release-1')
  await page.getByRole('button', { name: 'Save as baseline', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Comparable configuration', exact: true })).toBeVisible()
  const baseline = (await (await request.get(`${API}/targets/${target.id}/baselines`)).json())[0]
  const second = await evaluate('v2')
  await page.goto(`/evaluations/${second}`)
  await page.getByLabel('Compare with baseline', { exact: true }).selectOption(String(baseline.id))
  await expect(page.getByText('0 observed regressions · 0 improvements · 0 execution errors')).toBeVisible()
  await expect(page.getByText(/Insufficient repeats/)).toBeVisible()
  await expect(page.locator('.history-table tbody tr')).toHaveCount(2)
  await expect(page.getByText('Version labels: application: v2')).toBeVisible()
  await page.reload()
  await page.getByLabel('Compare with baseline', { exact: true }).selectOption(String(baseline.id))
  await expect(page.getByRole('heading', { name: 'Comparable configuration', exact: true })).toBeVisible()
  expect((await (await request.get(`${API}/targets/${target.id}/baselines`)).json())[0].run_id).toBe(first)
})
