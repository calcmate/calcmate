import { Link } from 'react-router-dom'

export default function CalculatorCard({ calc }) {
  return (
    <Link to={`/calculators/${encodeURIComponent(calc.slug)}`} className="calc-card">
      <div className="calc-card__slug">{calc.slug}</div>
      <div className="calc-card__name">{calc.name || '(이름없음)'}</div>
      <div className="calc-card__badges">
        <span className={`badge ${calc.db_status === 'active' ? 'badge--on' : 'badge--off'}`}>
          {calc.db_status || 'unknown'}
        </span>
        {calc.is_legal_hold && <span className="badge badge--hold">LEGAL HOLD</span>}
        {calc.is_deployed && <span className="badge badge--on">배포됨</span>}
      </div>
    </Link>
  )
}
