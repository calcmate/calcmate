import { useCallback, useEffect, useState } from 'react'
import {
  getCurrentUser,
  getAssistantModels,
  postAssistantChat,
  postAssistantFilesList,
  postAssistantFileRead,
  postAssistantFilePreview,
  postAssistantFileWrite,
  postAssistantFileCreate,
  getAssistantMemory,
  postAssistantMemory,
  getAssistantTasks,
  postAssistantTask,
  patchAssistantTask,
} from '../api/client.js'

// /assistant — CALCMATE-STREAMLIT-REMAINING-MIGRATION-AI-ASSISTANT-02: dashboard.py
// "🤖 AI Assistant — 운영비서"(L2892-2998) 이관. 대화(asst_msgs)·모델(asst_model)은 이 화면의
// React state로만 둔다(저장하지 않음 — 새로고침 시 사라지는 원본 session_state와 동일).
// 파일 쓰기는 미리보기 → 승인 → 서버 재검증(현재 파일 sha 대조) 순서로만 저장된다.
const FALLBACK_QUICK = ['현재 프로젝트 분석해', 'App Factory 분석해', '문제점 찾아', '개선안 제안해']
const MEMORY_KINDS = ['rules', 'todo', 'dev_log']

function errText(res, fallback) {
  if (res?.error?.message) return res.error.message
  if (res?.detail) return typeof res.detail === 'string' ? res.detail : '요청이 거부되었습니다.'
  return fallback
}

