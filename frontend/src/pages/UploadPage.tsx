import { useCallback, useEffect, useRef, useState } from 'react'
import type { GapAnalysis, IngestResponse, MaterialMeta, MaterialRole } from '../types'
import { addTextMaterial, analyzeGaps, listMaterials, uploadFile } from '../api'
import { DEMO_EXECUTION, DEMO_PLAN } from '../demo-data'

interface Props {
  sessionId: string
  onNext: () => void
  onBack: () => void
}

/** 单个上传区域:计划或执行,各自独立的上传按钮和粘贴框。
 * 已有同角色材料时,可选择"补充"(追加)或"替换旧版本"(先清空再上传)。
 */
function UploadArea({
  sessionId,
  role,
  existingCount,
  onUploaded,
}: {
  sessionId: string
  role: MaterialRole
  /** 当前该角色已有材料数(>0 时显示模式选择) */
  existingCount: number
  onUploaded: () => void
}) {
  const isPlan = role === 'plan'
  const [pasteMode, setPasteMode] = useState(false)
  const [pasteName, setPasteName] = useState(isPlan ? 'plan.md' : 'train.py')
  const [pasteContent, setPasteContent] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [lastResult, setLastResult] = useState<IngestResponse | null>(null)
  const [uploadMode, setUploadMode] = useState<'append' | 'replace'>('append')
  const fileRef = useRef<HTMLInputElement>(null)

  async function handleUpload(file: File) {
    if (file.size > 5 * 1024 * 1024) { setError('单个文件不能超过5 MB'); return }
    setBusy(true)
    setError('')
    try {
      const res = await uploadFile(sessionId, role, file, uploadMode)
      setLastResult(res)
      onUploaded()
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传失败')
    } finally {
      setBusy(false)
    }
  }

  async function handlePaste() {
    if (!pasteContent.trim()) return
    setBusy(true)
    setError('')
    try {
      const res = await addTextMaterial(sessionId, role, pasteName, pasteContent, uploadMode)
      setLastResult(res)
      setPasteContent('')
      onUploaded()
    } catch (e) {
      setError(e instanceof Error ? e.message : '提交失败')
    } finally {
      setBusy(false)
    }
  }

  function loadDemo() {
    setPasteMode(true)
    setPasteName(isPlan ? 'plan.md' : 'train.py')
    setPasteContent(isPlan ? DEMO_PLAN : DEMO_EXECUTION)
    setError('')
  }

  return (
    <div className={`upload-area ${role}`}>
      <div className="upload-area-header">
        <span className={`role-tag ${role}`}>
          {isPlan ? '计划' : '执行'}
        </span>
        <span className="upload-area-title">
          {isPlan ? '实验计划' : '实际执行(代码/配置/结果)'}
        </span>
      </div>
      <p className="muted upload-area-desc">
        {isPlan
          ? '上传实验设计文档、研究方案等,说明你打算怎么做。'
          : '上传实际代码、配置文件、运行结果等,说明你实际怎么做的。'}
      </p>

      {existingCount > 0 && (
        <div className="upload-mode-select">
          <span className="muted">已有 {existingCount} 份{isPlan ? '计划' : '执行'}材料,本次上传:</span>
          <label className={`mode-option ${uploadMode === 'append' ? 'active' : ''}`}>
            <input
              type="radio"
              name={`mode-${role}`}
              value="append"
              checked={uploadMode === 'append'}
              onChange={() => setUploadMode('append')}
            />
            补充(保留旧材料,追加新内容)
          </label>
          <label className={`mode-option ${uploadMode === 'replace' ? 'active' : ''}`}>
            <input
              type="radio"
              name={`mode-${role}`}
              value="replace"
              checked={uploadMode === 'replace'}
              onChange={() => setUploadMode('replace')}
            />
            替换旧版本(新材料解析成功后归档旧材料)
          </label>
        </div>
      )}

      {!isPlan && <details className="workflow-details">
        <summary>提供可自动核对的结果表</summary>
        <p>填入本次真实结果。只有核对过条件确实相同时才填写 same；缺项会继续提示需要核实。</p>
        <p><a href="/templates/comparison.csv" download>下载比较结果表</a>　
          <a href="/templates/stability.csv" download>下载重复运行结果表</a></p>
        <p className="muted">自动核对只涉及所提供的点估计或有限运行的样本标准差，不代替显著性与总体泛化检验。</p>
      </details>}

      <div className="upload-actions">
        <button disabled={busy} onClick={() => fileRef.current?.click()}>
          上传文件
        </button>
        <button disabled={busy} onClick={() => setPasteMode(!pasteMode)}>
          {pasteMode ? '收起粘贴框' : '粘贴文本内容'}
        </button>
        <button disabled={busy} onClick={loadDemo} title="一键填入演示材料">
          加载示例材料
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.md,.markdown,.py,.ipynb,.js,.ts,.java,.go,.rs,.sh,.c,.cpp,.h,.hpp,.cs,.sql,.r,.rb,.kt,.swift,.json,.yaml,.yml,.toml,.ini,.csv,.log,.pdf,.docx,.xlsx"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) handleUpload(f)
            e.target.value = ''
          }}
        />
      </div>

      {pasteMode && (
        <div className="paste-box">
          <input
            value={pasteName}
            onChange={(e) => setPasteName(e.target.value)}
            placeholder={isPlan ? '文件名,如 plan.md' : '文件名,如 train.py'}
          />
          <textarea
            rows={6}
            value={pasteContent}
            onChange={(e) => setPasteContent(e.target.value)}
            placeholder={
              isPlan
                ? '粘贴实验计划、研究方案…'
                : '粘贴代码、配置或运行结果…'
            }
          />
          <button className="primary" disabled={busy} onClick={handlePaste}>
            提交文本材料
          </button>
        </div>
      )}

      {error && <div className="error">{error}</div>}

      {lastResult && (
        <div className="ingest-result">
          <h4>
            {lastResult.filename}({isPlan ? '计划' : '执行'})
          </h4>
          {lastResult.ocr_required && (
            <div className="warn">
              解析缺口:{lastResult.ocr_note || '该材料含未提取内容,需 OCR。'}
            </div>
          )}
          <div>提取到 {lastResult.extracted_facts.length} 条待确认事实</div>
          {lastResult.dropped.length > 0 && (
            <div className="warn">
              <ul>{lastResult.dropped.map((reason, i) => <li key={i}>{reason}</li>)}</ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** 第二步:收集材料。计划与执行分两个独立区域上传。
 * 材料列表下方自动显示缺口分析,每上传一份材料自动刷新。
 */
export function UploadPage({ sessionId, onNext, onBack }: Props) {
  const [materials, setMaterials] = useState<MaterialMeta[]>([])
  const [gapResponse, setGapResponse] = useState<{ version: string; value: GapAnalysis } | null>(null)

  const refresh = useCallback(async () => {
    const value = await listMaterials(sessionId)
    setMaterials(value)
    return value
  }, [sessionId])

  useEffect(() => {
    let active = true
    listMaterials(sessionId).then((value) => { if (active) setMaterials(value) })
      .catch(() => { /* the upload controls still allow retry */ })
    return () => { active = false }
  }, [sessionId])

  const materialVersion = materials.map((m) => m.material_id).join(',')
  const gapVersion = `${sessionId}:${materialVersion}`
  const gaps = gapResponse?.version === gapVersion ? gapResponse.value : null
  useEffect(() => {
    if (!materialVersion) return
    let active = true
    analyzeGaps(sessionId).then((value) => { if (active) setGapResponse({ version: gapVersion, value }) }).catch(() => {})
    return () => { active = false }
  }, [sessionId, materialVersion, gapVersion])

  const planMaterials = materials.filter((m) => m.role === 'plan')
  const execMaterials = materials.filter((m) => m.role === 'execution')

  const priorityColor: Record<string, string> = {
    high: '#d93025',
    medium: '#e37400',
    low: '#1a73e8',
  }
  const sufficiencyLabel: Record<string, string> = {
    sufficient: '基础清单已覆盖',
    partial: '有待核实项',
    insufficient: '有待补充项',
    unknown: '尚无法判断',
  }

  return (
    <div className="page">
      <h2>第二步:收集材料</h2>
      <p className="muted">
        分别上传<strong>实验计划</strong>和<strong>实际执行</strong>材料——
        两者不一致本身就是重要线索。支持文本、代码、CSV、PDF、DOCX和XLSX。图像、公式和扫描内容会明确标出解析缺口。
      </p>

      <div className="upload-areas">
        <UploadArea
          sessionId={sessionId}
          role="plan"
          existingCount={planMaterials.length}
          onUploaded={refresh}
        />
        <UploadArea
          sessionId={sessionId}
          role="execution"
          existingCount={execMaterials.length}
          onUploaded={refresh}
        />
      </div>

      {materials.length > 0 && (
        <div className="material-list">
          <h4>已上传材料</h4>
          {planMaterials.length > 0 && (
            <div className="material-group">
              <div className="material-group-label">计划({planMaterials.length})</div>
              {planMaterials.map((m) => (
                <div key={m.material_id} className="material-item">
                  <span className="role-tag plan">计划</span>
                  <span>{m.filename}</span>
                  <span className="muted">{m.content_length} 字符</span>
                  {m.ocr_required && <span className="warn">需 OCR</span>}
                </div>
              ))}
            </div>
          )}
          {execMaterials.length > 0 && (
            <div className="material-group">
              <div className="material-group-label">执行({execMaterials.length})</div>
              {execMaterials.map((m) => (
                <div key={m.material_id} className="material-item">
                  <span className="role-tag execution">执行</span>
                  <span>{m.filename}</span>
                  <span className="muted">{m.content_length} 字符</span>
                  {m.ocr_required && <span className="warn">需 OCR</span>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {materials.length === 0 && <section className="gap-status" aria-label="材料准备">
        <strong>等待上传材料</strong>
        <p>尚未上传材料，暂不判断材料缺口。请先提供实验计划和实际执行材料。</p>
      </section>}

      {/* 未确认的信息不能被当成缺失；只有实际分析完成才展示结论。 */}
      {materials.length > 0 && gaps && (
        <div className="gap-status">
          <div className="agent-section-header">
            <span>{gaps.phase === 'awaiting_confirmation' ? '材料已收到，等待核对事实' : '材料缺口分析'}</span>
            <span className={`agent-tag suf-${gaps.sufficiency}`}>
              {gaps.phase === 'awaiting_confirmation' ? '待确认' : (sufficiencyLabel[gaps.sufficiency] ?? gaps.sufficiency)}
            </span>
          </div>
          {gaps.summary && <p className="muted">{gaps.summary}</p>}
          {gaps.phase === 'awaiting_confirmation' || gaps.phase === 'awaiting_materials' ? null : gaps.gaps.length === 0 ? (
            <div className={gaps.sufficiency === 'sufficient' ? 'success' : 'muted'}>
              {gaps.sufficiency === 'sufficient'
                ? '已核对的材料清单暂未发现缺项，仍需运行后续审查。'
                : '目前无法确定材料是否充足，请核对提取事实和原始材料。'}
            </div>
          ) : (
            <div className="agent-subsection">
              {gaps.gaps.map((g, i) => (
                <div key={i} className="agent-item gap-item">
                  <span
                    className="agent-severity"
                    style={{ color: priorityColor[g.priority] ?? '#5f6368' }}
                  >
                    [{g.priority}]
                  </span>
                  <strong>{g.missing}</strong>
                  <div className="muted">原因:{g.reason}</div>
                  <div className="muted">如何补充:{g.how_to_provide}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="page-actions">
        <button onClick={onBack}>上一步</button>
        <button className="primary" onClick={onNext} disabled={materials.length === 0}>
          下一步:确认提取的事实
        </button>
      </div>
    </div>
  )
}
