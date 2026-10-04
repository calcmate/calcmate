import { useCallback, useEffect, useState } from 'react'
import { getRecentLogs, getErrorLogs } from '../api/client.js'

// 🕒 Recent Activity — 운영센터(/) 확장 영역(STEP 18-G §9). 조회 전용.
export default function RecentActivityPanel() {
  const [recent, setRecent] = useState(null)
  const [errors, setErrors] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([getRecentLogs(), getErrorLogs()]).then(([r, e]) => {
      setRecent(r)
      setErrors(e)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const failed = !loading && (!recent?.success || !errors?.success)
  const lines = recent?.data?.lines || []
  const errorTotal = errors?.data?.total ?? 0

  return (
    <div className="status-card blog-panel">
      <h3 className="status-card__title">🕒 Recent Activity</h3>
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && (
        <>
          <p className="status-card__hint">최근 오류 {errorTotal}건</p>
          <p className="panel-section-title">최근 실행</p>
          {lines.length === 0 && <p className="status-card__hint">No Activity</p>}
          {lines.length > 0 && <pre className="content-preview log-live">{lines.join('\n')}</pre>}
        </>
      )}
    </div>
  )
}
