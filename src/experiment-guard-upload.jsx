import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import ContextCards from './beautiful-ui/ContextCards'
import CodeBlock from './beautiful-ui/CodeBlock'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import './beautiful-ui/foundation.css'
import './experiment-guard-upload.css'

const MAX_FILE_BYTES = 10 * 1024 * 1024
const MAX_TEXT_LENGTH = 40000
const MAX_PDF_PAGES = 30
const ACCEPTED = ['pdf', 'docx', 'txt', 'md', 'csv', 'json', 'ipynb', 'py', 'js', 'ts', 'log']
const CODE_EXTENSIONS = new Set(['py', 'js', 'ts', 'ipynb'])

function extension(name) {
  return name.split('.').pop()?.toLowerCase() || ''
}

async function readPdf(file) {
  const pdfjs = await import('pdfjs-dist')
  pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl
  const task = pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) })
  const document = await task.promise
  const totalPages = document.numPages
  const pages = Math.min(totalPages, MAX_PDF_PAGES)
  const parts = []
  for (let pageNumber = 1; pageNumber <= pages; pageNumber += 1) {
    const page = await document.getPage(pageNumber)
    const content = await page.getTextContent()
    parts.push(content.items.map((item) => item.str || '').join(' '))
    if (parts.join('\n').length >= MAX_TEXT_LENGTH) break
  }
  await task.destroy()
  return { text: parts.join('\n'), note: totalPages > pages ? `仅读取前 ${pages} 页` : '' }
}

async function readDocx(file) {
  const module = await import('mammoth/mammoth.browser')
  const mammoth = module.default || module
  const result = await mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() })
  return { text: result.value, note: result.messages?.length ? '原文中的图片和复杂格式未提取' : '' }
}

async function readNotebook(file) {
  const notebook = JSON.parse(await file.text())
  if (!Array.isArray(notebook.cells)) throw new Error('这份 Notebook 文件无法识别。')
  return { text: notebook.cells.map((cell) => Array.isArray(cell.source) ? cell.source.join('') : cell.source || '').join('\n\n'), note: '已提取单元格文字；输出图像未读取' }
}

async function readMaterial(file) {
  const ext = extension(file.name)
  if (!ACCEPTED.includes(ext)) throw new Error('暂不支持这个格式。请用 PDF、DOCX 或常见文本文件。')
  if (file.size > MAX_FILE_BYTES) throw new Error('文件超过 10 MB，请先压缩或拆分。')
  const result = ext === 'pdf' ? await readPdf(file) : ext === 'docx' ? await readDocx(file) : ext === 'ipynb' ? await readNotebook(file) : { text: await file.text(), note: '' }
  const cleaned = result.text.replace(/\u0000/g, '').trim()
  if (!cleaned) throw new Error(ext === 'pdf' ? '没有读到文字。这可能是扫描版 PDF，请先进行 OCR。' : '文件中没有可读取的文字。')
  const truncated = cleaned.length > MAX_TEXT_LENGTH
  return { text: cleaned.slice(0, MAX_TEXT_LENGTH), note: [result.note, truncated ? '文字仅保留前 4 万字' : ''].filter(Boolean).join('；'), ext }
}

function MaterialUpload() {
  const inputRef = useRef(null)
  const [role, setRole] = useState('plan')
  const [materials, setMaterials] = useState([])
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const reset = () => { setMaterials([]); setStatus('') }
    window.addEventListener('experiment-guard:reset', reset)
    return () => window.removeEventListener('experiment-guard:reset', reset)
  }, [])

  async function acceptFiles(fileList) {
    const files = Array.from(fileList || []).slice(0, 3)
    if (!files.length) return
    setBusy(true)
    for (const file of files) {
      try {
        setStatus(`正在读取 ${file.name}…`)
        const result = await readMaterial(file)
        const item = { name: file.name, role, ...result }
        window.dispatchEvent(new CustomEvent('experiment-guard:material', { detail: item }))
        setMaterials((current) => [...current, item].slice(-3))
        setStatus(`${file.name} 已加入${role === 'plan' ? '实验计划' : '执行材料'}。${result.note}`)
      } catch (error) {
        setStatus(`${file.name}：${error.message || '读取失败。'}`)
      }
    }
    setBusy(false)
    if (inputRef.current) inputRef.current.value = ''
  }

  const chunks = materials.map((item, index) => ({
    title: `${index + 1}. ${item.name}`,
    chars: `${item.text.length.toLocaleString('zh-CN')} 字`,
    body: item.text.slice(0, 180) + (item.text.length > 180 ? '…' : ''),
    source: `本机文件 · ${item.role === 'plan' ? '实验计划' : '执行材料'}`,
    badge: item.ext.toUpperCase().slice(0, 3),
    tone: item.role === 'plan' ? 'bg-accent' : 'bg-green',
  }))
  const code = [...materials].reverse().find((item) => CODE_EXTENSIONS.has(item.ext))

  return <section className="upload-workspace" aria-labelledby="upload-title">
    <div className="upload-heading">
      <div><span className="upload-kicker">材料输入</span><h3 id="upload-title">上传实验材料</h3></div>
      <span className="upload-local">只在本机读取</span>
    </div>
    <p className="upload-description">提取出的文字会放入下方对应文本框，并参与现有规则检查。文件不会传到服务器；图片、图表和扫描页暂不分析。</p>
    <div className="upload-controls">
      <label htmlFor="upload-role">材料属于</label>
      <select id="upload-role" value={role} onChange={(event) => setRole(event.target.value)} disabled={busy}>
        <option value="plan">实验计划</option><option value="execution">执行材料</option>
      </select>
    </div>
    <div className="upload-dropzone" onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); if (!busy) acceptFiles(event.dataTransfer.files) }}>
      <span className="upload-icon" aria-hidden="true">↑</span>
      <div><strong>拖放文件到这里</strong><small>或选择 PDF、DOCX、TXT、MD、CSV、JSON、代码文件</small></div>
      <button type="button" onClick={() => inputRef.current?.click()} disabled={busy}>选择文件</button>
      <input ref={inputRef} type="file" accept=".pdf,.docx,.txt,.md,.csv,.json,.ipynb,.py,.js,.ts,.log" multiple hidden onChange={(event) => acceptFiles(event.target.files)} />
    </div>
    <p className="upload-hint">单个文件最多 10 MB；一次最多 3 个。提取文字会保存在本浏览器草稿，提交前请删除敏感信息。</p>
    {status && <p className="upload-status" role="status">{status}</p>}
    {chunks.length > 0 && <div className="upload-evidence"><ContextCards chunks={chunks} labels={{ header: '已读取的材料', count: String(chunks.length) }} /></div>}
    {code && <div className="upload-code"><CodeBlock filename={code.name} lines={code.text.split(/\r?\n/).slice(0, 14)} code={code.text} labels={{ copy: '复制', copied: '已复制' }} /></div>}
  </section>
}

const root = document.getElementById('material-upload-root')
if (root) createRoot(root).render(<MaterialUpload />)
