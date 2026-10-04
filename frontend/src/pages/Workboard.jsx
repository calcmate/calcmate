import { useCallback, useEffect, useState } from 'react'
import { getWorkboard } from '../api/client.js'

// 📋 작업 현황 보드 — STEP S9: dashboard.py "📋 작업 보드" 탭(칸반)을 그대로
// 이관. 읽기 전용 — 상태 변경/드래그앤드롭/카드 클릭 동작을 새로 추가하지 않는다
// (기존 Streamlit에도 없던 기능).
export default function Workboard() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getWorkboard().then((res) => {
      setResult(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const failed = !loading && !result?.success
  const columns = result?.data?.columns

  return (
    <div className="page">
      <div className="page__header">
        <h1>📋 작업 현황 보드</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>
      <p className="status-card__hint">
        마스터_DB 상태값 기준 칸반. (수집중→작성중→검수중→발행대기→발행완료 / 오류)
      </p>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && columns && (
        <div className="card-grid">
          {columns.map((col) => (
            <div className="status-card" key={col.title}>
              <h3 className="status-card__title">{col.title}</h3>
              <p className="kpi-number">{col.count}</p>
              {col.items.length > 0 ? (
                <ul className="log-list">
                  {col.items.map((it) => (
                    <li key={it.id} className="log-list__item" style={{ overflowWrap: 'break-word' }}>
                      • {it.title}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="status-card__hint">항목 없음</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
