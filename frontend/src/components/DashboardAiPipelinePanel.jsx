import { useCallback, useEffect, useState } from 'react'
import { getDashboardAiPipeline } from '../api/client.js'

// 📊 AI Pipeline Monitor — STEP P2-11: dashboard.py "📊 AI Pipeline" 탭
// (dashboard.py:2875-2901)과 동일한 표시 의미를 재현한다. stages/cost_today/
// tokens_today/model_costs/last_lines/finished/has_error 전부 서버
// (dashboard_status_service.get_ai_pipeline_status() → 기존 log_service.
// get_pipeline_status()/modules.pipeline_status.get_pipeline_state())가
// 계산한 값을 그대로 받는다 — React는 재계산하지 않는다("실행 상태" 텍스트
// 파생만 원본과 동일한 분기로 재현: has_error→"🔴 오류", finished→"✅ 완료/대기",
// 그 외→"🔵 진행중" — 이것도 원본 dashboard.py:2894의 조건문을 그대로 옮긴
// 것이지 새 계산이 아니다).
const STATUS_ICON = { pending: '🟡', running: '🔵', completed: '🟢', error: '🔴' }

export default function DashboardAiPipelinePanel() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getDashboardAiPipeline().then((res) => {
      setResult(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const failed = !loading && !result?.success
  const d = result?.data
  const stages = d?.stages || []
  const modelCosts = d?.model_costs || {}
  const hasModelCosts = Object.keys(modelCosts).length > 0
  const runStatusText = d
    ? (d.has_error ? '🔴 오류' : d.finished ? '✅ 완료/대기' : '🔵 진행중')
    : ''

  return (
    <div className="status-card" style={{ gridColumn: '1 / -1' }}>
      <h3 className="status-card__title">📊 AI Pipeline Monitor</h3>
      <p className="status-card__hint">pipeline.log 기반 단계 상태(비침습적). 파이프라인 실행 중 자동 반영.</p>
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
            {stages.map((s) => (
              <div className="status-card" key={s.name}>
                <p className="status-card__title">{STATUS_ICON[s.status] || '⬜'}</p>
                <p className="status-card__title">{s.name}</p>
                <p className="status-card__hint">모델: {s.model}</p>
                <p className="status-card__hint">상태: {s.status}</p>
              </div>
            ))}
          </div>

          <dl className="kv-list">
            <div className="kv-list__row">
              <dt>오늘 비용</dt>
              <dd>${Number(d.cost_today).toFixed(4)}</dd>
            </div>
            <div className="kv-list__row">
              <dt>오늘 토큰</dt>
              <dd>{Number(d.tokens_today).toLocaleString()}</dd>
            </div>
            <div className="kv-list__row">
              <dt>실행 상태</dt>
              <dd>{runStatusText}</dd>
            </div>
          </dl>

          {hasModelCosts && (
            <>
              <h4 className="status-card__title">오늘 모델별 비용</h4>
              <div style={{ overflowX: 'auto', minWidth: 0 }}>
                <table className="settings-table">
                  <thead>
                    <tr><th>모델</th><th>비용($)</th></tr>
                  </thead>
                  <tbody>
                    {Object.entries(modelCosts).map(([model, cost]) => (
                      <tr key={model}>
                        <td style={{ overflowWrap: 'anywhere' }}>{model}</td>
                        <td>{cost}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <h4 className="status-card__title">최근 로그</h4>
          {d.last_lines && d.last_lines.length > 0
            ? <pre className="content-preview log-live">{d.last_lines.join('\n')}</pre>
            : <p className="status-card__hint">(로그 없음)</p>}
        </>
      )}
    </div>
  )
}
