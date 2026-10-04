import { useEffect, useState } from 'react'
import { getCurrentUser, postPipelineRunOnce } from '../api/client.js'

// ▶ 파이프라인 실행(전량) — STEP S12: dashboard.py "▶ 파이프라인 실행(전량)" 버튼
// (dashboard.py:472-473, "🔧 고급 실행(수동)" expander 안)과 동일한 실행 의미를
// 재현한다. main.py의 run_once(cfg)를 그대로 호출하며(목표 건수는
// DAILY_POST_COUNT 설정값), 파이프라인 본체는 새로 만들지 않는다.
//
// 주의: "전량"은 "무제한"이 아니라 DAILY_POST_COUNT(설정값, 현재 1) 만큼만
// 생산한다는 뜻이다 — /api/scheduler/blog/run-once(Blog Scheduler, 다른 함수)와도
// 다른 별개의 기능이다.
const REASON_LABEL = {
  budget_daily: '일일 AI 예산 초과로 중단됨',
  budget_monthly: '월간 AI 예산 초과로 중단됨',
  budget_midrun: '처리 중 예산 초과로 중단됨',
  no_items: '수집된 항목 없음',
  dry_run: 'dry-run(실행 안 함)',
  ok: '정상 완료',
}

export default function PipelineQuickActionPanel() {
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
    postPipelineRunOnce().then((res) => {
      setRunning(false)
      if (res?.success) {
        setOutcome({ kind: 'success', data: res.data })
      } else if (res?.error?.code === 'LOCK_CONFLICT') {
        setOutcome({ kind: 'busy', message: res.error.message })
      } else {
        setOutcome({ kind: 'error', message: res?.error?.message || '파이프라인 실행 요청 실패' })
      }
    })
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">▶ 파이프라인 실행(전량)</h3>
      <p className="status-card__hint">
        수집→작성→발행 전체 파이프라인을 DAILY_POST_COUNT(설정값) 건만큼 실행합니다(Blog Scheduler와는 다른 별개 실행).
      </p>

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || running} onClick={handleRun}>
          {running ? '실행 중...' : '▶ 파이프라인 실행(전량)'}
        </button>
      </div>

      {outcome?.kind === 'busy' && (
        <p className="status-card__error">⚠ {outcome.message}</p>
      )}
      {outcome?.kind === 'error' && (
        <p className="status-card__error">⚠ 파이프라인 실행 실패: {outcome.message}</p>
      )}
      {outcome?.kind === 'success' && (
        <p className={outcome.data.produced > 0 ? 'status-card__success' : 'status-card__hint'}>
          {outcome.data.produced > 0 ? '✅' : 'ℹ'} 파이프라인 실행 요청 완료 · 생산 {outcome.data.produced}건
          {' '}({REASON_LABEL[outcome.data.reason] || outcome.data.reason || '-'})
        </p>
      )}
    </div>
  )
}
