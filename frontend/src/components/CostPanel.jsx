import { useCallback, useEffect, useState } from 'react'
import { getCosts, getCurrentUser, postCostRemove, postCostResume, postCostRetry } from '../api/client.js'

function fmtUsd(n) {
  return typeof n === 'number' ? `$${n.toFixed(4)}` : '데이터 없음'
}

// 💰 비용 모니터 — STEP 18-G/18-Z: 조회. STEP S4: Provider/Model breakdown.
// STEP S5: Cost Manager 수동 재개 / Retry Queue 수동 재시도.
// STEP S6: Retry Queue 수동 제거("🗑 제거").
export default function CostPanel() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isAdmin, setIsAdmin] = useState(false)
  const [resuming, setResuming] = useState(false)
  const [resumeMsg, setResumeMsg] = useState(null)
  const [retryingIds, setRetryingIds] = useState(() => new Set())
  const [retryMsgs, setRetryMsgs] = useState({})
  const [retryBanner, setRetryBanner] = useState(null)
  const [removingIds, setRemovingIds] = useState(() => new Set())
  const [removeMsgs, setRemoveMsgs] = useState({})
  const [removeBanner, setRemoveBanner] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    getCosts().then((res) => {
      setResult(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
  }, [load])

  const handleResume = () => {
    if (resuming) return
    setResuming(true)
    setResumeMsg(null)
    postCostResume().then((res) => {
      setResuming(false)
      if (res?.success) {
        setResumeMsg(res.data)
        if (res.data?.ok) load()
      } else {
        setResumeMsg({ ok: false, message: res?.error?.message || '재개 요청 실패' })
      }
    })
  }

  const handleRetry = (id) => {
    if (retryingIds.has(id)) return
    setRetryingIds((prev) => new Set(prev).add(id))
    setRetryMsgs((prev) => ({ ...prev, [id]: null }))
    postCostRetry(id).then((res) => {
      setRetryingIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      const data = res?.success ? res.data : { ok: false, message: res?.error?.message || '재시도 요청 실패' }
      if (data.ok) {
        // 성공 시 Queue에서 항목이 제거되어 재조회 후 해당 행이 사라지므로,
        // item별 메시지가 아니라 섹션 상단의 일반 배너로 결과를 보여준다.
        setRetryBanner(data)
        load()
      } else {
        setRetryMsgs((prev) => ({ ...prev, [id]: data }))
      }
    })
  }

  const handleRemove = (id) => {
    if (removingIds.has(id) || retryingIds.has(id)) return
    setRemovingIds((prev) => new Set(prev).add(id))
    setRemoveMsgs((prev) => ({ ...prev, [id]: null }))
    postCostRemove(id).then((res) => {
      setRemovingIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
      const data = res?.success ? res.data : { ok: false, message: res?.error?.message || '제거 요청 실패' }
      if (data.ok) {
        // 제거 성공 시 해당 item이 목록에서 사라지므로(S5와 동일한 이유),
        // item별 메시지가 아니라 섹션 상단의 일반 배너로 결과를 보여준다.
        setRemoveBanner(data)
        load()
      } else {
        setRemoveMsgs((prev) => ({ ...prev, [id]: data }))
      }
    })
  }

  const failed = !loading && !result?.success
  const d = result?.data

  return (
    <div className="status-card">
      <h3 className="status-card__title">💰 비용 모니터</h3>
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && d && (
        <>
          <p className="panel-section-title">오늘</p>
          <dl className="kv-list">
            <div className="kv-list__row"><dt>AI 비용</dt><dd>{fmtUsd(d.today.used)} / 한도 {fmtUsd(d.today.limit)}</dd></div>
            <div className="kv-list__row"><dt>토큰</dt><dd>{d.today.tokens?.toLocaleString?.() ?? '데이터 없음'}</dd></div>
          </dl>

          <p className="panel-section-title">이번 달</p>
          <dl className="kv-list">
            <div className="kv-list__row"><dt>AI 비용</dt><dd>{fmtUsd(d.month.used)} / 한도 {fmtUsd(d.month.limit)}</dd></div>
            <div className="kv-list__row"><dt>누적(전체월)</dt><dd>{fmtUsd(d.total_cost)}</dd></div>
          </dl>

          <p className="panel-section-title">Provider별(이번 달)</p>
          {d.by_provider_month && Object.keys(d.by_provider_month).length > 0 ? (
            <dl className="kv-list">
              {Object.entries(d.by_provider_month).map(([provider, cost]) => (
                <div className="kv-list__row" key={provider}><dt>{provider}</dt><dd>{fmtUsd(cost)}</dd></div>
              ))}
            </dl>
          ) : (
            <p className="status-card__hint">이번달 집계 없음</p>
          )}

          <p className="panel-section-title">모델별(이번 달)</p>
          {d.by_model_month && Object.keys(d.by_model_month).length > 0 ? (
            <dl className="kv-list">
              {Object.entries(d.by_model_month)
                .sort((a, b) => b[1] - a[1])
                .map(([model, cost]) => (
                  <div className="kv-list__row" key={model}><dt>{model}</dt><dd>{fmtUsd(cost)}</dd></div>
                ))}
            </dl>
          ) : (
            <p className="status-card__hint">이번달 집계 없음</p>
          )}
          <p className="status-card__hint">※ 비용은 모델별 입력/출력 단가표 기반 추정치입니다.</p>

          <p className="panel-section-title">🛡️ Cost Manager</p>
          <dl className="kv-list">
            <div className="kv-list__row"><dt>일 예산 사용률</dt><dd>{d.cost_manager?.pct?.toFixed?.(0) ?? '—'}%</dd></div>
            <div className="kv-list__row"><dt>상태</dt><dd>{d.cost_manager?.paused ? '⛔ 일시정지' : '🟢 정상'}</dd></div>
          </dl>
          {d.cost_manager?.paused && (
            <>
              <p className="status-card__error">일 예산 한도 도달로 자동 일시정지됨(익일 자동 재개).</p>
              <div className="form-actions">
                <button
                  type="button"
                  className="refresh-btn"
                  disabled={!isAdmin || resuming}
                  onClick={handleResume}
                >
                  {resuming ? '재개 중...' : '▶ 지금 수동 재개'}
                </button>
              </div>
            </>
          )}
          {resumeMsg && (
            // 성공 시 재조회로 paused가 false가 되어 위 블록이 사라지므로,
            // 결과 메시지는 paused 상태와 무관하게 항상 표시한다.
            <p className={resumeMsg.ok ? 'status-card__success' : 'status-card__error'}>
              {resumeMsg.ok ? '✅' : '⚠'} {resumeMsg.message}
            </p>
          )}

          <p className="panel-section-title">Retry Queue</p>
          <p className="status-card__hint">대기 {d.retry_queue.pending_count}건</p>
          {retryBanner && (
            <p className={retryBanner.ok ? 'status-card__success' : 'status-card__error'}>
              {retryBanner.ok ? '✅' : '⚠'} {retryBanner.message}
            </p>
          )}
          {removeBanner && (
            <p className={removeBanner.ok ? 'status-card__success' : 'status-card__error'}>
              {removeBanner.ok ? '✅' : '⚠'} {removeBanner.message}
            </p>
          )}
          {d.retry_queue.items.length > 0 && (
            <ul className="log-list">
              {d.retry_queue.items.map((it) => {
                const isRetrying = retryingIds.has(it.id)
                const isRemoving = removingIds.has(it.id)
                const busy = isRetrying || isRemoving
                const msg = retryMsgs[it.id] || removeMsgs[it.id]
                return (
                  <li key={it.id} className="log-list__item">
                    <span className="log-list__time">{it.created_at?.slice(0, 16) || '—'}</span>
                    <span className="log-list__msg">{it.title || '(제목없음)'} · {it.error}</span>
                    <div className="form-actions">
                      <button
                        type="button"
                        className="refresh-btn"
                        disabled={!isAdmin || busy}
                        onClick={() => handleRetry(it.id)}
                      >
                        {isRetrying ? '재시도 중...' : '🔁 재발행'}
                      </button>
                      <button
                        type="button"
                        className="refresh-btn"
                        disabled={!isAdmin || busy}
                        onClick={() => handleRemove(it.id)}
                      >
                        {isRemoving ? '제거 중...' : '🗑 제거'}
                      </button>
                    </div>
                    {msg && (
                      <p
                        className="status-card__error"
                        style={{ flexBasis: '100%', minWidth: 0, width: '100%', overflowWrap: 'break-word' }}
                      >
                        ⚠ {msg.message}
                      </p>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
