import { useCallback, useEffect, useState } from 'react'
import { getDashboardKpi } from '../api/client.js'

// STEP P2-01: dashboard.py render_kpi_cards()(운영센터 홈 5개 KPI 카드)와 동일한
// 값을 표시한다. icon/label은 순수 UI 텍스트(원본과 동일 문구)이고, value/sub는
// 전부 GET /api/dashboard/kpi(서버에서 기존 계산 함수로 산출)에서 그대로 받는다
// — React는 재계산하지 않는다.
const CARDS = [
  { key: 'system', icon: '🩺', label: '시스템' },
  { key: 'workflow', icon: '⛓️', label: 'Workflow' },
  { key: 'ai_task', icon: '🤖', label: 'AI 작업' },
  { key: 'today', icon: '📦', label: '오늘' },
  { key: 'cost', icon: '💰', label: 'AI 비용' },
]

export default function DashboardKpiPanel() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getDashboardKpi().then((res) => {
      setResult(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const failed = !loading && !result?.success
  const data = result?.data

  return (
    <div className="status-card" style={{ gridColumn: '1 / -1' }}>
      <h3 className="status-card__title">KPI 요약</h3>
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && data && (
        <div className="card-grid">
          {CARDS.map(({ key, icon, label }) => {
            const kpi = data[key] || {}
            return (
              <div className="status-card" key={key}>
                <h3 className="status-card__title">{icon} {label}</h3>
                <p className="kpi-number">{kpi.value ?? '—'}</p>
                {kpi.sub && <p className="status-card__hint">{kpi.sub}</p>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
