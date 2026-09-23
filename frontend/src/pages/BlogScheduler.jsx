import { useCallback, useEffect, useState } from 'react'
import BlogSchedulerPanel from '../components/BlogSchedulerPanel.jsx'
import { getContentSyncStatus } from '../api/client.js'

// /blog-scheduler — 블로그 스케줄 통합 화면
// 반복 발행(스케줄 ON/OFF, 요일별 개수/시간, Draft/배포) + 1회 생성(Draft/배포) + 진행 상황
export default function BlogScheduler() {
  const [sync, setSync] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getContentSyncStatus().then((s) => {
      setSync(s)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="page">
      <div className="page__header">
        <h1>블로그 스케줄</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>
      <div className="card-grid">
        <BlogSchedulerPanel />
        <div className="status-card">
          <h3 className="status-card__title">Content Sync</h3>
          <p className="status-card__hint">WordPress 발행 상태를 로컬 DB와 동기화합니다.</p>
          <div className="form-actions" style={{ marginTop: '12px' }}>
            <button
              type="button"
              className="refresh-btn"
              onClick={() => {
                import('../api/client.js').then(({ postContentSyncRunOnce }) =>
                  postContentSyncRunOnce('recent').then(() => load())
                )
              }}
              disabled={loading}
            >
              동기화 실행
            </button>
          </div>
          {loading && <p className="status-card__hint">상태 확인 중...</p>}
        </div>
      </div>
    </div>
  )
}
