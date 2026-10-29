const STORAGE_KEY = 'experiment-guard-v1'
const form = document.getElementById('experiment-form')
const reportPanel = document.getElementById('report-panel')
const dataFields = document.getElementById('data-fields')
const systemFields = document.getElementById('system-fields')

const labels = {
  repeatedEntity: { unknown: '尚不清楚', yes: '同一对象有多条记录', no: '每个对象只有一条记录' },
  plannedSplit: { unknown: '尚未确定', entity: '按对象分组', row: '按单条记录随机划分', time: '按时间划分' },
  actualSplit: { unknown: '尚未执行或不清楚', entity: '按对象分组', row: '按单条记录随机划分', time: '按时间划分' },
  preprocessOrder: { unknown: '尚不清楚', train: '划分后，仅用训练集拟合', all: '划分前，用全部数据拟合', none: '没有需拟合的预处理' },
  tuningBudget: { unknown: '尚未说明', comparable: '基本相当', unequal: '明显不一致', 'not-applicable': '不涉及调参' },
  plannedHardware: { unknown: '尚未说明', same: '两个方法使用相同环境', different: '两个方法使用不同环境' },
  actualHardware: { unknown: '尚未执行或不清楚', same: '两个方法使用相同环境', different: '两个方法使用不同环境' },
  sameWorkload: { unknown: '尚未说明', same: '相同', different: '不同' },
  repeatCount: { unknown: '尚未说明', once: '只运行一次', multiple: '多次运行并记录波动' },
}

const examples = {
  data: {
    studyType: 'data',
    claim: '新模型 A 在相同条件下比基线 B 预测设备故障更准确。',
    plan: '从 120 台设备采集多次传感器记录。计划按设备划分训练集与测试集，用准确率比较新模型 A 和基线 B。',
    execution: 'X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)\n# 新模型 A 搜索了 50 组参数；基线 B 使用默认参数',
    repeatedEntity: 'yes', plannedSplit: 'entity', actualSplit: 'row', preprocessOrder: 'unknown', tuningBudget: 'unequal',
  },
  system: {
    studyType: 'system',
    claim: '算法 A 在相同测试负载下比算法 B 的请求响应更快。',
    plan: '计划在同一台机器上用相同的请求集比较算法 A 和 B，分别记录每次请求的响应时间。',
    execution: '运行记录：算法 A 使用 16 核机器，算法 B 使用 8 核机器；两组均处理相同的 1 万条请求，各运行一次。',
    plannedHardware: 'same', actualHardware: 'different', sameWorkload: 'same', repeatCount: 'once',
  },
}

let state = { draft: null, audit: null, history: [], learningAnswer: '', showReference: false }

const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character])
const readable = (field, value) => labels[field]?.[value] || value || '未说明'
const source = (label, value) => `${label}：${value}`
const today = () => new Date().toLocaleString('zh-CN', { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })

function save() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)) } catch { /* 浏览器禁用存储时仍可完成当前页面操作 */ }
}

function load() {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (stored && typeof stored === 'object') state = { ...state, ...stored, history: Array.isArray(stored.history) ? stored.history : [] }
  } catch { /* 忽略不可读取的旧草稿 */ }
}

function syncStudyType() {
  const isData = form.elements.studyType.value === 'data'
  dataFields.hidden = !isData
  dataFields.disabled = !isData
  systemFields.hidden = isData
  systemFields.disabled = isData
}

function collectInput() {
  const input = Object.fromEntries(new FormData(form).entries())
  for (const key of ['claim', 'plan', 'execution']) input[key] = (input[key] || '').trim()
  return input
}

function fill(input) {
  form.reset()
  form.elements.studyType.value = input.studyType || 'data'
  syncStudyType()
  Object.entries(input).forEach(([key, value]) => {
    if (key !== 'studyType' && form.elements[key]) form.elements[key].value = value
  })
  state.draft = collectInput()
  save()
}

function codeLine(text, pattern) {
  const line = text.split(/\r?\n/).find((item) => pattern.test(item))
  return line ? line.trim().slice(0, 180) : ''
}

