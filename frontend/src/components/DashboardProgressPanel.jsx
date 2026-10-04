import { useCallback, useEffect, useState } from 'react'
import { getDashboardProgress } from '../api/client.js'

// 📈 진행 현황 — STEP P2-02: dashboard.py render_progress()(dashboard.py:489-511)
// 와 동일한 표시 의미를 재현한다. total/completed/pct/failed/running/next/
// retry_pending 전부 서버(modules.scheduler.summarize()/modules.retry_queue.
// list_pending())가 계산한 값을 그대로 받는다 — React는 재계산하지 않는다.
export default function DashboardProgressPanel() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getDashboardProgress().then((res) => {
      setResult(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const failed = !loading && !result?.success
  const d = result?.data

  return (
    <div className="status-card" style={{ gridColumn: '1 / -1' }}>
      <h3 className="status-card__title">📈 진행 현황</h3>
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && d && (
        <>
          <p className="status-card__hint">
            오늘 일정 {d.completed}/{d.total} ({d.pct}%)
          </p>
          <progress value={d.total ? d.pct : 0} max={100} style={{ width: '100%' }} />

          <dl className="kv-list">
            <div className="kv-list__row">
              <dt>Retry 대기</dt>
              <dd>{d.retry_pending ?? '—'}</dd>
            </div>
            <div className="kv-list__row">
              <dt>실패</dt>
              <dd>{d.failed}</dd>
            </div>
            <div className="kv-list__row">
              <dt>진행중</dt>
              <dd>{d.running}</dd>
            </div>
            <div className="kv-list__row">
              <dt>다음 발행(ETA)</dt>
              <dd>{d.next || '-'}</dd>
            </div>
          </dl>
        </>
      )}
    </div>
  )
}
