import CostPanel from '../components/CostPanel.jsx'

// /costs — 「AI 사용비용」 탭 복구(STEP 18-Z). 기존 STEP 18-G의 CostPanel/getCosts()/
// /api/costs를 그대로 재사용한다 — 새 비용 계산 로직을 만들지 않는다. Streamlit의
// "💰 Revenue > 💰 비용 모니터"(dashboard.py) 탭과 동일한 데이터 소스다.
export default function Cost() {
  return (
    <div className="page">
      <div className="page__header">
        <h1>AI 사용비용</h1>
      </div>
      <div className="card-grid">
        <CostPanel />
      </div>
    </div>
  )
}
