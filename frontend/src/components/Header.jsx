export default function Header({ onMenuClick }) {
  return (
    <header className="header">
      <button
        type="button"
        className="header__menu-btn"
        aria-label="메뉴 열기"
        onClick={onMenuClick}
      >
        ☰
      </button>
      <span className="header__title">CalcMate Dashboard</span>
    </header>
  )
}
