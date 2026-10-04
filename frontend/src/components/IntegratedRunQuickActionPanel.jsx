import { useEffect, useState } from 'react'
import { getCurrentUser, postIntegratedRunOnce } from '../api/client.js'

// ▶ 실행(통합 실행) — STEP S13: dashboard.py "▶ 실행" 버튼(dashboard.py:432-469,
// render_quick_actions()의 qa_run)과 동일한 실행 의미를 재현한다. 새 파이프라인이
// 아니라 site의 활성 platforms에 따라 Calculator 생성(S11)/Blog 파이프라인
// 실행(S12) 중 하나(또는 순차)를 서버가 고르는 dispatcher다.
//
// CURRENT-SITE-02: 홈 화면의 현재 Site(useCurrentSiteSelection)를 site prop으로 받아
// dashboard.py render_quick_actions()와 같이 "대상: {site} · Platform: …"을 표시하고,
// WordPress+Calculator가 모두 활성이면 실행 방식(순차/Calculator만/WordPress만)을
// 고르게 한 뒤 site_id와 함께 보낸다. 서버가 site를 다시 조회해 분기한다.
// site prop을 주지 않으면(단독 렌더) site_id 없이 보내며 서버 기본값을 쓴다.
const ORDERS = ['순차(Calculator→WordPress)', 'Calculator만', 'WordPress만']
const REASON_LABEL = {
  budget_daily: '일일 AI 예산 초과로 중단됨',
  budget_monthly: '월간 AI 예산 초과로 중단됨',
  budget_midrun: '처리 중 예산 초과로 중단됨',
  no_items: '수집된 항목 없음',
  no_calculators: '활성 계산기 없음(App Factory/시드로 등록 필요)',
  dry_run: 'dry-run(실행 안 함)',
  ok: '정상 완료',
  정상완료: '정상 완료',
  모든후보HOLD: '모든 후보가 품질보류(REWRITE 한도 초과)',
  후보소진: '생성할 신규 후보 없음(전부 발행됨/재도전 대상 아님)',
}

export default function IntegratedRunQuickActionPanel({ site } = {}) {
  const [isAdmin, setIsAdmin] = useState(false)
  const [running, setRunning] = useState(false)
  const [outcome, setOutcome] = useState(null) // {kind: 'success'|'busy'|'error', ...}
  const [order, setOrder] = useState(ORDERS[0])
  const siteMode = site !== undefined
  const platforms = Array.isArray(site?.platforms) ? site.platforms : []
  const hasWp = platforms.includes('WordPress')
  const hasCalc = platforms.includes('Calculator')

  useEffect(() => {
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
  }, [])

  const handleRun = () => {
    if (running) return
    setRunning(true)
    setOutcome(null)
    const req = siteMode ? postIntegratedRunOnce(hasWp && hasCalc ? order : undefined, site?.site_id) : postIntegratedRunOnce()
    req.then((res) => {
      setRunning(false)
      if (res?.success) {
        setOutcome({ kind: 'success', data: res.data })
      } else if (res?.error?.code === 'LOCK_CONFLICT') {
        setOutcome({ kind: 'busy', message: res.error.message })
      } else {
        setOutcome({ kind: 'error', message: res?.error?.message || '실행 요청 실패' })
      }
    })
  }

  const produced = typeof outcome?.data === 'object' && outcome?.data !== null ? outcome.data.produced : null

  return (
    <div className="status-card">
      <h3 className="status-card__title">▶ 실행</h3>
      <p className="status-card__hint">
        현재 site의 활성 Platform에 따라 Calculator 생성/Blog 파이프라인 중 알맞은 것을 자동 실행합니다(Platform 미설정 시 기본 Blog 파이프라인).
      </p>
      {siteMode && (
        <p className="status-card__hint" data-testid="integrated-run-target">
          대상: {site ? (site.site_name || site.site_id) : '기본(CalcMate)'}
          {platforms.length ? ` · Platform: ${platforms.join(' + ')}` : ' · Platform 미설정 → 기본 블로그 파이프라인 실행'}
        </p>
      )}
      {siteMode && hasWp && hasCalc && (
        <div className="form-row" role="radiogroup" aria-label="실행 방식">
          {ORDERS.map((o) => (
            <label key={o} className="form-label">
              <input type="radio" name="integrated-order" value={o} checked={order === o}
                     onChange={() => setOrder(o)} /> {o}
            </label>
          ))}
        </div>
      )}

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || running} onClick={handleRun}>
          {running ? '실행 중...' : '▶ 실행'}
        </button>
      </div>

      {outcome?.kind === 'busy' && (
        <p className="status-card__error">⚠ {outcome.message}</p>
      )}
      {outcome?.kind === 'error' && (
        <p className="status-card__error">⚠ 실행 실패: {outcome.message}</p>
      )}
      {outcome?.kind === 'success' && typeof outcome.data === 'string' && (
        <p className="status-card__success">✅ {outcome.data}</p>
      )}
      {outcome?.kind === 'success' && typeof outcome.data === 'object' && outcome.data !== null && (
        <p className={produced > 0 ? 'status-card__success' : 'status-card__hint'}>
          {produced > 0 ? '✅' : 'ℹ'} 실행 요청 완료 · 생산 {produced}건
          {' '}({REASON_LABEL[outcome.data.reason] || outcome.data.reason || '-'})
        </p>
      )}
    </div>
  )
}
