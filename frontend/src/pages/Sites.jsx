import SiteManagementPanel from '../components/SiteManagementPanel.jsx'

// /sites — STEP P2-04: dashboard.py "🌐 사이트 관리" 탭의 사이트 목록 조회만
// 이관한다(GET /api/sites). 생성/수정/삭제/Import 등 write 기능은 이번 STEP
// 범위 밖이며, 별도 STEP에서 판단한다.
export default function Sites() {
  return (
    <div className="page">
      <div className="page__header">
        <h1>사이트 관리</h1>
      </div>
      <div className="card-grid">
        <SiteManagementPanel />
      </div>
    </div>
  )
}