export default function AiAssistant() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [models, setModels] = useState([])
  const [model, setModel] = useState('')
  const [quick, setQuick] = useState(FALLBACK_QUICK)
  const [messages, setMessages] = useState([])           // asst_msgs
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)

  const [fpath, setFpath] = useState('data/workspace/example.txt')   // asst_path
  const [fcontent, setFcontent] = useState('')                       // asst_content
  const [diff, setDiff] = useState(null)                             // asst_diff
  const [fileMsg, setFileMsg] = useState(null)

  const [dir, setDir] = useState('.')                                // asst_ls
  const [listing, setListing] = useState(null)
  const [readPath, setReadPath] = useState('modules/app_factory.py') // asst_rf
  const [readResult, setReadResult] = useState(null)

  const [memory, setMemory] = useState(null)
  const [memKind, setMemKind] = useState('rules')                    // asst_mk
  const [memText, setMemText] = useState('')                         // asst_mt
  const [tasks, setTasks] = useState([])
  const [statuses, setStatuses] = useState(['Pending', 'Running', 'Completed', 'Failed'])
  const [taskTitle, setTaskTitle] = useState('')                     // asst_tt
  const [sideMsg, setSideMsg] = useState(null)

  const loadMemory = useCallback(() => getAssistantMemory().then((r) => { if (r?.success) setMemory(r.data) }), [])
  const loadTasks = useCallback(() => getAssistantTasks().then((r) => {
    if (r?.success) { setTasks(r.data.tasks || []); setStatuses(r.data.statuses || statuses) }
  }), []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
    getAssistantModels().then((res) => {
      if (res?.success) {
        setModels(res.data.models || [])
        setModel(res.data.default || res.data.models?.[0]?.label || '')
        if (Array.isArray(res.data.quick_questions) && res.data.quick_questions.length) setQuick(res.data.quick_questions)
      }
    })
    loadMemory()
    loadTasks()
  }, [loadMemory, loadTasks])

  async function send(text) {
    const prompt = (text || '').trim()
    if (!prompt || sending || !model) return
    const history = [...messages, { role: 'user', content: prompt }]
    setMessages(history)
    setInput('')
    setSending(true)
    const res = await postAssistantChat(model, history.map((m) => ({ role: m.role, content: m.content })))
    setSending(false)
    if (res?.success) {
      setMessages([...history, { role: 'assistant', content: res.data.reply, meta: `${res.data.model} · ${res.data.tokens} tokens` }])
    } else {
      // 원본은 실패도 assistant 메시지로 남겼다 — 원문 예외 대신 서버의 고정 문구만 남긴다.
      setMessages([...history, { role: 'assistant', content: errText(res, 'AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'), error: true }])
    }
  }

  async function handlePreview() {
    setFileMsg(null)
    setDiff(null)
    const res = await postAssistantFilePreview(fpath, fcontent)
    if (res?.success) setDiff({ ...res.data, content: fcontent })
    else setFileMsg({ ok: false, text: errText(res, '미리보기 실패') })
  }

  async function handleApply() {
    if (!diff) return
    const res = diff.exists
      ? await postAssistantFileWrite(diff.path, diff.content, diff.old_sha256)
      : await postAssistantFileCreate(diff.path, diff.content)
    if (res?.success) {
      setFileMsg({ ok: true, text: `저장 완료: ${res.data.path}` })
      setDiff(null)
    } else {
      setFileMsg({ ok: false, text: `저장 실패: ${errText(res, '요청 실패')}` })
    }
  }

  async function handleList() {
    const res = await postAssistantFilesList(dir)
    setListing(res?.success ? { items: res.data.items } : { error: errText(res, '목록 조회 실패') })
  }

  async function handleRead() {
    const res = await postAssistantFileRead(readPath)
    setReadResult(res?.success ? { content: res.data.content } : { error: errText(res, '읽기 실패') })
  }

  async function handleAddMemory() {
    if (!memText.trim()) return
    const res = await postAssistantMemory(memKind, memText)
    if (res?.success) { setMemory(res.data); setMemText('') } else setSideMsg(errText(res, '메모리 추가 실패'))
  }

  async function handleAddTask() {
    if (!taskTitle.trim()) return
    const res = await postAssistantTask(taskTitle)
    if (res?.success) { setTasks(res.data.tasks || []); setTaskTitle('') } else setSideMsg(errText(res, '태스크 추가 실패'))
  }

  async function handleTaskStatus(id, status) {
    const res = await patchAssistantTask(id, status)
    if (res?.success) setTasks(res.data.tasks || []); else setSideMsg(errText(res, '상태 변경 실패'))
  }

  // 미리보기 이후 경로/내용이 바뀌면 그 미리보기로는 승인할 수 없다(원본: diff.path == fpath일 때만 표시).
  const diffValid = diff && diff.path === fpath.trim().replace(/\\/g, '/') && diff.content === fcontent
  const off = !isAdmin

  return (
    <div className="page">
      <div className="page__header">
        <h1>🤖 AI Assistant — 운영비서</h1>
      </div>
      <p className="status-card__hint">
        채팅으로 프로젝트 분석·개선·수정. 파일 쓰기는 승인 후에만, 워크스페이스 내부 한정(삭제/시스템명령 불가 · 민감 파일 접근 불가).
      </p>

      <div className="status-card">
        <div className="form-row">
          <label className="form-label" htmlFor="asst-model">모델</label>
          <select id="asst-model" className="form-select" value={model} onChange={(e) => setModel(e.target.value)} disabled={off}>
            {models.map((m) => <option key={m.label} value={m.label}>{m.label}</option>)}
          </select>
        </div>
        <div className="form-actions">
          {quick.map((q) => (
            <button key={q} type="button" className="refresh-btn" disabled={off || sending || !model} onClick={() => send(q)}>{q}</button>
          ))}
        </div>

        <div className="chat-log" data-testid="assistant-chat">
          {messages.map((m, i) => (
            <div key={i} className={`chat-msg chat-msg--${m.role}`} data-role={m.role}>
              <strong>{m.role === 'user' ? '🙋' : '🤖'}</strong>{' '}
              <span className={m.error ? 'status-card__error' : undefined} style={{ whiteSpace: 'pre-wrap' }}>{m.content}</span>
              {m.meta && <p className="status-card__hint">{m.meta}</p>}
            </div>
          ))}
          {sending && <p className="status-card__hint">분석 중...</p>}
        </div>

        <form onSubmit={(e) => { e.preventDefault(); send(input) }}>
          <div className="form-row">
            <input aria-label="명령/질문" className="form-search" value={input} disabled={off || sending}
                   placeholder="명령/질문 (예: config 수정해, 새 계산기 추가해, 최근 오류 분석해)"
                   onChange={(e) => setInput(e.target.value)} />
            <button type="submit" className="refresh-btn" disabled={off || sending || !input.trim() || !model}>
              {sending ? '전송 중...' : '전송'}
            </button>
          </div>
        </form>
      </div>

      <details className="status-card">
        <summary>📝 파일 수정/생성 (변경 미리보기 → 승인 후 저장)</summary>
        <p className="status-card__hint">워크스페이스 내부만(민감 파일 제외). 덮어쓰기 시 원본은 서버가 자동 백업합니다.</p>
        <div className="form-row">
          <label className="form-label" htmlFor="asst-path">대상 경로</label>
          <input id="asst-path" className="form-search" value={fpath} disabled={off} onChange={(e) => setFpath(e.target.value)} />
        </div>
        <div className="form-row">
          <label className="form-label" htmlFor="asst-content">새 내용 (AI 답변에서 복사 가능)</label>
          <textarea id="asst-content" className="form-search" rows={8} value={fcontent} disabled={off}
                    onChange={(e) => setFcontent(e.target.value)} />
        </div>
        <div className="form-actions">
          <button type="button" className="refresh-btn" disabled={off || !fpath.trim()} onClick={handlePreview}>🔍 변경 미리보기</button>
        </div>
        {diffValid && (
          <div data-testid="assistant-diff">
            <p>{diff.exists ? '✏️ 덮어쓰기' : '🆕 신규 생성'} — 기존 {diff.old_len}자 → 새 {diff.new_len}자</p>
            {diff.exists && (
              <details>
                <summary>기존 내용 보기</summary>
                <pre>{diff.old}</pre>
              </details>
            )}
            <div className="form-actions">
              <button type="button" className="refresh-btn" disabled={off} onClick={handleApply}>✅ 승인 후 저장</button>
              <button type="button" className="refresh-btn" onClick={() => setDiff(null)}>취소</button>
            </div>
          </div>
        )}
        {fileMsg && <p className={fileMsg.ok ? 'status-card__success' : 'status-card__error'}>{fileMsg.text}</p>}
      </details>

      <details className="status-card">
        <summary>📂 워크스페이스 탐색/읽기</summary>
        <div className="form-row">
          <label className="form-label" htmlFor="asst-ls">디렉터리</label>
          <input id="asst-ls" className="form-search" value={dir} disabled={off} onChange={(e) => setDir(e.target.value)} />
          <button type="button" className="refresh-btn" disabled={off} onClick={handleList}>목록</button>
        </div>
        {listing?.error && <p className="status-card__error">{listing.error}</p>}
        {listing?.items && (
          <ul className="today-list" aria-label="디렉터리 목록">
            {listing.items.map((it) => <li key={it.path}>{(it.type === 'dir' ? '📁 ' : '📄 ') + it.path}</li>)}
          </ul>
        )}
        <div className="form-row">
          <label className="form-label" htmlFor="asst-rf">파일 읽기 경로</label>
          <input id="asst-rf" className="form-search" value={readPath} disabled={off} onChange={(e) => setReadPath(e.target.value)} />
          <button type="button" className="refresh-btn" disabled={off || !readPath.trim()} onClick={handleRead}>읽기</button>
        </div>
        {readResult?.error && <p className="status-card__error">{readResult.error}</p>}
        {readResult?.content !== undefined && <pre data-testid="assistant-read">{readResult.content}</pre>}
      </details>

      <details className="status-card">
        <summary>🧠 Memory (운영규칙 / TODO / 개발기록)</summary>
        <div className="form-row">
          <label className="form-label" htmlFor="asst-mk">종류</label>
          <select id="asst-mk" className="form-select" value={memKind} disabled={off} onChange={(e) => setMemKind(e.target.value)}>
            {MEMORY_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
          <label className="form-label" htmlFor="asst-mt">추가 내용</label>
          <input id="asst-mt" className="form-search" value={memText} disabled={off} onChange={(e) => setMemText(e.target.value)} />
          <button type="button" className="refresh-btn" disabled={off || !memText.trim()} onClick={handleAddMemory}>메모리 추가</button>
        </div>
        {memory && MEMORY_KINDS.map((k) => (memory[k] || []).length > 0 && (
          <div key={k} data-testid={`memory-${k}`}>
            <strong>{k}</strong> ({memory[k].length})
            <ul className="today-list">{memory[k].slice(-10).map((it, i) => <li key={i}>• {it.text}</li>)}</ul>
          </div>
        ))}
      </details>

      <details className="status-card">
        <summary>✅ Task (Lite: 상태만)</summary>
        <div className="form-row">
          <label className="form-label" htmlFor="asst-tt">새 태스크</label>
          <input id="asst-tt" className="form-search" value={taskTitle} disabled={off} onChange={(e) => setTaskTitle(e.target.value)} />
          <button type="button" className="refresh-btn" disabled={off || !taskTitle.trim()} onClick={handleAddTask}>태스크 추가</button>
        </div>
        <ul className="today-list" aria-label="태스크 목록">
          {tasks.slice(-15).map((t) => (
            <li key={t.id}>
              {t.title}{' '}
              <select aria-label={`상태 ${t.title}`} className="form-select" value={t.status} disabled={off}
                      onChange={(e) => handleTaskStatus(t.id, e.target.value)}>
                {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </li>
          ))}
        </ul>
      </details>
      {sideMsg && <p className="status-card__error">{sideMsg}</p>}

      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={() => setMessages([])}>🗑 대화 초기화</button>
      </div>
    </div>
  )
}
