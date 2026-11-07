import { expect, test, type Page } from '@playwright/test'

const API = 'http://127.0.0.1:18000'
// Public synthetic credentials provisioned only in serve_browser_tests.py's fresh DB.
const admin = `snt_${'A'.repeat(43)}`
const reader = `snt_${'R'.repeat(43)}`

async function signIn(page: Page, token = admin) {
  await page.getByLabel('Access token', { exact: true }).fill(token)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Current access' })).toBeVisible()
}

test.afterEach(async ({ request }) => {
  const headers = { Authorization: `Bearer ${admin}` }
  const targets = await (await request.get(`${API}/targets`, { headers })).json()
  for (const target of targets) await request.delete(`${API}/targets/${target.id}`, { headers })
})

test('sign-in, queued evaluation, no persistent token, reload and sign-out', async ({ page }) => {
  await page.goto('/targets')
  await expect(page.getByRole('heading', { name: 'Sign in to Sentinel' })).toBeVisible()
  await page.getByLabel('Access token', { exact: true }).fill('not-a-token')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Sign-in failed')
  await signIn(page)
  await expect(page.getByRole('region', { name: 'Current access' })).toContainText('Browser admin · admin')
  await page.getByRole('link', { name: 'Register target', exact: true }).first().click()
  await page.getByLabel('Application name').fill('Authenticated demo')
  await page.getByLabel('Endpoint URL').fill('http://127.0.0.1:18001/security/safe')
  await page.getByLabel('Request JSON template').fill('{"message":""}')
  await page.getByRole('button', { name: 'Register target', exact: true }).click()
  await page.getByLabel('Attack pack', { exact: true }).first().selectOption('sentinel-action-boundaries')
  await page.getByRole('button', { name: 'Run evaluation', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: 'Evaluation completed', exact: true })).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('.finding')).toHaveCount(5)
  const persisted = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage }, cookie: document.cookie }))
  expect(JSON.stringify(persisted)).not.toContain(admin)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Sign in to Sentinel' })).toBeVisible()
  await expect(page.locator('.finding')).toHaveCount(0)
  await signIn(page)
  await expect(page.locator('.finding')).toHaveCount(5)
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.locator('.finding')).toHaveCount(0)
  await expect(page.getByLabel('Access token', { exact: true })).toHaveValue('')
})

test('reader can inspect but cannot mutate, and unauthorized refresh clears data', async ({ page, request }) => {
  await request.post(`${API}/targets`, { headers: { Authorization: `Bearer ${admin}` }, data: {
    name: 'Private reader fixture', endpoint_url: 'http://127.0.0.1:18001/chat',
    request_template: { message: '' }, prompt_field: 'message', response_field: 'response',
  } })
  await page.goto('/targets')
  await signIn(page, reader)
  await expect(page.getByRole('link', { name: 'Private reader fixture', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Delete Private reader fixture', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Delete target', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('cannot perform that operation')
  // Backend tests verify real expiry/revocation. This fixture verifies browser
  // behavior on the resulting 401 without adding a test-only API backdoor.
  await page.route(`${API}/targets`, (route) => route.fulfill({ status: 401, json: { detail: 'A valid access token is required.' } }))
  await page.getByRole('link', { name: 'Overview', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Sign in to Sentinel' })).toBeVisible()
  await expect(page.getByText('Private reader fixture')).toHaveCount(0)
})

test('access discovery outage fails closed and can retry', async ({ page }) => {
  let down = true
  await page.route(`${API}/auth/status`, (route) => down ? route.fulfill({ status: 503, json: {} }) : route.continue())
  await page.goto('/targets')
  await expect(page.getByRole('heading', { name: 'Access settings unavailable' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Targets', exact: true })).toHaveCount(0)
  down = false
  await page.getByRole('button', { name: 'Try again', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Sign in to Sentinel' })).toBeVisible()
})

test('a late response from signed-out access cannot clear the next identity', async ({ page }) => {
  let release: () => void = () => {}
  const gate = new Promise<void>((resolve) => { release = resolve })
  let held = false
  await page.route(`${API}/targets`, async (route) => {
    if (!held && route.request().headers().authorization === `Bearer ${admin}`) {
      held = true
      await gate
      await route.fulfill({ status: 401, json: { detail: 'Expired old access' } })
    } else await route.continue()
  })
  await page.goto('/targets')
  await signIn(page)
  await expect.poll(() => held).toBe(true)
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await signIn(page, reader)
  await expect(page.getByRole('heading', { name: 'No targets registered' })).toBeVisible()
  const oldResponse = page.waitForResponse((response) => response.url() === `${API}/targets` && response.status() === 401)
  release()
  await oldResponse
  await expect(page.getByRole('region', { name: 'Current access' })).toContainText('Browser reader · reader')
  await expect(page.getByRole('heading', { name: 'No targets registered' })).toBeVisible()
})

test('switching project tokens clears prior data and blocks direct report access', async ({ page, request }) => {
  const other = `snt_${'B'.repeat(43)}`
  const auth = { Authorization: `Bearer ${other}` }
  const response = await request.post(`${API}/targets`, { headers: auth, data: {
    name: 'Other project private target', endpoint_url: 'http://127.0.0.1:18001/security/safe',
    request_template: { message: '' }, prompt_field: 'message', response_field: 'response',
  } })
  expect(response.status()).toBe(201)
  const target = await response.json()
  try {
    const packs = await (await request.get(`${API}/attack-packs`, { headers: auth })).json()
    const run = await (await request.post(`${API}/targets/${target.id}/evaluation-jobs`, {
      headers: auth, data: { attack_pack: packs.find((pack: { id: string }) => pack.id === 'sentinel-action-boundaries') },
    })).json()
    await page.goto('/targets')
    await signIn(page, other)
    await expect(page.getByRole('region', { name: 'Current access' })).toContainText('Browser other organization / Browser other project')
    await expect(page.getByRole('link', { name: target.name, exact: true })).toBeVisible()
    await page.goto(`/evaluations/${run.id}`)
    await signIn(page, other)
    await expect(page.getByRole('heading', { name: 'Evaluation completed', exact: true })).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await signIn(page, admin)
    await expect(page.locator('.finding')).toHaveCount(0)
    await expect(page.getByText(target.name, { exact: true })).toHaveCount(0)
    expect((await request.get(`${API}/evaluations/${run.id}`, { headers: { Authorization: `Bearer ${admin}` } })).status()).toBe(404)
    await page.getByRole('link', { name: 'Targets', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'No targets registered' })).toBeVisible()
  } finally {
    await request.delete(`${API}/targets/${target.id}`, { headers: auth })
  }
})
