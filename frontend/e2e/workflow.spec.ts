import { test, expect } from '@playwright/test'

test.beforeEach(async ({ browser }, testInfo) => {
  testInfo.annotations.push({ type: 'browser_version', description: browser.version() })
})

test('create, upload, confirm, answer, revise, practice and refresh', async ({ page }, testInfo) => {
  const errors: string[] = []
  const fitsViewport = async () => expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto('/')
  await fitsViewport()
  await page.getByPlaceholder('例如:设备故障预测模型对比实验').fill('浏览器回归示例')
  await page.getByPlaceholder('例如:模型 A 比基线 B 更能预测新设备的故障。').fill('模型A优于基线B，可预测新设备')
  await page.getByRole('button', { name: '创建审查会话', exact: true }).click()
  await page.getByRole('button', { name: '下一步:上传材料', exact: true }).click()
  await expect(page.getByRole('heading', { name: '第二步:收集材料' })).toBeVisible()
  const execution = page.locator('.upload-area.execution')
  await execution.locator('input[type=file]').setInputFiles({ name: 'entities.json', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ train_entity_ids: ['X', 'Y'], test_entity_ids: ['Y'] })) })
  await expect(execution.getByText(/提取到.*待确认事实/)).toBeVisible()
  await fitsViewport()
  await page.getByRole('button', { name: '下一步:确认提取的事实' }).click()
  await page.getByRole('button', { name: /全部确认/ }).click()
  await fitsViewport()
  await page.getByRole('button', { name: '下一步:运行审查' }).click()
  await expect(page.getByText('提供的训练/测试实体编号存在交集，与未见实体主张冲突')).toBeVisible()
  await fitsViewport()

  await page.getByRole('button', { name: '生成追问', exact: true }).click()
  const question = page.locator('.followup-card.pending').first()
  await question.locator('textarea').fill('基线为B，独立运行结果尚需补充。')
  await question.getByRole('button', { name: '保存回答并提取事实' }).click()
  const answered = page.locator('.followup-card.answered').first()
  await expect(answered.getByRole('button', { name: '请先核对全部新事实' })).toBeDisabled()
  const confirmations = answered.getByRole('button', { name: '确认无误', exact: true })
  const pendingCount = await confirmations.count()
  for (let index = 0; index < pendingCount; index++) {
    await confirmations.first().click()
    await expect(confirmations).toHaveCount(pendingCount - index - 1)
  }
  await answered.getByRole('button', { name: '重新审查并查看变化' }).click()
  await expect(page.getByText('审查已更新，请查看变化说明。')).toBeVisible()
  await page.getByRole('button', { name: '去修改与复查' }).click()
  await expect(page.getByRole('heading', { name: '第五步：修改、复查与迁移练习' })).toBeVisible()
  await page.locator('.vdiff-run-area textarea').fill('尚未修复，先核对当前发现')
  await page.getByRole('button', { name: '运行版本差异复审' }).click()
  await expect(page.getByText('版本差异复审完成', { exact: true })).toBeVisible()
  await expect(page.getByRole('region', { name: '修改后的实际验证' })).toContainText('问题仍在')
  await page.getByRole('button', { name: '生成迁移题', exact: true }).click()
  await page.locator('.migration-answer-area textarea').fill('应先核对两个集合中的实体是否重叠，再决定是否能描述未见实体。')
  await page.getByRole('button', { name: '提交作答', exact: true }).click()
  await expect(page.getByText('本次未评分', { exact: true })).toBeVisible()
  await expect(page.getByText('已掌握', { exact: true })).toHaveCount(0)
  await page.reload()
  await expect(page.getByRole('heading', { name: '第五步：修改、复查与迁移练习' })).toBeVisible()
  await expect(page.getByText('本次未评分', { exact: true })).toBeVisible()
  await expect(page.locator('.migration-answer-area textarea')).toHaveValue('应先核对两个集合中的实体是否重叠，再决定是否能描述未见实体。')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
  expect(overflow).toBe(false)
  await page.screenshot({ path: testInfo.outputPath('workflow.png'), fullPage: true })
  expect(errors).toEqual([])
})

