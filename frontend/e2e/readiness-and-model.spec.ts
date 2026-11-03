import { test, expect, type Page } from '@playwright/test'

async function reachUpload(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: '创建审查会话', exact: true }).click()
  await page.getByRole('button', { name: '下一步:上传材料', exact: true }).click()
}

test('empty upload shows preparation without running gap analysis; pending facts are not missing', async ({ page }) => {
  let gapCalls = 0
  page.on('request', request => { if (request.url().endsWith('/agent/gaps')) gapCalls++ })
  await reachUpload(page)
  await expect(page.getByRole('region', { name: '材料准备' })).toContainText('暂不判断材料缺口')
  await expect(page.getByRole('button', { name: '下一步:确认提取的事实' })).toBeDisabled()
  await expect(page.getByText('材料缺口分析', { exact: true })).toHaveCount(0)
  expect(gapCalls).toBe(0)
  await page.locator('.upload-area.execution input[type=file]').setInputFiles({
    name: 'result.log', mimeType: 'text/plain', buffer: Buffer.from('F1=0.8'),
  })
  await expect(page.getByText('材料已收到，等待核对事实', { exact: true })).toBeVisible()
  await expect(page.locator('.gap-status')).toContainText('未确认不等于材料缺失')
  await expect(page.locator('.gap-status .gap-item')).toHaveCount(0)
  await expect(page.locator('.gap-status .success')).toHaveCount(0)
  expect(gapCalls).toBeGreaterThan(0)
})

test('unknown sufficiency and an empty gap list do not claim materials are sufficient', async ({ page }) => {
  await reachUpload(page)
  await page.route('**/agent/gaps', route => route.fulfill({ json: {
    phase: 'analyzed', sufficiency: 'unknown', gaps: [], summary: '目前无法判断', source: 'heuristic',
  } }))
  await page.locator('.upload-area.execution input[type=file]').setInputFiles({
    name: 'record.txt', mimeType: 'text/plain', buffer: Buffer.from('A plain record.'),
  })
  await expect(page.locator('.gap-status')).toContainText('目前无法确定材料是否充足')
  await expect(page.locator('.gap-status .success')).toHaveCount(0)
})

test('specific model error is visible and fallback only runs on explicit click', async ({ page }) => {
  await reachUpload(page)
  await page.locator('.upload-area.execution input[type=file]').setInputFiles({
    name: 'result.log', mimeType: 'text/plain', buffer: Buffer.from('F1=0.8'),
  })
  await expect(page.locator('.material-list')).toContainText('result.log')
  await page.getByRole('button', { name: '下一步:确认提取的事实' }).click()
  await page.getByRole('button', { name: /全部确认/ }).click()
  await page.getByRole('button', { name: '下一步:运行审查' }).click()
  let primaryCalls = 0
  let fallbackCalls = 0
  await page.route('**/agent/deep-review*', route => {
    const fallback = new URL(route.request().url()).searchParams.get('use_fallback') === 'true'
    if (fallback) fallbackCalls++
    else primaryCalls++
    return route.fulfill({ json: fallback ? {
      status: 'ok_no_findings', message: '', findings: [], coverage: [], llm_available: true,
      requested_model: 'glm-4-flash', response_model: 'glm-4-flash', used_fallback: true,
      fallback_model: 'glm-4-flash', call_error: null,
    } : {
      status: 'llm_call_failed', message: '模型服务当前繁忙，本次复核未完成。', findings: [], coverage: [],
      llm_available: true, requested_model: 'glm-4.7-flash', fallback_model: 'glm-4-flash', used_fallback: false,
      call_error: { kind: 'provider_busy', message: '模型服务当前繁忙', retryable: true, http_status: 429, provider_code: '1305' },
    } })
  })
  await page.getByText('需要进一步建议时，运行模型复核', { exact: true }).click()
  await page.getByRole('button', { name: '运行模型复核', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('模型服务当前繁忙')
  await expect(page.getByRole('alert')).toContainText('1305')
  expect(primaryCalls).toBe(1)
  expect(fallbackCalls).toBe(0)
  await page.getByRole('button', { name: '使用备用模型 glm-4-flash 复核', exact: true }).click()
  await expect(page.locator('.deep-review-panel')).toContainText('响应模型：glm-4-flash')
  await expect(page.locator('.deep-review-panel')).toContainText('本次手动使用备用模型')
  expect(fallbackCalls).toBe(1)
  expect(primaryCalls).toBe(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
})
