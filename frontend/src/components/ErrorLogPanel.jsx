import { useCallback, useEffect, useState } from 'react'
import { getErrorLogs } from '../api/client.js'

// ⚠️ 오류 로그 — 조회 전용. 삭제/정리 기능은 만들지 않는다(STEP 18-G).
export default function ErrorLogPanel() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getErrorLogs().then((res) => {
      setResult(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const failed = !loading && !result?.success
  const opErrors = result?.data?.operation_errors || []
  const calcHolds = result?.data?.calculator_quality_holds || []

  return (
    <div className="status-card blog-panel">
      <h3 className="status-card__title">⚠ 오류 로그</h3>
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && (
        <>
          <p className="panel-section-title">운영로그 오류 ({opErrors.length})</p>
          {opErrors.length === 0 && <p className="status-card__hint">최근 오류가 없습니다.</p>}
          {opErrors.length > 0 && (
            <ul className="log-list">
              {opErrors.map((row, i) => (
                <li key={i} className="log-list__item">
                  <span className="log-list__time">{row['실행일시'] || '—'}</span>
                  <span className="log-list__target">{row['대상정책명'] || row['마스터ID'] || '—'}</span>
                  <span className="log-list__msg">{row['실패모듈'] || ''} {row['오류내용'] || row['가동결과'] || ''}</span>
                </li>
              ))}
            </ul>
          )}

          <p className="panel-section-title">계산기 품질보류 ({calcHolds.length})</p>
          {calcHolds.length === 0 && <p className="status-card__hint">품질보류 항목이 없습니다.</p>}
          {calcHolds.length > 0 && (
            <ul className="log-list">
              {calcHolds.map((row, i) => (
                <li key={i} className="log-list__item">
                  <span className="log-list__time">{row['발행일시'] || '—'}</span>
                  <span className="log-list__target">{row['최종추천제목'] || row['정책명'] || '—'}</span>
                  <span className="log-list__msg">{row['상태값'] || ''}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