function finding(id, status, title, evidence, impact, action, question = '') {
  return { id, status, title, evidence, impact, action, question }
}

function audit(input) {
  const items = []
  const hasExecution = input.execution.length > 0
  const hasComparison = /对照|比较|优于|相比|较之|比.{1,12}(好|高|低|快|慢|准确)|\b(vs\.?|versus|compare|baseline)\b/i.test(`${input.claim} ${input.plan}`)

  if (!hasComparison) items.push(finding('comparison', 'missing', '比较对象尚未写清', source('研究主张', input.claim), '目前难以判断怎样的实验结果能够支持这句话。', '说明要比较的两个方法、条件或版本，并写出准备如何比较。', '你希望拿什么作为对照？'))
  if (input.plan.length < 30) items.push(finding('plan-detail', 'missing', '实验计划仍缺少关键安排', source('实验计划', input.plan), '目前无法核对数据或负载、比较条件和评价方式。', '补充实验对象、对照安排和至少一个评价指标。'))

  if (input.studyType === 'data') {
    const repeated = input.repeatedEntity
    const planned = input.plannedSplit
    const actual = input.actualSplit
    const genericSplitLine = codeLine(input.execution, /\btrain_test_split\s*\(|\brandom_split\s*\(/i)
    const groupAwareCode = /\b(GroupShuffleSplit|GroupKFold|StratifiedGroupKFold)\b|\bgroups\s*=|\bgroup_ids?\b/i.test(input.execution)
    const preprocessingLine = codeLine(input.execution, /\bfit_transform\s*\(/i)
    const splitPosition = input.execution.search(/\btrain_test_split\s*\(|\brandom_split\s*\(/i)
    const preprocessingPosition = input.execution.search(/\bfit_transform\s*\(/i)

    if (planned !== 'unknown' && actual !== 'unknown' && planned !== actual) {
      items.push(finding('split-mismatch', 'issue', '计划与填写的实际划分方式不一致', `${source('计划划分', readable('plannedSplit', planned))}\n${source('实际划分', readable('actualSplit', actual))}`, '实验执行与原计划不同，结论适用的对象可能随之改变。', '先核对真实划分代码或记录，再说明最终采用的单位以及原因。'))
    } else if (planned === 'entity' && actual === 'unknown' && genericSplitLine && !groupAwareCode) {
      items.push(finding('split-mismatch', 'review', '计划按对象分组，代码片段尚未显示分组依据', `${source('计划划分', readable('plannedSplit', planned))}\n代码片段：${genericSplitLine}`, '这段代码本身无法证明对象被分到不同集合；也可能在片段之外先完成了分组。', '补充生成训练集和测试集索引的代码，核对同一对象是否只落在一个集合。', '是否有在这段代码之前完成按对象分组的步骤？'))
    }

    if (repeated === 'yes' && (planned === 'row' || actual === 'row')) {
      items.push(finding('entity-overlap', 'review', '同一对象的多条记录可能跨集合', `${source('数据特点', readable('repeatedEntity', repeated))}\n${source('划分单位', readable('actualSplit', actual !== 'unknown' ? actual : planned))}`, '相似记录若跨训练集和测试集，测试结果可能高估对新对象的效果；是否发生交叉仍需检查对象编号。', '检查两集合的对象编号交集。如果目标是预测新对象，考虑按对象分组。', '训练集和测试集是否包含同一个对象？'))
    } else if (repeated === 'unknown' && (planned === 'row' || actual === 'row')) {
      items.push(finding('entity-overlap', 'missing', '需要确认数据是否包含重复对象', source('数据特点', readable('repeatedEntity', repeated)), '划分是否独立，取决于同一对象是否产生多条记录。', '补充数据采集单位和每个对象的记录数。', '同一个对象会出现多次吗？'))
    }

    if (input.preprocessOrder === 'all') {
      items.push(finding('preprocess', 'review', '预处理可能提前使用了测试集信息', source('预处理顺序', readable('preprocessOrder', input.preprocessOrder)), '若均值、标准差或特征选择从全量数据拟合，测试集信息会影响训练流程。', '先划分数据，再只在训练集上拟合需要学习参数的预处理，并把变换应用到测试集。', '哪些预处理步骤需要从数据中学习参数？'))
    } else if (input.preprocessOrder === 'unknown' && preprocessingLine && preprocessingPosition >= 0 && splitPosition > preprocessingPosition) {
      items.push(finding('preprocess', 'review', '代码片段中拟合操作出现在划分之前', `代码片段：${preprocessingLine}`, '代码顺序提示潜在风险，但还需确认该变量是否为全量数据，以及是否存在其他划分步骤。', '补充上下文，核对拟合输入是否包含将来的测试集。'))
    }

    if (input.tuningBudget === 'unequal') {
      items.push(finding('tuning', 'review', '比较方法的调参机会不一致', source('调参安排', readable('tuningBudget', input.tuningBudget)), '结果差异可能同时受到调参机会影响，难以全部归因于方法本身。', '记录各方法的搜索范围与计算预算；给主要基线合理的优化机会，或收窄结论。'))
    }
    if (actual === 'unknown' && !genericSplitLine) {
      items.push(finding('execution', 'missing', '实际数据划分仍无法核对', source('实际划分', readable('actualSplit', actual)), '计划里的划分方式不能代替执行证据。', '完成实验后补充划分记录、对象编号核对结果或关键代码。'))
    }
  } else {
    const planned = input.plannedHardware
    const actual = input.actualHardware
    if (planned === 'same' && actual === 'different') {
      items.push(finding('environment', 'issue', '计划使用同一环境，实际运行环境不同', `${source('计划环境', readable('plannedHardware', planned))}\n${source('实际环境', readable('actualHardware', actual))}`, '观察到的性能差异可能来自硬件或软件环境，不能直接归因于算法。', '尽量在同一环境复跑；若无法做到，记录配置差异并限制结论范围。'))
    } else if (actual === 'different') {
      items.push(finding('environment', 'review', '比较方法使用了不同环境', source('实际环境', readable('actualHardware', actual)), '环境差异可能混入算法差异。', '补充两组硬件、软件和运行参数，并说明怎样控制这些差异。'))
    } else if (actual === 'unknown') {
      items.push(finding('environment', 'missing', '实际运行环境尚未记录', source('实际环境', readable('actualHardware', actual)), '目前无法核对比较是否在相同条件下进行。', '记录硬件、软件版本和关键运行配置。'))
    }
    if (input.sameWorkload === 'different') {
      items.push(finding('workload', 'review', '比较方法使用的测试负载不同', source('测试负载', readable('sameWorkload', input.sameWorkload)), '不同负载可能独立改变运行时间或吞吐量。', '使用相同输入、规模和请求分布；如果做不到，分别报告负载条件。'))
    } else if (input.sameWorkload === 'unknown') {
      items.push(finding('workload', 'missing', '测试负载还需要说明', source('测试负载', readable('sameWorkload', input.sameWorkload)), '没有负载记录，难以复查性能比较是否公平。', '补充输入规模、请求类型和两种方法接收的任务是否一致。'))
    }
    if (input.repeatCount === 'once') {
      items.push(finding('repetition', 'review', '只运行一次，尚无法观察结果波动', source('运行次数', readable('repeatCount', input.repeatCount)), '单次结果可能受系统状态或偶然波动影响。', '在可行的范围内重复运行并报告波动；若资源受限，写明限制。'))
    } else if (input.repeatCount === 'unknown') {
      items.push(finding('repetition', 'missing', '运行次数与波动尚未说明', source('运行次数', readable('repeatCount', input.repeatCount)), '当前材料不足以判断性能结果是否稳定。', '补充运行次数和准备如何报告波动。'))
    }
  }

  if (!hasExecution) items.push(finding('execution-material', 'missing', '还没有实际执行材料', '执行材料：未提供', '本轮只能核对计划和填写的条件，无法验证代码或运行记录。', '完成实验后粘贴关键代码、配置或运行记录，再复查。'))
  if (!items.length) items.push(finding('scope-clear', 'clear', '在当前规则范围内未见明显矛盾', '依据：本页填写的计划与执行条件', '这不等于实验已经有效；未提交的流程和代码仍未检查。', '请指导老师核对研究主张、数据来源和实际执行细节。'))

  const priority = { issue: 0, review: 1, missing: 2, clear: 3 }
  items.sort((a, b) => priority[a.status] - priority[b.status])
  return items
}

function renderSummary(items) {
  const counts = { issue: 0, review: 0, missing: 0 }
  items.forEach((item) => { if (item.status in counts) counts[item.status] += 1 })
  document.getElementById('report-summary').innerHTML = [
    ['明确矛盾', counts.issue], ['潜在风险', counts.review], ['信息不足', counts.missing],
  ].map(([label, count]) => `<span class="summary-pill"><strong>${count}</strong>${label}</span>`).join('')
}

function renderContract(input) {
  const cells = [
    ['研究主张', input.claim],
    ['计划怎样做', input.plan],
    ['执行材料', input.execution || '尚未提供；实际执行仍待核对。'],
  ]
  document.getElementById('contract-view').innerHTML = cells.map(([label, value]) => `<div class="contract-cell"><small>${escapeHTML(label)}</small><p>${escapeHTML(value)}</p></div>`).join('')
}

function renderFindings(items) {
  const statusText = { issue: '明确矛盾', review: '潜在风险', missing: '信息不足', clear: '本项说明' }
  document.getElementById('findings-list').innerHTML = items.map((item, index) => `
    <article class="finding ${item.status}">
      <div class="finding-side"><span>${statusText[item.status]}</span><small>${String(index + 1).padStart(2, '0')}</small></div>
      <div class="finding-body"><h4>${escapeHTML(item.title)}</h4><p class="finding-evidence">${escapeHTML(item.evidence)}</p><p>${escapeHTML(item.impact)}</p><p class="finding-action">下一步：${escapeHTML(item.action)}</p>${item.question ? `<p>需要确认：${escapeHTML(item.question)}</p>` : ''}</div>
    </article>`).join('')
}

function renderHistory() {
  const history = document.getElementById('revision-history')
  history.innerHTML = state.history.length ? state.history.slice().reverse().map((entry, index) => `<div class="history-row"><b>修改 ${state.history.length - index}</b> · ${escapeHTML(entry.time)}<br>${escapeHTML(entry.reason)}<br>${entry.resolved.length ? `本轮已不再出现：${escapeHTML(entry.resolved.join('、'))}` : '本轮没有疑点消失；请继续核对。'}</div>`).join('') : ''
}

function renderLearning(type) {
  const dataCase = '某实验收集了每位用户连续 7 天的使用记录，研究者把全部记录随机分成训练集和测试集，声称模型能够预测从未见过的新用户。你会先核查哪项设计？'
  const systemCase = '研究者声称新算法的响应时间更稳定，却只在一次测试中报告了平均响应时间。你会先核查哪项设计？'
  const dataReference = '参考思路：先核查划分单位。同一用户的多条记录如果进入两个集合，测试可能无法代表“新用户”；还要查看训练集和测试集的用户编号是否交叉。'
  const systemReference = '参考思路：先核查重复运行和结果分布。一次测试的平均值无法展示波动，也不足以支持“更稳定”的主张。'
  document.getElementById('learning-case').textContent = type === 'data' ? dataCase : systemCase
  document.getElementById('learning-answer').value = state.learningAnswer || ''
  const reference = document.getElementById('learning-reference')
  reference.textContent = type === 'data' ? dataReference : systemReference
  reference.hidden = !state.showReference
}

function renderReport() {
  if (!state.audit) { reportPanel.hidden = true; return }
  reportPanel.hidden = false
  renderSummary(state.audit.findings)
  renderContract(state.audit.input)
  renderFindings(state.audit.findings)
  renderHistory()
  renderLearning(state.audit.input.studyType)
}

function createAudit(input) {
  state.audit = { input, findings: audit(input), time: today() }
  state.draft = input
  state.learningAnswer = ''
  state.showReference = false
  save()
  renderReport()
  reportPanel.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' })
}

form.addEventListener('submit', (event) => {
  event.preventDefault()
  const input = collectInput()
  const error = document.getElementById('form-error')
  if (!input.claim || !input.plan) {
    error.textContent = '请先填写研究主张和实验计划。'
    error.hidden = false
    (!input.claim ? form.elements.claim : form.elements.plan).focus()
    return
  }
  error.hidden = true
  state.history = []
  createAudit(input)
})

form.addEventListener('input', () => { state.draft = collectInput(); save() })
form.elements.studyType.addEventListener('change', () => { syncStudyType(); state.draft = collectInput(); save() })
window.addEventListener('experiment-guard:material', (event) => {
  const { role, name, text } = event.detail || {}
  if (!['plan', 'execution'].includes(role) || !text) return
  const field = form.elements[role]
  field.value = [field.value.trim(), `【上传材料：${name}】\n${text}`].filter(Boolean).join('\n\n')
  field.dispatchEvent(new Event('input', { bubbles: true }))
  field.focus()
})

document.getElementById('load-data-sample').addEventListener('click', () => { state.history = []; state.audit = null; state.learningAnswer = ''; state.showReference = false; fill(examples.data); renderReport(); form.scrollIntoView({ behavior: 'smooth', block: 'start' }) })
document.getElementById('load-system-sample').addEventListener('click', () => { state.history = []; state.audit = null; state.learningAnswer = ''; state.showReference = false; fill(examples.system); renderReport(); form.scrollIntoView({ behavior: 'smooth', block: 'start' }) })
document.getElementById('clear-draft').addEventListener('click', () => {
  state = { draft: null, audit: null, history: [], learningAnswer: '', showReference: false }
  window.dispatchEvent(new Event('experiment-guard:reset'))
  form.reset()
  syncStudyType()
  document.getElementById('form-error').hidden = true
  document.getElementById('revision-reason').value = ''
  renderReport()
  save()
})

document.getElementById('recheck').addEventListener('click', () => {
  const status = document.getElementById('revision-status')
  const reason = document.getElementById('revision-reason').value.trim()
  const input = collectInput()
  if (!reason) { status.textContent = '请先写下修改理由。'; document.getElementById('revision-reason').focus(); return }
  if (!input.claim || !input.plan) { status.textContent = '请先补齐研究主张和实验计划。'; return }
  if (JSON.stringify(input) === JSON.stringify(state.audit.input)) { status.textContent = '上方实验内容还没有变化。'; return }
  const previous = state.audit.findings
  const next = audit(input)
  const nextIds = new Set(next.map((item) => item.id))
  const resolved = previous.filter((item) => item.status !== 'clear' && !nextIds.has(item.id)).map((item) => item.title)
  state.history.push({ reason, resolved, time: today() })
  state.audit = { input, findings: next, time: today() }
  state.draft = input
  state.learningAnswer = ''
  state.showReference = false
  status.textContent = `已保存第 ${state.history.length} 次修改。`
  document.getElementById('revision-reason').value = ''
  save()
  renderReport()
  reportPanel.scrollIntoView({ behavior: 'smooth', block: 'start' })
})

document.getElementById('learning-answer').addEventListener('input', (event) => { state.learningAnswer = event.target.value; save() })
document.getElementById('show-reference').addEventListener('click', () => {
  const answer = document.getElementById('learning-answer').value.trim()
  if (!answer) { document.getElementById('learning-answer').focus(); return }
  state.learningAnswer = answer
  state.showReference = true
  save()
  renderLearning(state.audit.input.studyType)
})
document.getElementById('print-report').addEventListener('click', () => window.print())

load()
syncStudyType()
if (state.draft) fill(state.draft)
renderReport()
