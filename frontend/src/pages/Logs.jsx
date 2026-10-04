import ErrorLogPanel from '../components/ErrorLogPanel.jsx'
import LiveLogPanel from '../components/LiveLogPanel.jsx'
import CostPanel from '../components/CostPanel.jsx'
import PipelinePanel from '../components/PipelinePanel.jsx'
import DashboardAiPipelinePanel from '../components/DashboardAiPipelinePanel.jsx'

// /logs — 오류 로그 / 실시간 로그 / 비용 모니터 / Pipeline 상태를 한 화면에 모은다(STEP 18-G).
// STEP P2-11: dashboard.py "📊 AI Pipeline" 탭(cost/token/모델별 비용/최근
// 로그 포함 전체 화면)을 기존 PipelinePanel(공개 endpoint, 간단한 단계
// 목록만 표시) 바로 다음에 추가한다 — PipelinePanel 자체는 수정하지 않는다
// (STEP 18-G 코드 무변경 원칙).
export default function Logs() {
  return (
    <div className="page">
      <div className="page__header">
        <h1>로그 / 상태</h1>
      </div>
      <div className="card-grid">
        <ErrorLogPanel />
        <LiveLogPanel />
        <CostPanel />
        <PipelinePanel />
        <DashboardAiPipelinePanel />
      </div>
    </div>
  )
}
