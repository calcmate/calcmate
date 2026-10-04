import { useCallback, useEffect, useState } from 'react'
import { getLiveLogs } from '../api/client.js'

const LEVELS = [
  { value: 'all', label: '전체' },
  { value: 'error', label: 'ERROR만' },
  { value: 'warn_error', label: 'WARN+ERROR' },
  { value: 'info', label: 'INFO만' },
]

// 📡 실시간 로그 — WebSocket/SSE 없이 [새로고침] 버튼으로만 재조회한다(STEP 18-G §11).
export default function LiveLogPanel() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [level, setLevel] = useState('all')

  const load = useCallback((lv) => {
    setLoading(true)
    getLiveLogs(lv).then((res) => {
      setResult(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load(level)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [level])

  const failed = !loading && !result?.success
  const entries = result?.data?.entries || []
  const counts = result?.data?.counts || { error: 0, warn: 0, info: 0 }

  return (
    <div className="status-card blog-panel">
      <h3 className="status-card__title">📡 실시간 로그</h3>
      <div className="form-row">
        <label className="form-label" htmlFor="log-level">필터</label>
        <select
          id="log-level"
          className="form-select"
          value={level}
          onChange={(e) => setLevel(e.target.value)}
        >
          {LEVELS.map((l) => (
            <option key={l.value} value={l.value}>{l.label}</option>
          ))}
        </select>
        <button type="button" className="refresh-btn" onClick={() => load(level)}>
          새로고침
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && (
        <>
          <p className="status-card__hint">
            🔴 ERROR {counts.error} · 🟡 WARN {counts.warn} · 🟢 INFO {counts.info}
          </p>
          {entries.length === 0 && <p className="status-card__hint">표시할 로그가 없습니다.</p>}
          {entries.length > 0 && (
            <pre className="content-preview log-live">
              {entries.map((e) => e.line).join('\n')}
            </pre>
          )}
        </>
      )}
    </div>
  )
}
