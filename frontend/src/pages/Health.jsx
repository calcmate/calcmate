import { useCallback, useEffect, useState } from 'react'
import { getCurrentUser, getExternalHealth, getHealthDetails, runExternalHealthCheck } from '../api/client.js'

// /health — 로컬 application/data 상태만 표시(STEP 18-M).
// 외부 서비스(WordPress/GitHub/Cloudflare/Sheets 등) 상태는 여기서 다루지 않는다.
const SCHEDULER_LABELS = { blog: 'Blog', calculator: 'Calculator', content_sync: 'Content Sync' }
const DATA_LABELS = {
  database: 'Database',
  config: 'Config',
  registry: 'Registry',
  labor_af: 'Labor AF',
  pipeline_log: 'Pipeline Log',
}

// STEP S3: 실질 헬스체크(실제 외부 서비스 호출) 표시 라벨 — Streamlit
// dashboard.py의 labels dict와 동일한 항목/이름을 그대로 따른다.
const EXTERNAL_LABELS = {
  openai: 'OpenAI',
  claude: 'Claude',
  gemini: 'Gemini',
  google_sheet: 'Sheets',
  google_drive: 'Drive',
  wordpress: 'WordPress',
  service_account: 'Service Account',
}

function Mark({ ok }) {
  return <span aria-hidden="true">{ok ? '✓' : '✗'}</span>
}

function ExternalHealthCard() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [state, setState] = useState(null) // getExternalHealth/runExternalHealthCheck 응답 그대로
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)

  const loadCache = useCallback(() => {
    setLoading(true)
    getExternalHealth().then((res) => {
      setState(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
    loadCache()
  }, [loadCache])

  const handleRun = () => {
    setRunning(true)
    runExternalHealthCheck().then((res) => {
      setState(res)
      setRunning(false)
    })
  }

  const failed = !loading && !state?.success
  const data = state?.data
  const items = data?.checks
    ? Object.entries(data.checks).map(([key, v]) => [EXTERNAL_LABELS[key] || key, v])
    : []

  return (
    <div className="status-card">
      <h3 className="status-card__title">External Services(실질 헬스체크)</h3>
      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || running} onClick={handleRun}>
          {running ? '검사 중...' : '🔄 다시 검사'}
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패{state?.error?.message ? `: ${state.error.message}` : ''}</p>}

      {!loading && !failed && data && !data.available && data.error && (
        <p className="status-card__error">⚠ 헬스체크 실행 실패: {data.error}</p>
      )}
      {!loading && !failed && data && !data.available && !data.error && (
        <p className="status-card__hint">검사 기록이 없습니다. 위 버튼으로 실행하세요.</p>
      )}

      {!loading && !failed && data?.available && (
        <>
          <p className="status-card__hint">
            전체 상태: {data.critical_passed ? '🟢 PASS' : '🔴 FAIL'} · 마지막 검사: {data.timestamp || '-'}
          </p>
          <ul className="health-list">
            {items.map(([label, v]) => {
              const ok = v?.status === 'OK'
              return (
                <li key={label} style={{ flexWrap: 'wrap' }}>
                  <Mark ok={ok} /> {label} — {v?.status}({v?.level})
                  {!ok && v?.error && (
                    <div
                      className="status-card__error"
                      style={{ flexBasis: '100%', minWidth: 0, width: '100%', overflowWrap: 'break-word' }}
                    >
                      {String(v.error).slice(0, 200)}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}

export default function Health() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getHealthDetails().then((res) => {
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
    <div className="page">
      <div className="page__header">
        <h1>System Health</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && data && (
        <div className="card-grid">
          <div className="status-card">
            <h3 className="status-card__title">Application</h3>
            <ul className="health-list">
              <li>
                <Mark ok={data.application?.fastapi === 'healthy'} /> FastAPI —{' '}
                {data.application?.fastapi === 'healthy' ? 'Healthy' : 'Unhealthy'}
              </li>
              <li>
                <Mark ok /> React — Healthy
              </li>
            </ul>
          </div>

          <div className="status-card">
            <h3 className="status-card__title">Schedulers</h3>
            <ul className="health-list">
              {Object.entries(SCHEDULER_LABELS).map(([key, label]) => {
                const s = data.schedulers?.[key]
                return (
                  <li key={key}>
                    <Mark ok={Boolean(s?.enabled)} /> {label} — {s?.enabled ? 'Enabled' : 'Disabled'} /{' '}
                    {s?.running ? 'Running' : 'Stopped'}
                  </li>
                )
              })}
            </ul>
          </div>

          <div className="status-card">
            <h3 className="status-card__title">Data</h3>
            <ul className="health-list">
              {Object.entries(DATA_LABELS).map(([key, label]) => (
                <li key={key}>
                  <Mark ok={Boolean(data.data?.[key])} /> {label} —{' '}
                  {data.data?.[key] ? '정상' : '파일 없음'}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="card-grid">
        <ExternalHealthCard />
      </div>
    </div>
  )
}
