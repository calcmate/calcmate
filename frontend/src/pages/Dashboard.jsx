import { useCallback, useEffect, useState } from 'react'
import StatusCard from '../components/StatusCard.jsx'
import SchedulerCard from '../components/SchedulerCard.jsx'
import RecentActivityPanel from '../components/RecentActivityPanel.jsx'
import DashboardKpiPanel from '../components/DashboardKpiPanel.jsx'
import DashboardPipelineStatusPanel from '../components/DashboardPipelineStatusPanel.jsx'
import DashboardProgressPanel from '../components/DashboardProgressPanel.jsx'
import DashboardStatusSummaryPanel from '../components/DashboardStatusSummaryPanel.jsx'
import CalculatorQuickActionPanel from '../components/CalculatorQuickActionPanel.jsx'
import PipelineQuickActionPanel from '../components/PipelineQuickActionPanel.jsx'
import BlogOneRunQuickActionPanel from '../components/BlogOneRunQuickActionPanel.jsx'
import CurrentSiteCard from '../components/CurrentSiteCard.jsx'
import { useCurrentSiteSelection } from '../components/CurrentSiteContext.jsx'
import IntegratedRunQuickActionPanel from '../components/IntegratedRunQuickActionPanel.jsx'
import {
  getHealth,
  getDashboardStatus,
  getBlogSchedulerStatus,
  getCalculatorSchedulerStatus,
  getContentSyncStatus,
} from '../api/client.js'

// 운영센터(/) — STEP 18-G: System Status에 Dashboard 상태 표시 + Recent Activity 추가.
// STEP S11: Quick Action 「🧮 계산기 생성」 추가(그 외 상태 카드는 여전히 조회 전용).
export default function Dashboard() {
  const [health, setHealth] = useState(null)
  const [dashboardStatus, setDashboardStatus] = useState(null)
  const [blog, setBlog] = useState(null)
  const [calc, setCalc] = useState(null)
  const [sync, setSync] = useState(null)
  const [loading, setLoading] = useState(true)
  // CURRENT-SITE-02: dashboard.py current_site_id(세션 상태) — 저장하지 않는다.
  const siteSel = useCurrentSiteSelection()

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      getHealth(),
      getDashboardStatus(),
      getBlogSchedulerStatus(),
      getCalculatorSchedulerStatus(),
      getContentSyncStatus(),
    ]).then(([h, d, b, c, s]) => {
      setHealth(h)
      setDashboardStatus(d)
      setBlog(b)
      setCalc(c)
      setSync(s)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const apiOk = Boolean(health?.success && health?.data?.status === 'ok')
  const apiFailed = !loading && !health?.success
  const dashboardOk = Boolean(dashboardStatus?.success && dashboardStatus?.data?.dashboard === 'fastapi')
  const dashboardFailed = !loading && !dashboardStatus?.success

  return (
    <div className="page">
      <div className="page__header">
        <h1>CalcMate Dashboard</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>
      <div className="card-grid">
        {/* CURRENT-SITE-02: dashboard.py render_dashboard_home()과 같이 최상단 '현재 Site' 카드. */}
        <CurrentSiteCard sites={siteSel.sites} currentSite={siteSel.currentSite}
                         currentSiteId={siteSel.currentSiteId} onChange={siteSel.setCurrentSiteId}
                         error={siteSel.error} />
        {/* STEP P2-01: dashboard.py render_kpi_cards()(운영센터 홈 KPI 5종) 이관 —
            원본 레이아웃과 동일하게 최상단에 배치. */}
        <DashboardKpiPanel />
        {/* STEP P2-02: dashboard.py render_pipeline_status()/render_progress()
            이관 — 원본과 동일하게 KPI 바로 다음, Quick Action보다 먼저 배치. */}
        <DashboardPipelineStatusPanel />
        <DashboardProgressPanel />
        {/* STEP P2-10: dashboard.py "📊 현황" 탭(원본은 "🏠 운영센터"의 형제
            탭이었지만, 이 React 앱은 기존 Dashboard 구조에 패널로 통합해
            KPI/Workflow/Progress와 시각적 일관성을 유지한다 — 별도 라우트를
            새로 만들지 않는다). */}
        <DashboardStatusSummaryPanel />
        <StatusCard title="API">
          {loading && <p className="status-card__hint">불러오는 중...</p>}
          {apiFailed && <p className="status-card__error">⚠ API 연결 실패</p>}
          {!loading && !apiFailed && (
            <span className={`badge ${apiOk ? 'badge--on' : 'badge--off'}`}>
              {apiOk ? '정상' : '오류'}
            </span>
          )}
        </StatusCard>
        <StatusCard title="Dashboard">
          {loading && <p className="status-card__hint">불러오는 중...</p>}
          {dashboardFailed && <p className="status-card__error">⚠ API 연결 실패</p>}
          {!loading && !dashboardFailed && (
            <span className={`badge ${dashboardOk ? 'badge--on' : 'badge--off'}`}>
              {dashboardOk ? '정상' : '오류'}
            </span>
          )}
        </StatusCard>
        <SchedulerCard
          title="Blog Scheduler"
          data={blog?.data}
          loading={loading}
          failed={!loading && !blog?.success}
        />
        <SchedulerCard
          title="Calculator Scheduler"
          data={calc?.data}
          loading={loading}
          failed={!loading && !calc?.success}
        />
        <SchedulerCard
          title="Content Sync"
          data={sync?.data}
          loading={loading}
          failed={!loading && !sync?.success}
        />
        <RecentActivityPanel />
        {/* STEP S13: Dashboard Quick Action 「▶ 실행」(통합 실행) — dashboard.py의
            실제 배치와 동일하게 "고급 실행(수동)" 계열보다 먼저 표시. */}
        <IntegratedRunQuickActionPanel site={siteSel.currentSite} />
        {/* STEP S11: Dashboard Quick Action 「🧮 계산기 생성」만 이관 — 다른
            Quick Action(파이프라인 실행/글 생성)은 이번 STEP 범위 밖. */}
        <CalculatorQuickActionPanel />
        {/* STEP S12: Dashboard Quick Action 「▶ 파이프라인 실행(전량)」만 이관. */}
        <PipelineQuickActionPanel />
        {/* SMALL-GAPS-02: 「📝 글 생성(1건)」(main.run_once max_count=1) 이관. */}
        <BlogOneRunQuickActionPanel />
      </div>
    </div>
  )
}
