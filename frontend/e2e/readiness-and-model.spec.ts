import { test, expect, type Page } from '@playwright/test'

async function reachUpload(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: '创建审查会话', exact: true }).click()
  await page.getByRole('button', { name: '下一步:上传材料', exact: true }).click()
}

test('upload proceeds to fact confirmation without redundant cards or gap requests', async ({ page }) => {
  let gapCalls = 0
  page.on('request', request => { if (request.url().endsWith('/agent/gaps')) gapCalls++ })
  await reachUpload(page)
  await expect(page.getByRole('button', { name: '下一步:确认提取的事实' })).toBeDisabled()
  await expect(page.getByText('材料缺口分析', { exact: true })).toHaveCount(0)
  expect(gapCalls).toBe(0)
  await page.locator('.upload-area.execution input[type=file]').setInputFiles({
    name: 'result.log', mimeType: 'text/plain', buffer: Buffer.from('F1=0.8'),
  })
  await expect(page.locator('.material-list')).toContainText('result.log')
  await expect(page.locator('.gap-status')).toHaveCount(0)
  await page.getByRole('button', { name: '下一步:确认提取的事实' }).click()
  await expect(page.getByRole('button', { name: /全部确认/ })).toBeVisible()
  expect(gapCalls).toBe(0)
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
