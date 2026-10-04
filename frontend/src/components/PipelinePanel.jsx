import { useCallback, useEffect, useState } from 'react'
import { getPipelineStatus } from '../api/client.js'

const STATUS_LABEL = { completed: '완료', running: '진행중', error: '오류', pending: '대기' }

// Pipeline 상태 — 조회 전용. 실행 버튼은 만들지 않는다(STEP 18-G §13).
export default function PipelinePanel() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getPipelineStatus().then((res) => {
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
    <div className="status-card">
      <h3 className="status-card__title">Pipeline 상태</h3>
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && d && (
        <>
          <dl className="kv-list">
            <div className="kv-list__row">
              <dt>상태</dt>
              <dd><span className={`badge ${d.has_error ? 'badge--hold' : 'badge--on'}`}>{d.finished ? '완료' : d.has_error ? '오류' : '진행중/대기'}</span></dd>
            </div>
          </dl>
          {(!d.stages || d.stages.length === 0) && (
            <p className="status-card__hint">최근 실행 데이터가 없습니다.</p>
          )}
          {d.stages && d.stages.length > 0 && (
            <ul className="log-list">
              {d.stages.map((s, i) => (
                <li key={i} className="log-list__item">
                  <span className="log-list__target">{s.name}</span>
                  <span className="log-list__msg">{STATUS_LABEL[s.status] || s.status} · {s.model}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
