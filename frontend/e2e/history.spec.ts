import { test, expect } from '@playwright/test'

test('history is always accessible and distinguishes empty records from loading failure', async ({ page }) => {
  await page.goto('/')
  const opener = page.getByRole('button', { name: '历史会话', exact: true })
  await opener.click()
  const dialog = page.getByRole('dialog', { name: '历史审查会话' })
  await expect(dialog).toContainText('当前浏览器没有可用的历史会话')
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(opener).toBeFocused()

  let fail = true
  await page.route('**/api/sessions', route => route.fulfill(fail
    ? { status: 503, json: { detail: 'temporarily unavailable' } }
    : { json: [] }))
  await opener.click()
  await expect(dialog.getByRole('alert')).toContainText('暂时无法读取历史会话')
  await expect(dialog.getByText(/当前浏览器没有可用/)).toHaveCount(0)
  fail = false
  await dialog.getByRole('button', { name: '刷新列表', exact: true }).click()
  await expect(dialog).toContainText('当前浏览器没有可用的历史会话')
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(opener).toBeFocused()
})

test('untitled history remains visible and can be reopened from an active review', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '创建审查会话', exact: true }).click()
  await page.getByRole('button', { name: '下一步:上传材料', exact: true }).click()
  await page.locator('.upload-area.execution input[type=file]').setInputFiles({
    name: 'untitled.log', mimeType: 'text/plain', buffer: Buffer.from('F1=0.8'),
  })
  await expect(page.locator('.material-list')).toContainText('untitled.log')
  await page.getByRole('button', { name: '新建审查', exact: true }).click()
  await page.getByLabel('审查标题', { exact: true }).fill('第二个会话')
  await page.getByRole('button', { name: '创建审查会话', exact: true }).click()
  await page.getByRole('button', { name: '下一步:上传材料', exact: true }).click()
  await page.locator('.upload-area.execution input[type=file]').setInputFiles({
    name: 'second.log', mimeType: 'text/plain', buffer: Buffer.from('F1=0.9'),
  })
  await expect(page.locator('.material-list')).toContainText('second.log')
  await page.getByRole('button', { name: '历史会话', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '历史审查会话' })
  await expect(dialog.locator('.session-history-item')).toHaveCount(2)
  await expect(dialog.locator('.session-history-item').first()).toContainText('第二个会话')
  await dialog.getByRole('button', { name: /未命名审查/ }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('.material-list')).toContainText('untitled.log')
  await expect(page.locator('.material-list')).not.toContainText('second.log')
  await page.reload()
  await expect(page.locator('.material-list')).toContainText('untitled.log')
  await page.getByRole('button', { name: '历史会话', exact: true }).click()
  await expect(dialog.locator('.session-history-item')).toHaveCount(2)
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(page.locator('.material-list')).toContainText('untitled.log')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
})

test('a stale history entry does not clear the current review', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '创建审查会话', exact: true }).click()
  await page.getByRole('button', { name: '下一步:上传材料', exact: true }).click()
  await page.locator('.upload-area.execution input[type=file]').setInputFiles({
    name: 'kept.log', mimeType: 'text/plain', buffer: Buffer.from('F1=0.8'),
  })
  await expect(page.locator('.material-list')).toContainText('kept.log')
  await page.getByRole('button', { name: '历史会话', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '历史审查会话' })
  const id = await page.evaluate(() => JSON.parse(localStorage.getItem('yanzheng_session')!).session_id as string)
  await page.route(`**/api/sessions/${id}`, route => route.fulfill({ status: 404, json: { detail: '会话不存在' } }))
  await dialog.getByRole('button', { name: /未命名审查/ }).click()
  await expect(dialog.getByRole('alert')).toContainText('当前审查仍然保留')
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(page.locator('.material-list')).toContainText('kept.log')
})
