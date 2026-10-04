import { useCallback, useEffect, useState } from 'react'
import {
  getPublishOverview,
  getPublishArticles,
  getCurrentUser,
  postPublishEdit,
  postTrash,
} from '../api/client.js'

// /publish — 조회는 누구나, Edit/Trash는 admin만(STEP 18-R). 실제 WordPress
// 호출은 서버가 하며, 이 화면은 admin이 아니면 버튼을 비활성화해 오조작을 막는다.

function EditRow({ article, isAdmin, onDone }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState(article.title)
  const [excerpt, setExcerpt] = useState('')
  const [content, setContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(null)

  async function handleSave() {
    setSaving(true)
    setMessage(null)
    const payload = {
      title: title !== article.title ? title : undefined,
      excerpt: excerpt.trim() ? excerpt : undefined,
      content: content.trim() ? content : undefined,
    }
    const res = await postPublishEdit(article.id, payload)
    setSaving(false)
    if (res.success) {
      setMessage('수정되었습니다.')
      onDone()
    } else {
      setMessage(`⚠ ${res.error?.message || '수정 실패'}`)
    }
  }

  if (!open) {
    return (
      <button type="button" className="refresh-btn" disabled={!isAdmin} onClick={() => setOpen(true)}>
        수정
      </button>
    )
  }

  return (
    <div className="write-panel">
      <label className="form-label" htmlFor={`edit-title-${article.id}`}>
        제목
      </label>
      <input
        id={`edit-title-${article.id}`}
        className="form-search"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <label className="form-label" htmlFor={`edit-excerpt-${article.id}`}>
        요약(excerpt)
      </label>
      <input
        id={`edit-excerpt-${article.id}`}
        className="form-search"
        placeholder="비워두면 수정하지 않음"
        value={excerpt}
        onChange={(e) => setExcerpt(e.target.value)}
      />
      <label className="form-label" htmlFor={`edit-content-${article.id}`}>
        본문 교체
      </label>
      <textarea
        id={`edit-content-${article.id}`}
        className="form-search"
        placeholder="비워두면 본문은 수정하지 않음"
        rows={3}
        value={content}
        onChange={(e) => setContent(e.target.value)}
      />
      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || saving} onClick={handleSave}>
          {saving ? '저장 중...' : '저장'}
        </button>
        <button type="button" className="refresh-btn" onClick={() => setOpen(false)}>
          취소
        </button>
      </div>
      {message && <p className="status-card__hint">{message}</p>}
    </div>
  )
}

function TrashRow({ article, isAdmin, onDone }) {
  const [open, setOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [running, setRunning] = useState(false)
  const [message, setMessage] = useState(null)

  async function handleTrash() {
    setRunning(true)
    setMessage(null)
    const res = await postTrash(article.id, confirmText)
    setRunning(false)
    if (res.success) {
      setMessage('휴지통으로 이동되었습니다.')
      setOpen(false)
      onDone()
    } else {
      setMessage(`⚠ ${res.error?.message || '휴지통 이동 실패'}`)
    }
  }

  if (!open) {
    return (
      <button type="button" className="refresh-btn" disabled={!isAdmin} onClick={() => setOpen(true)}>
        휴지통 이동
      </button>
    )
  }

  return (
    <div className="write-panel">
      <p className="status-card__hint">
        휴지통으로 이동하려면 <strong>TRASH</strong>를 입력하세요.
      </p>
      <input
        className="form-search"
        value={confirmText}
        onChange={(e) => setConfirmText(e.target.value)}
        aria-label={`trash-confirm-${article.id}`}
      />
      <div className="form-actions">
        <button
          type="button"
          className="refresh-btn"
          disabled={!isAdmin || running || confirmText !== 'TRASH'}
          onClick={handleTrash}
        >
          {running ? '처리 중...' : '실행'}
        </button>
        <button type="button" className="refresh-btn" onClick={() => setOpen(false)}>
          취소
        </button>
      </div>
      {message && <p className="status-card__hint">{message}</p>}
    </div>
  )
}

export default function Publish() {
  const [overview, setOverview] = useState(null)
  const [list, setList] = useState(null)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setFailed(false)
    Promise.all([getPublishOverview(), getPublishArticles(), getCurrentUser()]).then(([o, l, u]) => {
      setOverview(o)
      setList(l)
      setUser(u)
      setFailed(!o?.success || !l?.success)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  return (
    <div className="page">
      <div className="page__header">
        <h1>Article Publish</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      <p className="status-card__hint">
        이 화면은 내부 Article/SEO 콘텐츠 파이프라인("articles" DB) 관리 화면입니다 — 실제
        공개 중인 calcmate.kr Blog 글은 <strong>Blog</strong> 메뉴에서 확인하세요.
      </p>
      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다 — 수정/휴지통 이동이 가능합니다.'
          : '현재 조회 전용입니다. 수정/휴지통 이동은 admin 권한이 필요합니다.'}
      </p>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {!loading && failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && overview && (
        <>
          <div className="card-grid">
            <div className="status-card">
              <h3 className="status-card__title">전체 Article</h3>
              <p className="kpi-number">{overview.data.total}</p>
            </div>
            {Object.entries(overview.data.by_status || {}).map(([status, count]) => (
              <div className="status-card" key={status}>
                <h3 className="status-card__title">{status}</h3>
                <p className="kpi-number">{count}</p>
              </div>
            ))}
          </div>

          <div className="status-card article-panel">
            <h3 className="status-card__title">발행 목록(발행완료 / 검수대기 / 수정됨)</h3>
            {list?.data?.articles?.length ? (
              <table className="article-table">
                <thead>
                  <tr>
                    <th>제목</th>
                    <th>상태</th>
                    <th>날짜</th>
                    <th>URL</th>
                    <th>관리</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data.articles.map((a) => (
                    <tr key={a.id}>
                      <td>{a.title || '(제목없음)'}</td>
                      <td>{a.status}</td>
                      <td>{a.published_at || '-'}</td>
                      <td>
                        {a.url ? (
                          <a href={a.url} target="_blank" rel="noreferrer">
                            링크
                          </a>
                        ) : (
                          '-'
                        )}
                      </td>
                      <td>
                        <div className="row-actions">
                          <EditRow article={a} isAdmin={isAdmin} onDone={load} />
                          <TrashRow article={a} isAdmin={isAdmin} onDone={load} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="status-card__hint">발행된 글이 없습니다.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}
