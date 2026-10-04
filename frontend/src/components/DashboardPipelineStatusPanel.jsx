import { useCallback, useEffect, useState } from 'react'
import { getDashboardPipelineStatus } from '../api/client.js'

// ⛓️ Workflow — STEP P2-02: dashboard.py render_pipeline_status()(dashboard.py:
// 380-413)와 동일한 표시 의미를 재현한다. 각 단계의 status는 서버(modules.
// pipeline_status.get_pipeline_state())가 계산한 값을 그대로 받아 배지 스타일만
// 매핑한다 — React는 상태를 재계산하지 않는다.
//
// 계산기(App Factory) 단계는 원본에서도 항상 정적(live=False)이라 실제 상태를
// 절대 반영하지 않는다 — 그대로 재현하며 "고치지" 않는다.
const STATUS_BADGE = {
  completed: 'badge--on',
  running: 'badge--hold',
  error: 'badge--hold',
  pending: 'badge--off',
}
const STATUS_LABEL = {
  completed: '완료', running: '진행중', error: '오류', pending: '대기',
}

function StepRow({ steps, live }) {
  return (
    <div className="form-actions" style={{ flexWrap: 'wrap' }}>
      {steps.map((s, i) => (
        <span
          key={i}
          className={`badge ${live ? (STATUS_BADGE[s.status] || 'badge--off') : 'badge--off'}`}
          title={live ? (STATUS_LABEL[s.status] || s.status) : undefined}
        >
          {s.icon} {s.label}
        </span>
      ))}
    </div>
  )
}

export default function DashboardPipelineStatusPanel() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getDashboardPipelineStatus().then((res) => {
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
      <h3 className="status-card__title">⛓️ Workflow</h3>
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && data && (
        <>
          <p className="panel-section-title">📰 블로그 파이프라인 (현재 단계 강조)</p>
          {(data.blog || []).length === 0 && <p className="status-card__hint">No Data</p>}
          {(data.blog || []).length > 0 && <StepRow steps={data.blog} live />}

          <p className="panel-section-title">🧮 계산기 파이프라인</p>
          {(data.calculator || []).length === 0 && <p className="status-card__hint">No Data</p>}
          {(data.calculator || []).length > 0 && <StepRow steps={data.calculator} live={false} />}
        </>
      )}
    </div>
  )
}
