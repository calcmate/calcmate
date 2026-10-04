import { NavLink, useLocation } from 'react-router-dom'

// STEP 18-D: 운영센터/Scheduler. STEP 18-F: Calculators. STEP 18-G: 로그/상태.
// STEP 18-M: Settings/Health. STEP 18-P: Publish/Trash(조회 전용).
// STEP 18-X: Blog(실제 운영 calcmate.kr 전용, articles DB와 별개).
// STEP 18-Z: AI 사용비용(Streamlit "💰 Revenue > 💰 비용 모니터" 탭 복구 — 기존
// CostPanel/getCosts()/api/costs 재사용, 새 로직 없음).
// STEP V1-OPS-04: 계산기/블로그를 독립 상위 영역(그룹)으로 분리하고 각각
// 목록·생성/관리·Scheduler 하위탭을 둔다. 미이관 기능(App Factory Mode B,
// AI Workspace/Assistant, 사이트 관리, Build 등)은 메뉴에 넣지 않는다 —
// 기존에 존재하는 페이지/라우트만 재배치했다.
// STEP S8: 전략회의실(Strategy Room) 이관 — run_strategy_room() 재사용, 새
// 분석 로직 없음.
// STEP S9: 작업 현황 보드(Kanban/Workboard) 이관 — 읽기 전용, 상태 변경/
// 드래그앤드롭 기능은 추가하지 않음(기존 Streamlit에도 없던 기능).
// STEP P2-04: 사이트 관리(Site Management) 조회 전용 이관 — 생성/수정/삭제/
// Import 등 write는 이번 STEP에서 추가하지 않음(별도 STEP에서 판단).
const NAV_ITEMS = [
  { type: 'link', to: '/', label: '🏠 운영센터', end: true },
  {
    type: 'group',
    label: '🧮 계산기',
    children: [
      // STEP V1-OPS-06: NavLink의 기본 isActive는 pathname만 비교하고
      // query string은 무시한다 — "/calculators"와 "/calculators?new=1"이
      // 같은 pathname을 공유하므로 matchSearch로 쿼리까지 비교해 하나만
      // active가 되도록 한다.
      { to: '/calculators', label: '목록', end: true, matchSearch: '' },
      // "생성/관리": 계산기 목록 페이지가 이미 상세(관리) 진입과 생성 패널
      // 토글을 함께 제공한다 — ?new=1이면 생성 패널을 펼친 상태로 진입한다.
      { to: '/calculators?new=1', label: '생성/관리', end: false, matchSearch: 'new=1' },
      { to: '/calculator-scheduler', label: 'Scheduler', end: false },
    ],
  },
  {
    type: 'group',
    label: '📝 블로그',
    children: [
      { to: '/blog', label: '목록/관리', end: false },
      // "생성"과 "Scheduler"는 현재 동일한 화면(BlogSchedulerPanel)으로
      // 연결된다 — 콘텐츠 생성(수동 1회 실행)과 스케줄 설정이 아직 분리된
      // 화면으로 존재하지 않기 때문이다(미이관 기능을 새로 만들지 않음).
      { to: '/blog-scheduler', label: '생성', end: false },
      { to: '/blog-scheduler', label: 'Scheduler', end: false },
    ],
  },
  { type: 'link', to: '/publish', label: '📋 Publish', end: false },
  { type: 'link', to: '/trash', label: '🗑️ Trash', end: false },
  { type: 'link', to: '/costs', label: '💰 AI 비용', end: false },
  { type: 'link', to: '/strategy-room', label: '🧠 전략회의실', end: false },
  // AI-ASSISTANT-02: dashboard.py "🤖 AI Assistant" 이관.
  { type: 'link', to: '/assistant', label: '🤖 AI Assistant', end: false },
  // AI-WORKSPACE-02: dashboard.py "💬 AI Workspace" 이관.
  { type: 'link', to: '/ai-workspace', label: '💬 AI Workspace', end: false },
  { type: 'link', to: '/workboard', label: '📋 작업 보드', end: false },
  { type: 'link', to: '/sites', label: '🌐 사이트 관리', end: false },
  { type: 'link', to: '/site-wizard', label: '🧙 사이트 마법사', end: false },
  { type: 'link', to: '/logs', label: '📊 로그', end: false },
  { type: 'link', to: '/settings', label: '⚙️ Settings', end: false },
  { type: 'link', to: '/health', label: '❤️ Health', end: false },
]

function NavLinkItem({ to, label, end, sub, onNavigate, matchSearch }) {
  const location = useLocation()
  // matchSearch가 주어진 항목(계산기 목록/생성/관리)만 query string까지
  // 비교해서 active를 판정한다 — 그 외 항목은 NavLink 기본 동작(pathname만
  // 비교) 그대로 유지한다.
  const queryAware = matchSearch !== undefined
  const toPath = to.split('?')[0]
  const queryActive = location.pathname === toPath && location.search.replace(/^\?/, '') === matchSearch

  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => {
        const active = queryAware ? queryActive : isActive
        return `sidebar__link ${sub ? 'sidebar__link--sub' : ''} ${active ? 'sidebar__link--active' : ''}`
      }}
      onClick={onNavigate}
    >
      {label}
    </NavLink>
  )
}

export default function Sidebar({ open, onNavigate }) {
  return (
    <nav className={`sidebar ${open ? 'sidebar--open' : ''}`} aria-label="주 메뉴">
      <ul className="sidebar__list">
        {NAV_ITEMS.map((item) =>
          item.type === 'group' ? (
            <li key={item.label}>
              <span className="sidebar__group-label">{item.label}</span>
              <ul className="sidebar__sublist">
                {item.children.map((child) => (
                  <li key={child.to + child.label}>
                    <NavLinkItem {...child} sub onNavigate={onNavigate} />
                  </li>
                ))}
              </ul>
            </li>
          ) : (
            <li key={item.to}>
              <NavLinkItem {...item} onNavigate={onNavigate} />
            </li>
          )
        )}
      </ul>
    </nav>
  )
}
