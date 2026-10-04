import { useEffect, useState } from 'react'
import { getCurrentUser, postContentSyncRunOnce } from '../api/client.js'

// 🔄 Content Sync 수동 실행 — STEP S10: dashboard.py "🔄 Sync Now" 버튼
// (dashboard.py:899-930)과 동일한 실행 의미를 재현한다. modules.content_sync.
// run_sync_once()를 그대로 호출하며, 새 동기화 규칙을 만들지 않는다.
const FLAGS_SHOWN = ['WP_DELETED', 'URL_CHANGED', 'ORPHAN_WP', 'ORPHAN_SHEET']

function countFlags(anomalies) {
  const counts = {}
  for (const a of anomalies || []) {
    counts[a.flag] = (counts[a.flag] || 0) + 1
  }
  return counts
}

export default function ContentSyncManualPanel() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [mode, setMode] = useState('recent')
  const [running, setRunning] = useState(false)
  const [outcome, setOutcome] = useState(null) // {kind: 'success'|'not_run'|'busy'|'error', ...}

  useEffect(() => {
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
  }, [])

  const handleSync = () => {
    if (running) return
    setRunning(true)
    setOutcome(null)
    postContentSyncRunOnce(mode).then((res) => {
      setRunning(false)
      if (res?.success) {
        const data = res.data
        if (data?.ok) {
          setOutcome({ kind: 'success', data })
        } else {
          setOutcome({ kind: 'not_run', reason: data?.reason || '?' })
        }
      } else if (res?.error?.code === 'LOCK_CONFLICT') {
        setOutcome({ kind: 'busy', message: res.error.message })
      } else {
        setOutcome({ kind: 'error', message: res?.error?.message || '동기화 요청 실패' })
      }
    })
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">🔄 Content Sync 수동 실행</h3>
      <p className="status-card__hint">
        발행글의 WP 상태를 조회해 시트 sync_flag 갱신(WP_DELETED/URL_CHANGED/ORPHAN). 매일 03:00 자동 실행 + 여기서 즉시 수동 실행.
      </p>

      <fieldset className="form-actions" style={{ border: 'none', padding: 0, margin: 0 }}>
        <label>
          <input
            type="radio"
            name="content-sync-mode"
            value="recent"
            checked={mode === 'recent'}
            disabled={running}
            onChange={() => setMode('recent')}
          />
          {' '}recent(최근 30일)
        </label>
        {' '}
        <label>
          <input
            type="radio"
            name="content-sync-mode"
            value="full"
            checked={mode === 'full'}
            disabled={running}
            onChange={() => setMode('full')}
          />
          {' '}full(전체 스캔)
        </label>
      </fieldset>

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || running} onClick={handleSync}>
          {running ? '동기화 중...' : '🔄 Sync Now'}
        </button>
      </div>

      {outcome?.kind === 'busy' && (
        <p className="status-card__error">⚠ {outcome.message}</p>
      )}
      {outcome?.kind === 'not_run' && (
        <p className="status-card__error">⚠ 동기화 미실행: {outcome.reason} (WordPress 미구성 등)</p>
      )}
      {outcome?.kind === 'error' && (
        <p className="status-card__error">⚠ {outcome.message}</p>
      )}
      {outcome?.kind === 'success' && (
        <>
          <p className="status-card__success">
            ✅ 동기화 완료 · 검사 {outcome.data.checked}건 / 변경 {outcome.data.changed}건
          </p>
          {(() => {
            const counts = countFlags(outcome.data.anomalies)
            return (
              <p className="status-card__hint" style={{ overflowWrap: 'break-word' }}>
                이상: {FLAGS_SHOWN.map((f) => `${f} ${counts[f] || 0}`).join(' · ')}
              </p>
            )
          })()}
          {(outcome.data.anomalies || []).length > 0 && (
            <ul className="log-list">
              {outcome.data.anomalies.slice(0, 10).map((a, i) => (
                <li key={i} className="log-list__item" style={{ overflowWrap: 'break-word' }}>
                  - {a.flag} · {a.name || ''} (post_id={a.post_id || '-'})
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
