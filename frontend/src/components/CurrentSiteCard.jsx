import { useEffect, useState } from 'react'
import { getGeneralSettings, getOperationsSettings, getCalculators } from '../api/client.js'

// 🏢 현재 Site — CURRENT-SITE-02: dashboard.py render_current_site_card()(L242-271) 이관.
// 선택은 화면 상태(useCurrentSiteSelection)만 바꾸며 서버에 저장하지 않는다.
// Platform/활성 Feature는 원본과 같이 site가 아니라 현재 설정 기준으로 파생한다
// (_derive_platforms: WORDPRESS_URL 설정 + 계산기 존재, _derive_features: 고정 4종 +
// Telegram 토큰·Chat ID 설정 시 Telegram, ENABLE_STRATEGY_ROOM 시 Strategy).
// 원본의 RUN_MODE=="wordpress" 조건은 조회 API에 노출되지 않아 WORDPRESS_URL로만 판정한다.
const BASE_FEATURES = ['Scheduler', 'AI Assistant', 'Cost Manager', 'Retry Queue']

export default function CurrentSiteCard({ sites, currentSite, currentSiteId, onChange, error }) {
  const [derived, setDerived] = useState({ platforms: ['—'], features: BASE_FEATURES })

  useEffect(() => {
    let alive = true
    Promise.all([getGeneralSettings(), getOperationsSettings(), getCalculators()]).then(([g, o, c]) => {
      if (!alive) return
      const gd = g?.success ? g.data || {} : {}
      const od = o?.success ? o.data || {} : {}
      const hasCalc = Boolean(c?.success && (c.data?.calculators || []).length > 0)
      const platforms = []
      if (gd.WORDPRESS_URL) platforms.push('WordPress')
      if (hasCalc) platforms.push('Calculator')
      const features = [...BASE_FEATURES]
      if (gd.TELEGRAM_BOT_TOKEN?.configured && gd.TELEGRAM_CHAT_ID?.configured) features.push('Telegram')
      if (od.ENABLE_STRATEGY_ROOM) features.push('Strategy')
      setDerived({ platforms: platforms.length ? platforms : ['—'], features })
    })
    return () => { alive = false }
  }, [])

  const loading = sites === null
  const hasSites = Array.isArray(sites) && sites.length > 0
  const name = currentSite ? (currentSite.site_name || currentSite.site_id || 'CalcMate') : 'CalcMate'

  return (
    <div className="status-card" data-testid="current-site-card">
      <h3 className="status-card__title">🏢 현재 Site: {loading ? '불러오는 중...' : name}</h3>
      {hasSites && (
        <div className="form-row">
          <label className="form-label" htmlFor="current-site-select">Site 변경</label>
          <select id="current-site-select" className="form-select" value={currentSiteId || ''}
                  onChange={(e) => onChange?.(e.target.value)}>
            {sites.map((s) => (
              <option key={s.site_id} value={s.site_id}>
                {(s.site_name || s.site_id || '(이름없음)') + (s.status && s.status !== 'active' ? ` (${s.status})` : '')}
              </option>
            ))}
          </select>
        </div>
      )}
      {!loading && !hasSites && (
        <p className="status-card__hint">{error ? `⚠ ${error}` : '등록 사이트 없음 — 기본 사이트'}</p>
      )}
      <p className="status-card__hint">Platform: {derived.platforms.join('  +  ')}</p>
      <p className="status-card__hint">활성 Feature: {derived.features.join(' / ')}</p>
    </div>
  )
}
