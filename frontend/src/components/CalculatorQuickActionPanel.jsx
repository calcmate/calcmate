import { useEffect, useState } from 'react'
import { getCurrentUser, postCalculatorRunOnce } from '../api/client.js'

// 🧮 계산기 생성(Quick Action) — STEP S11: dashboard.py "🧮 계산기 생성" 버튼
// (dashboard.py:474-476, "🔧 고급 실행(수동)" expander 안)과 동일한 실행 의미를
// 재현한다. modules.calculator_pipeline.run_calculator_once(cfg, max_count=1)를
// 그대로 호출하며, 계산기 생성 파이프라인 자체는 새로 만들지 않는다.
//
// 이 버튼은 카드에 표시되는 "Calculator Scheduler"(CALC_WEBAPP_SCHEDULE, App
// Factory 계산기 앱 자동 생성 스케줄러)와는 별개의 기능이다 — 계산기 "SEO 글"을
// 활성 계산기 키워드 중에서 1건 생산한다.
const REASON_LABEL = {
  budget: '일일 AI 예산 초과로 중단됨',
  no_calculators: '활성 계산기 없음(App Factory/시드로 등록 필요)',
  정상완료: '정상 완료',
  모든후보HOLD: '모든 후보가 품질보류(REWRITE 한도 초과)',
  후보소진: '생성할 신규 후보 없음(전부 발행됨/재도전 대상 아님)',
}

export default function CalculatorQuickActionPanel() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [running, setRunning] = useState(false)
  const [outcome, setOutcome] = useState(null) // {kind: 'success'|'busy'|'error', ...}

  useEffect(() => {
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
  }, [])

  const handleRun = () => {
    if (running) return
    setRunning(true)
    setOutcome(null)
    postCalculatorRunOnce().then((res) => {
      setRunning(false)
      if (res?.success) {
        setOutcome({ kind: 'success', data: res.data })
      } else if (res?.error?.code === 'LOCK_CONFLICT') {
        setOutcome({ kind: 'busy', message: res.error.message })
      } else {
        setOutcome({ kind: 'error', message: res?.error?.message || '계산기 생성 요청 실패' })
      }
    })
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">🧮 계산기 생성</h3>
      <p className="status-card__hint">
        활성 계산기 키워드 중 1건을 골라 SEO 글을 생산합니다(App Factory 계산기 앱 생성과는 다른 기능).
      </p>

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || running} onClick={handleRun}>
          {running ? '생성 중...' : '🧮 계산기 생성'}
        </button>
      </div>

      {outcome?.kind === 'busy' && (
        <p className="status-card__error">⚠ {outcome.message}</p>
      )}
      {outcome?.kind === 'error' && (
        <p className="status-card__error">⚠ 계산기 생성 실패: {outcome.message}</p>
      )}
      {outcome?.kind === 'success' && (
        <>
          <p className={outcome.data.produced > 0 ? 'status-card__success' : 'status-card__hint'}>
            {outcome.data.produced > 0 ? '✅' : 'ℹ'} 계산기 생성 요청 완료 · 생산 {outcome.data.produced}건
            {' '}({REASON_LABEL[outcome.data.reason] || outcome.data.reason || '-'})
          </p>
          {outcome.data.published && (
            <p className="status-card__hint" style={{ overflowWrap: 'break-word' }}>
              제목: {outcome.data.published.title}
            </p>
          )}
        </>
      )}
    </div>
  )
}
