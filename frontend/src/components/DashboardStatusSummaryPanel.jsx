import { useCallback, useEffect, useState } from 'react'
import { getDashboardStatusSummary } from '../api/client.js'

// 📊 현황 — STEP P2-10: dashboard.py "📊 현황" 탭(dashboard.py:562-584)과
// 동일한 표시 의미를 재현한다. statuses/today_published/daily_goal/
// progress_percent 전부 서버(dashboard_status_service.get_status_summary())가
// 계산한 값을 그대로 받는다 — React는 재계산하지 않는다. P2-02의
// DashboardProgressPanel(scheduler 기반 "오늘 일정")과는 다른 데이터
// (articles 상태별 개수/오늘 발행 목표)를 보여주는 별개 패널이다.
export default function DashboardStatusSummaryPanel() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getDashboardStatusSummary().then((res) => {
      setResult(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const failed = !loading && !result?.success
  const d = result?.data
  const statuses = d?.statuses || []
  const empty = !loading && !failed && statuses.length > 0 && statuses.every((s) => s.count === 0)

  return (
    <div className="status-card" style={{ gridColumn: '1 / -1' }}>
      <h3 className="status-card__title">📊 현황</h3>
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && d && (
        <>
          <div className="card-grid">
            {statuses.map((s) => (
              <div className="status-card" key={s.status}>
                <p className="status-card__hint">{s.icon} {s.status}</p>
                <h3 className="status-card__title">{s.count}</h3>
              </div>
            ))}
          </div>
          {empty && <p className="status-card__hint">등록된 글이 없습니다.</p>}

          <p className="status-card__hint">
            오늘 발행: {d.today_published}/{d.daily_goal}
          </p>
          <progress value={d.progress_percent} max={100} style={{ width: '100%' }} />
        </>
      )}
    </div>
  )
}
