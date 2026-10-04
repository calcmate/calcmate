import { useEffect, useState } from 'react'
import {
  getCurrentUser,
  getWorkspaceModels,
  getWorkspaceContextFiles,
  postWorkspaceChat,
  postWorkspaceSandbox,
  postWorkspaceFilePreview,
  postWorkspaceFileWrite,
  postWorkspaceFileCreate,
} from '../api/client.js'

// /ai-workspace — CALCMATE-STREAMLIT-REMAINING-MIGRATION-AI-WORKSPACE-02: dashboard.py
// "💬 AI Workspace"(L2788-2858) 이관. 역할(ws_role)·대화(ws_msgs)·첨부 선택은 이 화면의 React
// state로만 둔다(저장하지 않음). 첨부 context는 선택값만 보내고 서버가 만든다. 프로젝트 파일
// 저장은 원본의 "확인 체크 → 즉시 저장" 대신 미리보기 → 승인 → 서버 SHA 재검증 → 백업 → 저장.
const REPO_OPTIONS = ['sites', 'calculators', 'articles', 'templates']

function errText(res, fallback) {
  if (res?.error?.message) return res.error.message
  if (res?.detail) return typeof res.detail === 'string' ? res.detail : '요청이 거부되었습니다.'
  return fallback
}

export default function AiWorkspace() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [roles, setRoles] = useState([])
  const [role, setRole] = useState('')                       // ws_role
  const [files, setFiles] = useState([])
  const [attachFile, setAttachFile] = useState('')           // ws_file
  const [attachRepo, setAttachRepo] = useState('')           // ws_repo
  const [attachStruct, setAttachStruct] = useState(false)    // ws_struct
  const [messages, setMessages] = useState([])               // ws_msgs
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)

  const [saveName, setSaveName] = useState('generated.html') // ws_save_name
  const [saveContent, setSaveContent] = useState('')         // ws_save_content
  const [sandboxConflict, setSandboxConflict] = useState(false)
  const [target, setTarget] = useState('')                   // ws_tgt
  const [diff, setDiff] = useState(null)                     // 승인 대상(원본 ws_confirm 대체)
  const [notice, setNotice] = useState(null)

  useEffect(() => {
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
    getWorkspaceModels().then((res) => {
      if (res?.success) {
        setRoles(res.data.roles || [])
        setRole(res.data.default || res.data.roles?.[0]?.id || '')
      }
    })
    getWorkspaceContextFiles().then((res) => { if (res?.success) setFiles(res.data.files || []) })
  }, [])

  async function send() {
    const prompt = input.trim()
    if (!prompt || sending || !role) return
    const history = [...messages, { role: 'user', content: prompt }]
    setMessages(history)
    setInput('')
    setSending(true)
    const context = { structure: attachStruct }
    if (attachFile) context.file = attachFile
    if (attachRepo) context.repo = attachRepo
    const res = await postWorkspaceChat(role, history.map((m) => ({ role: m.role, content: m.content })), context)
    setSending(false)
    if (res?.success) {
      setMessages([...history, { role: 'assistant', content: res.data.reply, meta: `${res.data.model} · ${res.data.tokens} tokens` }])
    } else {
      setMessages([...history, { role: 'assistant', content: errText(res, 'AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'), error: true }])
    }
  }

  async function handleSandbox(overwrite) {
    setNotice(null)
    if (!saveContent.trim()) { setNotice({ ok: false, text: '내용이 비어 있습니다.' }); return }
    const res = await postWorkspaceSandbox(saveName, saveContent, overwrite)
    if (res?.success) {
      setSandboxConflict(false)
      setNotice({ ok: true, text: `저장: ${res.data.path}${res.data.overwritten ? ` (기존 파일 백업: ${res.data.backup})` : ''}` })
    } else if (res?.error?.code === 'FILE_CONFLICT') {
      setSandboxConflict(true)
      setNotice({ ok: false, text: res.error.message })
    } else {
      setNotice({ ok: false, text: errText(res, '저장 실패') })
    }
  }

  async function handlePreview() {
    setNotice(null)
    setDiff(null)
    const res = await postWorkspaceFilePreview(target, saveContent)
    if (res?.success) setDiff({ ...res.data, content: saveContent })
    else setNotice({ ok: false, text: errText(res, '미리보기 실패') })
  }

  async function handleApprove() {
    if (!diff) return
    const res = diff.exists
      ? await postWorkspaceFileWrite(diff.path, diff.content, diff.old_sha256)
      : await postWorkspaceFileCreate(diff.path, diff.content)
    if (res?.success) {
      setNotice({ ok: true, text: `저장(${diff.exists ? '백업됨' : '신규'}): ${res.data.path}` })
      setDiff(null)
    } else {
      setNotice({ ok: false, text: `실패: ${errText(res, '요청 실패')}` })
    }
  }

  const off = !isAdmin
  const diffValid = diff && diff.path === target.trim().replace(/\\/g, '/') && diff.content === saveContent

  return (
    <div className="page">
      <div className="page__header">
        <h1>💬 AI Workspace</h1>
      </div>

      <div className="status-card">
        <div className="form-row">
          <label className="form-label" htmlFor="ws-role">역할 / 모델</label>
          <select id="ws-role" className="form-select" value={role} disabled={off} onChange={(e) => setRole(e.target.value)}>
            {roles.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
        </div>

        <details>
          <summary>📎 컨텍스트 첨부 (선택)</summary>
          <div className="form-row">
            <label className="form-label" htmlFor="ws-file">프로젝트 파일(읽기)</label>
            <select id="ws-file" className="form-select" value={attachFile} disabled={off} onChange={(e) => setAttachFile(e.target.value)}>
              <option value="">(없음)</option>
              {files.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div className="form-row">
            <label className="form-label" htmlFor="ws-repo">Repository/시트 데이터</label>
            <select id="ws-repo" className="form-select" value={attachRepo} disabled={off} onChange={(e) => setAttachRepo(e.target.value)}>
              <option value="">(없음)</option>
              {REPO_OPTIONS.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <label className="form-label">
            <input type="checkbox" checked={attachStruct} disabled={off} onChange={(e) => setAttachStruct(e.target.checked)} /> 프로젝트 구조 요약
          </label>
        </details>

        <div className="chat-log" data-testid="workspace-chat">
          {messages.map((m, i) => (
            <div key={i} className={`chat-msg chat-msg--${m.role}`} data-role={m.role}>
              <strong>{m.role === 'user' ? '🙋' : '🤖'}</strong>{' '}
              <span className={m.error ? 'status-card__error' : undefined} style={{ whiteSpace: 'pre-wrap' }}>{m.content}</span>
              {m.meta && <p className="status-card__hint">{m.meta}</p>}
            </div>
          ))}
          {sending && <p className="status-card__hint">생각 중...</p>}
        </div>

        <form onSubmit={(e) => { e.preventDefault(); send() }}>
          <div className="form-row">
            <input aria-label="메시지 입력" className="form-search" value={input} disabled={off || sending}
                   placeholder="메시지 입력 (예: 퇴직금 계산기 HTML 만들어줘 / main.py 구조 분석해줘)"
                   onChange={(e) => setInput(e.target.value)} />
            <button type="submit" className="refresh-btn" disabled={off || sending || !input.trim() || !role}>
              {sending ? '전송 중...' : '전송'}
            </button>
          </div>
        </form>
      </div>

      <details className="status-card">
        <summary>💾 코드/파일 저장 도구</summary>
        <p className="status-card__hint">기본은 샌드박스(data/workspace/)에 저장. 프로젝트 파일 저장은 미리보기·승인 후에만(원본 자동 백업).</p>
        <div className="form-row">
          <label className="form-label" htmlFor="ws-save-name">파일명</label>
          <input id="ws-save-name" className="form-search" value={saveName} disabled={off}
                 onChange={(e) => { setSaveName(e.target.value); setSandboxConflict(false) }} />
        </div>
        <div className="form-row">
          <label className="form-label" htmlFor="ws-save-content">내용</label>
          <textarea id="ws-save-content" className="form-search" rows={8} value={saveContent} disabled={off}
                    onChange={(e) => { setSaveContent(e.target.value); setSandboxConflict(false) }} />
        </div>
        <div className="form-actions">
          <button type="button" className="refresh-btn" disabled={off} onClick={() => handleSandbox(false)}>샌드박스 저장</button>
          {sandboxConflict && (
            <button type="button" className="refresh-btn" disabled={off} onClick={() => handleSandbox(true)}>덮어쓰기 확인 후 저장</button>
          )}
        </div>

        <p className="status-card__hint">⚠️ 고급: 프로젝트 파일 저장 (미리보기 → 승인, 원본 자동 백업)</p>
        <div className="form-row">
          <label className="form-label" htmlFor="ws-tgt">대상 경로 (예: data/workspace/x.py)</label>
          <input id="ws-tgt" className="form-search" value={target} disabled={off} onChange={(e) => setTarget(e.target.value)} />
          <button type="button" className="refresh-btn" disabled={off || !target.trim() || !saveContent.trim()} onClick={handlePreview}>
            🔍 변경 미리보기
          </button>
        </div>
        {diffValid && (
          <div data-testid="workspace-diff">
            <p>{diff.exists ? '✏️ 덮어쓰기' : '🆕 신규 생성'} — 기존 {diff.old_len}자 → 새 {diff.new_len}자</p>
            {diff.exists && (
              <details>
                <summary>기존 내용 보기</summary>
                <pre>{diff.old}</pre>
              </details>
            )}
            <div className="form-actions">
              <button type="button" className="refresh-btn" disabled={off} onClick={handleApprove}>✅ 승인 후 저장</button>
              <button type="button" className="refresh-btn" onClick={() => setDiff(null)}>취소</button>
            </div>
          </div>
        )}
        {notice && <p className={notice.ok ? 'status-card__success' : 'status-card__error'}>{notice.text}</p>}
      </details>

      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={() => setMessages([])}>🗑 대화 초기화</button>
      </div>
    </div>
  )
}
