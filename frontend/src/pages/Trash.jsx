import { useCallback, useEffect, useState } from 'react'
import { getTrashArticles, getCurrentUser, postTrashRestore } from '../api/client.js'

// /trash — 조회는 누구나, Restore는 admin만(STEP 18-R). Permanent Delete는 만들지 않는다.

function RestoreRow({ article, isAdmin, onDone }) {
  const [open, setOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [running, setRunning] = useState(false)
  const [message, setMessage] = useState(null)

  async function handleRestore() {
    setRunning(true)
    setMessage(null)
    const res = await postTrashRestore(article.id, confirmText)
    setRunning(false)
    if (res.success) {
      setMessage('복원되었습니다.')
      setOpen(false)
      onDone()
    } else {
      setMessage(`⚠ ${res.error?.message || '복원 실패'}`)
    }
  }

  if (!open) {
    return (
      <button type="button" className="refresh-btn" disabled={!isAdmin} onClick={() => setOpen(true)}>
        복원
      </button>
    )
  }

  return (
    <div className="write-panel">
      <p className="status-card__hint">
        복원하려면 <strong>RESTORE</strong>를 입력하세요.
      </p>
      <input
        className="form-search"
        value={confirmText}
        onChange={(e) => setConfirmText(e.target.value)}
        aria-label={`restore-confirm-${article.id}`}
      />
      <div className="form-actions">
        <button
          type="button"
          className="refresh-btn"
          disabled={!isAdmin || running || confirmText !== 'RESTORE'}
          onClick={handleRestore}
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

export default function Trash() {
  const [result, setResult] = useState(null)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([getTrashArticles(), getCurrentUser()]).then(([res, u]) => {
      setResult(res)
      setUser(u)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const failed = !loading && !result?.success
  const articles = result?.data?.articles || []
  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  return (
    <div className="page">
      <div className="page__header">
        <h1>Trash</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다 — 복원이 가능합니다.'
          : '현재 조회 전용입니다. 복원은 admin 권한이 필요합니다.'}
      </p>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && (
        <div className="status-card article-panel">
          <h3 className="status-card__title">휴지통 Article: {result.data.total}</h3>
          {articles.length ? (
            <table className="article-table">
              <thead>
                <tr>
                  <th>제목</th>
                  <th>상태</th>
                  <th>날짜</th>
                  <th>관리</th>
                </tr>
              </thead>
              <tbody>
                {articles.map((a) => (
                  <tr key={a.id}>
                    <td>{a.title || '(제목없음)'}</td>
                    <td>{a.status}</td>
                    <td>{a.published_at || '-'}</td>
                    <td>
                      <RestoreRow article={a} isAdmin={isAdmin} onDone={load} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="status-card__hint">휴지통이 비어 있습니다.</p>
          )}
        </div>
      )}
    </div>
  )
}