test('invalid persisted step recovers to a usable page', async ({ page }) => {
  await page.goto('/')
  await page.evaluate(() => {
    localStorage.setItem('yanzheng_step', 'invalid-step')
    localStorage.setItem('yanzheng_session', '{bad json')
  })
  await page.reload()
  await expect(page.getByRole('button', { name: '创建审查会话', exact: true })).toBeVisible()
})

test('upload failure keeps existing materials and retry remains usable', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: '创建审查会话', exact: true }).click()
  await page.getByRole('button', { name: '下一步:上传材料', exact: true }).click()
  const execution = page.locator('.upload-area.execution')
  const input = execution.locator('input[type=file]')
  await input.setInputFiles({ name: 'first.log', mimeType: 'text/plain', buffer: Buffer.from('F1=0.8') })
  await expect(page.locator('.material-list').getByText('first.log', { exact: true })).toBeVisible()
  await execution.getByRole('radio', { name: /替换旧版本/ }).check()
  await input.setInputFiles({ name: 'broken.docx', mimeType: 'application/octet-stream', buffer: Buffer.from('not a zip') })
  await expect(execution.locator('.error')).toContainText('损坏')
  await expect(page.locator('.material-list').getByText('first.log', { exact: true })).toBeVisible()
  await input.setInputFiles({ name: 'second.log', mimeType: 'text/plain', buffer: Buffer.from('F1=0.9') })
  await expect(page.locator('.material-list').getByText('second.log', { exact: true })).toBeVisible()
  await expect(page.locator('.material-list').getByText('first.log', { exact: true })).toHaveCount(0)
  await execution.getByText('提供可自动核对的结果表', { exact: true }).click()
  const downloadReady = page.waitForEvent('download')
  await execution.getByRole('link', { name: '下载比较结果表', exact: true }).click()
  expect((await downloadReady).suggestedFilename()).toBe('comparison.csv')
})

test('program results remain visible and rejected model output has no repair actions', async ({ page }, testInfo) => {
  await page.goto('/')
  await page.getByPlaceholder('例如:模型 A 比基线 B 更能预测新设备的故障。').fill('训练与测试原始图片编号无交集，unseen原图是测试目标')
  await page.getByRole('button', { name: '创建审查会话', exact: true }).click()
  await page.getByRole('button', { name: '下一步:上传材料', exact: true }).click()
  await page.locator('.upload-area.execution input[type=file]').setInputFiles({ name: 'entities.json', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ train_entity_ids: [1, 2], test_entity_ids: [2, 3], evaluation_scope: 'digits-v1' })) })
  await expect(page.locator('.upload-area.execution').getByText(/提取到.*待确认事实/)).toBeVisible()
  await page.getByRole('button', { name: '下一步:确认提取的事实' }).click()
  await page.getByRole('button', { name: /全部确认/ }).click()
  await page.getByRole('button', { name: '下一步:运行审查' }).click()
  await expect(page.getByRole('region', { name: '程序核对结果' })).toContainText('交集1个')
  // The backend rejection contract is covered by system tests. This response
  // tests that the UI never reconstructs repair instructions from rejected items.
  await page.route('**/agent/deep-review', route => route.fulfill({ json: {
    status: 'needs_evidence', message: '未采用修改操作', findings: [], coverage: [], llm_available: true,
    unverified: [{ title: '引用不匹配', reason: '证据编号不存在，未采用修改操作。' }], checks: [],
    validation_note: '请补充原始记录后验证。',
  } }))
  await page.getByText('需要进一步建议时，运行模型复核', { exact: true }).click()
  await page.getByRole('button', { name: '运行模型复核', exact: true }).click()
  await expect(page.getByRole('region', { name: '未采纳的模型输出' })).toContainText('引用不匹配')
  await expect(page.locator('.deep-finding .finding-suggestion')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('grounded-review.png'), fullPage: true })
})
