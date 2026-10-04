import { useEffect, useState } from 'react'
import { getCurrentUser, postPipelineRunOne } from '../api/client.js'

// 📝 글 생성(1건) — CALCMATE-REMAINING-MIGRATION-SMALL-GAPS-02: dashboard.py
// "📝 글 생성(1건)" 버튼("🔧 고급 실행(수동)" expander 안, PIPE.run_once(cfg,
// max_count=1))의 React 이관. POST /api/scheduler/pipeline/run-one.
//
// 주의: Blog Scheduler의 "지금 실행"(runBlogSchedulerOnce, BLOG_SCHEDULE.enabled
// 필요, Golden10 엔진)과 다른 기능이다 — 수집→작성→발행 파이프라인을 최대 1건만
// 실행하며 Blog Scheduler 스위치를 켜거나 끄지 않는다. 다른 파이프라인/Blog
// Scheduler 실행과는 같은 blog lock을 공유한다(겹치면 LOCK_CONFLICT).
const REASON_LABEL = {
  budget_daily: '일일 AI 예산 초과로 중단됨',
  budget_monthly: '월간 AI 예산 초과로 중단됨',
  budget_midrun: '처리 중 예산 초과로 중단됨',
  no_items: '수집된 항목 없음',
  dry_run: 'dry-run(실행 안 함)',
  ok: '정상 완료',
}

export default function BlogOneRunQuickActionPanel() {
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
    postPipelineRunOne().then((res) => {
      setRunning(false)
      if (res?.success) {
        setOutcome({ kind: 'success', data: res.data })
      } else if (res?.error?.code === 'LOCK_CONFLICT') {
        setOutcome({ kind: 'busy', message: res.error.message })
      } else {
        setOutcome({ kind: 'error', message: res?.error?.message || '글 생성 요청 실패' })
      }
    })
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">📝 글 생성(1건)</h3>
      <p className="status-card__hint">
        수집→작성→발행 파이프라인을 최대 1건만 실행합니다. Blog Scheduler의 "지금 실행"과 다른 기능이며,
        Blog Scheduler 사용 여부와 관계없이 실행됩니다.
      </p>

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || running} onClick={handleRun}>
          {running ? '실행 중...' : '📝 글 생성(1건)'}
        </button>
      </div>

      {outcome?.kind === 'busy' && (
        <p className="status-card__error">⚠ 다른 실행이 진행 중입니다: {outcome.message}</p>
      )}
      {outcome?.kind === 'error' && (
        <p className="status-card__error">⚠ 글 생성 실패: {outcome.message}</p>
      )}
      {outcome?.kind === 'success' && (
        <p className={outcome.data.produced > 0 ? 'status-card__success' : 'status-card__hint'}>
          {outcome.data.produced > 0 ? '✅' : 'ℹ'} 글 생성 요청 완료 · 생산 {outcome.data.produced}건
          {' '}({REASON_LABEL[outcome.data.reason] || outcome.data.reason || '-'})
        </p>
      )}
    </div>
  )
}
