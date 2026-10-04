import { useCallback, useEffect, useState } from 'react'
import {
  getSites, postCreateSite, postImportSites, getSitesExport, getCurrentUser,
  getSite, putUpdateSite, postSaveOverride, postResetOverride, getCalculators,
  postActivateSite, postDeactivateSite, postArchiveSite, postRestoreSite,
  deleteSite, postCloneSite,
} from '../api/client.js'

// 🌐 사이트 관리 — STEP P2-04: dashboard.py "🌐 사이트 관리" 탭(dashboard.py:
// 1012-1453)의 사이트 목록 표시 이관(조회 전용).
// STEP P2-06: "➕ 사이트 추가"(dashboard.py:1287-1343)와 "⬆️ Import"
// (dashboard.py:1037-1070)만 추가로 이관한다. Update/Delete/Archive/Restore/
// Clone/Override/Calculator 등록·삭제/Export는 이번 STEP에서도 다루지 않는다.
// STEP P2-07: 기본 정보 수정("💾 수정 저장", dashboard.py:1369-1373)과
// Site Settings Override 저장/초기화(dashboard.py:1072-1166)만 추가로
// 이관한다. Delete/Archive/Restore/Clone/Calculator 등록·삭제/Export는
// 이번 STEP에서도 다루지 않는다.
// STEP P2-08: 활성화/비활성화(dashboard.py:1374-1379)와 보관/복원
// (dashboard.py:1380-1385, 1398-1401)만 추가로 이관한다. Hard Delete/Clone/
// Calculator 등록·삭제/Export는 이번 STEP에서도 다루지 않는다 — 보관된
// 사이트에는 원본과 동일하게 활성화/비활성화 버튼을 숨기고 복원 버튼만
// 보여준다.
// STEP P2-09: 영구 삭제("⛔ 영구 삭제", dashboard.py:1402-1409)와 복제
// ("📑 복제(Clone)", dashboard.py:1411-1433)만 추가로 이관한다. 영구 삭제는
// 원본과 동일하게 "DELETE" 정확히 입력해야만 버튼이 활성화된다. 복제는
// 원본과 동일하게 site_tags/AI 프로필만 미리 채우고 site_name/domain/
// WordPress 자격증명은 항상 새로 입력받는다.

export const TYPE_LABELS = ['블로그', '계산기', '정책정보', '금융', '제휴마케팅', '사용자정의']

export const AI_PROFILES = ['gemini_flash', 'gemini_pro', 'gpt4o', 'gpt4o_mini', 'claude_sonnet', 'claude_haiku', 'claude_opus']

export const GLOB = '(Global 기본값)'

export const WP_FEATS = ['글 작성', '자동 발행', 'SEO', '이미지 업로드', '카테고리']

export const CALC_FEATS = ['계산기 생성', '계산기 SEO 글', 'FAQ 생성', 'AI Reviewer', 'HTML 생성']

export const COMMON_FEATS = ['Scheduler', 'Telegram', 'AI Assistant', 'Analytics', 'Cost Manager', 'Retry Queue']

export const DEFAULT_AI = { research_ai: 'gemini_flash', writing_ai: 'gpt4o', review_ai: 'claude_sonnet' }

function SiteEditPanel({ siteId, isAdmin, onSaved }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [allCalculators, setAllCalculators] = useState([])

  const [basicName, setBasicName] = useState('')
  const [basicDomain, setBasicDomain] = useState('')
  const [basicCategory, setBasicCategory] = useState('')
  const [basicState, setBasicState] = useState('idle')
  const [basicMessage, setBasicMessage] = useState('')

  const [ov, setOv] = useState(null)
  const [ovState, setOvState] = useState('idle')
  const [ovMessage, setOvMessage] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    getSite(siteId).then((res) => {
      setLoading(false)
      if (res?.success) {
        const d = res.data
        setDetail(d)
        setBasicName(d.site_name || '')
        setBasicDomain(d.domain || '')
        setBasicCategory(d.site_tags || '')
        setOv({
          research_ai: d.research_ai || '', writing_ai: d.writing_ai || '', review_ai: d.review_ai || '',
          wordpress_url: d.wordpress_url || '', site_tags: d.site_tags || '',
          seo_keyword_count: d.seo_keyword_count || '', seo_length: d.seo_length || '',
          daily_override: d.daily_override || '', image_mode: d.image_mode || '',
          telegram_enabled: d.telegram_enabled || '', analytics_enabled: d.analytics_enabled || '',
          calc_active: d.calc_active || [],
        })
      }
    })
  }, [siteId])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    getCalculators().then((res) => {
      if (res?.success) setAllCalculators((res.data?.calculators || []).map((c) => c.name || c.slug).filter(Boolean))
    })
  }, [])

  const saveBasic = (e) => {
    e.preventDefault()
    if (basicState === 'saving') return
    setBasicState('saving')
    setBasicMessage('')
    putUpdateSite(siteId, { site_name: basicName, domain: basicDomain, category: basicCategory }).then((res) => {
      if (res?.success) {
        setBasicState('saved')
        setBasicMessage('저장되었습니다')
        load()
        onSaved()
      } else {
        setBasicState('error')
        setBasicMessage(res?.error?.message || '저장 실패')
      }
    })
  }

  const saveOverride = (e) => {
    e.preventDefault()
    if (!ov || ovState === 'saving') return
    setOvState('saving')
    setOvMessage('')
    postSaveOverride(siteId, ov).then((res) => {
      if (res?.success) {
        setOvState('saved')
        setOvMessage('저장되었습니다')
        load()
        onSaved()
      } else {
        setOvState('error')
        setOvMessage(res?.error?.message || '저장 실패')
      }
    })
  }

  const resetOverride = () => {
    if (ovState === 'saving') return
    setOvState('saving')
    setOvMessage('')
    postResetOverride(siteId).then((res) => {
      if (res?.success) {
        setOvState('saved')
        setOvMessage('Global 기본값으로 초기화되었습니다')
        load()
        onSaved()
      } else {
        setOvState('error')
        setOvMessage(res?.error?.message || '초기화 실패')
      }
    })
  }

  // 저장 후 재조회(loading=true) 시에도 detail이 이미 있으면 폼과 저장 결과
  // 메시지를 계속 보여준다 — 최초 조회 중일 때만 "불러오는 중..."으로 대체한다.
  if (loading && !detail) return <p className="status-card__hint">불러오는 중...</p>
  if (!detail) return <p className="status-card__error">⚠ 사이트 정보를 불러오지 못했습니다.</p>

  return (
    <div className="status-card">
      <form onSubmit={saveBasic}>
        <h4 className="status-card__title">✏️ 기본 정보 수정</h4>
        <div className="form-row">
          <label>
            사이트명
            <input type="text" value={basicName} onChange={(e) => setBasicName(e.target.value)} disabled={basicState === 'saving'} />
          </label>
          <label>
            도메인
            <input type="text" value={basicDomain} onChange={(e) => setBasicDomain(e.target.value)} disabled={basicState === 'saving'} />
          </label>
          <label>
            카테고리
            <input type="text" value={basicCategory} onChange={(e) => setBasicCategory(e.target.value)} disabled={basicState === 'saving'} />
          </label>
        </div>
        <div className="form-actions">
          <button type="submit" className="refresh-btn" disabled={!isAdmin || basicState === 'saving'}>
            {basicState === 'saving' ? '저장 중...' : '💾 수정 저장'}
          </button>
        </div>
        {basicState === 'saved' && <p className="status-card__success">✅ {basicMessage}</p>}
        {basicState === 'error' && <p className="status-card__error">⚠ {basicMessage}</p>}
      </form>

      <div className="status-card__hint">
        <span className={`badge ${detail.wordpress_configured ? 'badge--on' : 'badge--off'}`}>
          WordPress {detail.wordpress_configured ? '설정됨' : '미설정'}
        </span>
      </div>

      {ov && (
        <form onSubmit={saveOverride}>
          <h4 className="status-card__title">⚙️ Site Settings (Override)</h4>
          <p className="status-card__hint">빈 값=Global 상속, 값 있으면 Override</p>

          <p className="status-card__hint"><strong>AI</strong></p>
          <div className="form-row">
            {[['research_ai', 'Research AI'], ['writing_ai', 'Writing AI'], ['review_ai', 'Review AI']].map(([field, label]) => (
              <label key={field}>
                {label}
                <select value={ov[field] || ''} onChange={(e) => setOv({ ...ov, [field]: e.target.value })} disabled={ovState === 'saving'}>
                  <option value="">{GLOB}</option>
                  {AI_PROFILES.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </label>
            ))}
          </div>

          <p className="status-card__hint"><strong>WordPress / SEO</strong></p>
          <div className="form-row">
            <label>
              WordPress URL
              <input type="text" value={ov.wordpress_url} onChange={(e) => setOv({ ...ov, wordpress_url: e.target.value })} disabled={ovState === 'saving'} />
            </label>
            <label>
              카테고리(site_tags)
              <input type="text" value={ov.site_tags} onChange={(e) => setOv({ ...ov, site_tags: e.target.value })} disabled={ovState === 'saving'} />
            </label>
          </div>
          <div className="form-row">
            <label>
              SEO 키워드 수
              <input type="text" value={ov.seo_keyword_count} onChange={(e) => setOv({ ...ov, seo_keyword_count: e.target.value })} disabled={ovState === 'saving'} placeholder="Global 5" />
            </label>
            <label>
              SEO 글 길이
              <input type="text" value={ov.seo_length} onChange={(e) => setOv({ ...ov, seo_length: e.target.value })} disabled={ovState === 'saving'} placeholder="Global 1500" />
            </label>
          </div>

          <p className="status-card__hint"><strong>Scheduler / Image</strong></p>
          <div className="form-row">
            <label>
              일 발행수
              <input type="text" value={ov.daily_override} onChange={(e) => setOv({ ...ov, daily_override: e.target.value })} disabled={ovState === 'saving'} />
            </label>
            <label>
              이미지 생성 방식
              <select value={ov.image_mode || ''} onChange={(e) => setOv({ ...ov, image_mode: e.target.value })} disabled={ovState === 'saving'}>
                <option value="">{GLOB}</option>
                <option value="free_pollinations">free_pollinations</option>
                <option value="openai">openai</option>
                <option value="none">none</option>
              </select>
            </label>
          </div>

          <p className="status-card__hint"><strong>Telegram / Analytics</strong></p>
          <div className="form-row">
            <label>
              Telegram 알림
              <select value={ov.telegram_enabled || ''} onChange={(e) => setOv({ ...ov, telegram_enabled: e.target.value })} disabled={ovState === 'saving'}>
                <option value="">{GLOB}</option>
                <option value="ON">ON</option>
                <option value="OFF">OFF</option>
              </select>
            </label>
            <label>
              Analytics
              <select value={ov.analytics_enabled || ''} onChange={(e) => setOv({ ...ov, analytics_enabled: e.target.value })} disabled={ovState === 'saving'}>
                <option value="">{GLOB}</option>
                <option value="ON">ON</option>
                <option value="OFF">OFF</option>
              </select>
            </label>
          </div>

          <p className="status-card__hint"><strong>Calculator (활성 계산기)</strong></p>
          <div className="form-row" style={{ flexWrap: 'wrap' }}>
            {allCalculators.length === 0 && <span className="status-card__hint">등록된 계산기가 없습니다.</span>}
            {allCalculators.map((name) => (
              <label key={name} style={{ minWidth: 'auto' }}>
                <input
                  type="checkbox"
                  checked={ov.calc_active.includes(name)}
                  disabled={ovState === 'saving'}
                  onChange={(e) => {
                    const next = e.target.checked
                      ? [...ov.calc_active, name]
                      : ov.calc_active.filter((n) => n !== name)
                    setOv({ ...ov, calc_active: next })
                  }}
                />
                {' '}{name}
              </label>
            ))}
          </div>

          <div className="form-actions">
            <button type="submit" className="refresh-btn" disabled={!isAdmin || ovState === 'saving'}>
              {ovState === 'saving' ? '저장 중...' : '💾 Override 저장'}
            </button>
            <button type="button" className="refresh-btn" disabled={!isAdmin || ovState === 'saving'} onClick={resetOverride}>
              ↩️ Override 초기화(Global 복귀)
            </button>
          </div>
          {ovState === 'saved' && <p className="status-card__success">✅ {ovMessage}</p>}
          {ovState === 'error' && <p className="status-card__error">⚠ {ovMessage}</p>}
        </form>
      )}
    </div>
  )
}

// STEP P2-08: 활성화/비활성화/보관/복원. 원본(dashboard.py:1374-1401)과 동일하게
// 보관된(archived) 사이트에는 활성화/비활성화/보관 버튼을 숨기고 복원 버튼만
// 보여준다 — 그 외 상태에서는 활성/비활성 토글과 보관 버튼만 보여준다.
function SiteStatusControls({ site, isAdmin, onSaved }) {
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState(null)

  const run = (action, fn) => {
    if (busy) return
    setBusy(true)
    setOutcome(null)
    fn(site.site_id).then((res) => {
      setBusy(false)
      if (res?.success) {
        setOutcome({ kind: 'success', action })
        onSaved()
      } else {
        setOutcome({ kind: 'error', message: res?.error?.message || `${action} 실패` })
      }
    })
  }

  const archived = site.status === 'archived'
  const active = site.status === 'active'

  return (
    <div className="status-card__hint">
      <div className="form-actions" style={{ flexWrap: 'wrap' }}>
        {!archived && (
          <button
            type="button" className="refresh-btn" disabled={!isAdmin || busy}
            onClick={() => run(active ? '비활성화' : '활성화', active ? postDeactivateSite : postActivateSite)}
          >
            {busy ? '처리 중...' : active ? '⏸ 비활성화' : '▶ 활성화'}
          </button>
        )}
        {!archived && (
          <button
            type="button" className="refresh-btn" disabled={!isAdmin || busy}
            onClick={() => run('보관', postArchiveSite)}
          >
            {busy ? '처리 중...' : '🗑️ 보관'}
          </button>
        )}
        {archived && (
          <button
            type="button" className="refresh-btn" disabled={!isAdmin || busy}
            onClick={() => run('복원', postRestoreSite)}
          >
            {busy ? '처리 중...' : '♻️ 복원'}
          </button>
        )}
      </div>
      {outcome?.kind === 'success' && <p className="status-card__success">✅ {outcome.action}되었습니다</p>}
      {outcome?.kind === 'error' && <p className="status-card__error">⚠ {outcome.message}</p>}
    </div>
  )
}

// STEP P2-09: 영구 삭제(Hard Delete) — 원본(dashboard.py:1402-1409)과 동일하게
// 확인란에 정확히 "DELETE"를 입력해야만 버튼이 활성화된다.
function SiteDeleteControl({ site, isAdmin, onSaved }) {
  const [expanded, setExpanded] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState(null)

  const handleDelete = () => {
    if (busy || confirmText.trim() !== 'DELETE') return
    setBusy(true)
    setOutcome(null)
    deleteSite(site.site_id, confirmText.trim()).then((res) => {
      setBusy(false)
      if (res?.success) {
        setOutcome({ kind: 'success' })
        onSaved()
      } else {
        setOutcome({ kind: 'error', message: res?.error?.message || '삭제 실패' })
      }
    })
  }

  return (
    <div className="status-card__hint">
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={() => setExpanded(!expanded)}>
          {expanded ? '닫기' : '⛔ 영구 삭제'}
        </button>
      </div>
      {expanded && (
        <div className="form-row">
          <label>
            영구삭제: "DELETE" 입력
            <input
              type="text" value={confirmText} disabled={busy}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="DELETE"
            />
          </label>
          <div className="form-actions">
            <button
              type="button" className="refresh-btn"
              disabled={!isAdmin || busy || confirmText.trim() !== 'DELETE'}
              onClick={handleDelete}
            >
              {busy ? '삭제 중...' : '⛔ 영구 삭제 실행'}
            </button>
          </div>
        </div>
      )}
      {outcome?.kind === 'success' && <p className="status-card__success">✅ 영구 삭제되었습니다</p>}
      {outcome?.kind === 'error' && <p className="status-card__error">⚠ {outcome.message}</p>}
    </div>
  )
}

// STEP P2-09: 복제(Clone) — 원본(dashboard.py:1411-1433)과 동일하게 site_tags/
// AI 프로필(research_ai/writing_ai/review_ai)만 서버가 원본에서 복사하고,
// site_name/domain/WordPress 자격증명은 항상 새로 입력받는다.
function SiteCloneForm({ site, isAdmin, onSaved }) {
  const [expanded, setExpanded] = useState(false)
  const [siteName, setSiteName] = useState('')
  const [domain, setDomain] = useState('')
  const [wpUrl, setWpUrl] = useState('')
  const [wpUser, setWpUser] = useState('')
  const [wpPw, setWpPw] = useState('')
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState(null)

  const openForm = () => {
    setSiteName(`${site.site_name || ''} (복사본)`)
    setDomain('')
    setWpUrl('')
    setWpUser('')
    setWpPw('')
    setOutcome(null)
    setExpanded(true)
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setOutcome(null)
    postCloneSite(site.site_id, {
      site_name: siteName, domain, wp_url: wpUrl, wp_user: wpUser, wp_app_password: wpPw,
    }).then((res) => {
      setBusy(false)
      if (res?.success) {
        setOutcome({ kind: 'success', data: res.data })
        setWpPw('')
        onSaved()
      } else {
        setOutcome({ kind: 'error', message: res?.error?.message || '복제 실패' })
      }
    })
  }

  return (
    <div className="status-card__hint">
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={() => (expanded ? setExpanded(false) : openForm())}>
          {expanded ? '닫기' : '📑 복제'}
        </button>
      </div>
      {expanded && (
        <form onSubmit={handleSubmit}>
          <div className="form-row">
            <label>
              새 사이트명
              <input type="text" value={siteName} onChange={(e) => setSiteName(e.target.value)} disabled={busy} required />
            </label>
            <label>
              새 도메인
              <input type="text" value={domain} onChange={(e) => setDomain(e.target.value)} disabled={busy}
                     placeholder="example.com" required />
            </label>
          </div>
          <p className="status-card__hint">이 유형이 WordPress를 사용한다면 자격증명을 새로 입력하세요(복제 시 재입력).</p>
          <div className="form-row">
            <label>
              WordPress URL
              <input type="text" value={wpUrl} onChange={(e) => setWpUrl(e.target.value)} disabled={busy} />
            </label>
            <label>
              WordPress ID
              <input type="text" value={wpUser} onChange={(e) => setWpUser(e.target.value)} disabled={busy} />
            </label>
            <label>
              App Password
              <input type="password" value={wpPw} onChange={(e) => setWpPw(e.target.value)} disabled={busy} />
            </label>
          </div>
          <div className="form-actions">
            <button type="submit" className="refresh-btn" disabled={!isAdmin || busy}>
              {busy ? '복제 중...' : '📑 복제 실행'}
            </button>
          </div>
          {outcome?.kind === 'success' && (
            <p className="status-card__success">✅ '{outcome.data.site_name}' 복제 완료</p>
          )}
          {outcome?.kind === 'error' && <p className="status-card__error">⚠ {outcome.message}</p>}
        </form>
      )}
    </div>
  )
}

function SiteList({ sites, isAdmin, expandedId, onToggle, onSaved }) {
  if (sites.length === 0) {
    return <p className="status-card__hint">등록된 사이트가 없습니다.</p>
  }
  return (
    <div className="card-grid">
      {sites.map((s) => (
        <div className="status-card" key={s.site_id}>
          <h3 className="status-card__title">{s.site_name || '(이름없음)'}</h3>
          <p className="status-card__hint" style={{ overflowWrap: 'anywhere' }}>{s.domain}</p>
          <div className="form-actions" style={{ flexWrap: 'wrap' }}>
            <span className={`badge ${s.status === 'active' ? 'badge--on' : 'badge--off'}`}>
              {s.status || '-'}
            </span>
            <span className="badge badge--off">{s.site_type || '-'}</span>
            {(s.platforms || []).map((p) => (
              <span className="badge badge--on" key={p}>{p}</span>
            ))}
            {(s.platforms || []).length === 0 && (
              <span className="badge badge--off">Platform 미설정</span>
            )}
            <span className={`badge ${s.wordpress_configured ? 'badge--on' : 'badge--off'}`}>
              WordPress {s.wordpress_configured ? '연동됨' : '미연동'}
            </span>
          </div>
          <SiteStatusControls site={s} isAdmin={isAdmin} onSaved={onSaved} />
          <div className="form-actions">
            <button type="button" className="refresh-btn" onClick={() => onToggle(s.site_id)}>
              {expandedId === s.site_id ? '닫기' : '✏️ 수정'}
            </button>
          </div>
          {expandedId === s.site_id && (
            <SiteEditPanel siteId={s.site_id} isAdmin={isAdmin} onSaved={onSaved} />
          )}
          <SiteCloneForm site={s} isAdmin={isAdmin} onSaved={onSaved} />
          <SiteDeleteControl site={s} isAdmin={isAdmin} onSaved={onSaved} />
        </div>
      ))}
    </div>
  )
}

function SiteCreateForm({ isAdmin, onCreated }) {
  const [typeLabel, setTypeLabel] = useState('계산기')
  const [siteName, setSiteName] = useState('')
  const [domain, setDomain] = useState('')
  const [useWp, setUseWp] = useState(false)
  const [useCalc, setUseCalc] = useState(false)
  const [wpUrl, setWpUrl] = useState('')
  const [wpUser, setWpUser] = useState('')
  const [wpPw, setWpPw] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [outcome, setOutcome] = useState(null)

  const handleSubmit = (e) => {
    e.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setOutcome(null)
    const platforms = [...(useWp ? ['WordPress'] : []), ...(useCalc ? ['Calculator'] : [])]
    postCreateSite({
      type_label: typeLabel,
      site_name: siteName,
      domain,
      platforms,
      wp_url: wpUrl,
      wp_user: wpUser,
      wp_app_password: wpPw,
    }).then((res) => {
      setSubmitting(false)
      if (res?.success) {
        setOutcome({ kind: 'success', data: res.data })
        setSiteName('')
        setDomain('')
        setWpUrl('')
        setWpUser('')
        setWpPw('')
        onCreated()
      } else if (res?.error?.code === 'VALIDATION_ERROR') {
        setOutcome({ kind: 'validation', message: res.error.message })
      } else if (res?.error?.code === 'LOCK_CONFLICT') {
        setOutcome({ kind: 'busy', message: res.error.message })
      } else {
        setOutcome({ kind: 'error', message: res?.error?.message || '사이트 생성 실패' })
      }
    })
  }

  return (
    <form className="status-card" onSubmit={handleSubmit}>
      <h3 className="status-card__title">➕ 사이트 추가</h3>
      <div className="form-row">
        <label>
          유형
          <select value={typeLabel} onChange={(e) => setTypeLabel(e.target.value)} disabled={submitting}>
            {TYPE_LABELS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
      </div>
      <div className="form-row">
        <label>
          사이트 이름
          <input type="text" value={siteName} onChange={(e) => setSiteName(e.target.value)} disabled={submitting} required />
        </label>
        <label>
          도메인
          <input type="text" value={domain} onChange={(e) => setDomain(e.target.value)} disabled={submitting}
                 placeholder="example.com" required />
        </label>
      </div>
      <div className="form-row">
        <label>
          <input type="checkbox" checked={useWp} onChange={(e) => setUseWp(e.target.checked)} disabled={submitting} />
          {' '}WordPress
        </label>
        <label>
          <input type="checkbox" checked={useCalc} onChange={(e) => setUseCalc(e.target.checked)} disabled={submitting} />
          {' '}Calculator
        </label>
      </div>
      {useWp && (
        <div className="form-row">
          <label>
            WordPress URL
            <input type="text" value={wpUrl} onChange={(e) => setWpUrl(e.target.value)} disabled={submitting}
                   placeholder="https://yourblog.com" />
          </label>
          <label>
            WordPress ID
            <input type="text" value={wpUser} onChange={(e) => setWpUser(e.target.value)} disabled={submitting} />
          </label>
          <label>
            App Password
            <input type="password" value={wpPw} onChange={(e) => setWpPw(e.target.value)} disabled={submitting} />
          </label>
        </div>
      )}
      <div className="form-actions">
        <button type="submit" className="refresh-btn" disabled={!isAdmin || submitting}>
          {submitting ? '생성 중...' : '💾 사이트 등록'}
        </button>
      </div>
      {outcome?.kind === 'success' && (
        <p className="status-card__success">✅ '{outcome.data.site_name}' 등록 완료</p>
      )}
      {outcome?.kind === 'validation' && <p className="status-card__error">⚠ {outcome.message}</p>}
      {outcome?.kind === 'busy' && <p className="status-card__error">⚠ {outcome.message}</p>}
      {outcome?.kind === 'error' && <p className="status-card__error">⚠ {outcome.message}</p>}
    </form>
  )
}

function SiteImportPanel({ isAdmin, onImported }) {
  const [fileText, setFileText] = useState(null)
  const [fileName, setFileName] = useState('')
  const [running, setRunning] = useState(false)
  const [outcome, setOutcome] = useState(null)

  const handleFile = (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setFileName(file.name)
    const reader = new FileReader()
    reader.onload = () => setFileText(reader.result)
    reader.readAsText(file)
  }

  const handleImport = () => {
    if (running || !fileText) return
    setRunning(true)
    setOutcome(null)
    let rows
    try {
      rows = JSON.parse(fileText)
      if (!Array.isArray(rows)) throw new Error('JSON 배열이어야 합니다')
    } catch (e) {
      setRunning(false)
      setOutcome({ kind: 'error', message: `JSON 파싱 실패: ${e.message}` })
      return
    }
    postImportSites(rows).then((res) => {
      setRunning(false)
      if (res?.success) {
        setOutcome({ kind: 'success', data: res.data })
        onImported()
      } else {
        setOutcome({ kind: 'error', message: res?.error?.message || 'Import 요청 실패' })
      }
    })
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">⬆️ Import(JSON)</h3>
      <p className="status-card__hint">검증 경유 신규 등록만 — WP 자격증명은 Import로 복원되지 않습니다.</p>
      <div className="form-actions">
        <input type="file" accept="application/json" onChange={handleFile} disabled={running} />
        <button type="button" className="refresh-btn" disabled={!isAdmin || running || !fileText} onClick={handleImport}>
          {running ? 'Import 중...' : 'Import 실행'}
        </button>
      </div>
      {fileName && <p className="status-card__hint">선택된 파일: {fileName}</p>}
      {outcome?.kind === 'success' && (
        <>
          <p className="status-card__success">
            ✅ Import 완료 · 총 {outcome.data.total}건 / 성공 {outcome.data.success}건 / 실패 {outcome.data.failed}건
          </p>
          {(outcome.data.errors || []).length > 0 && (
            <ul className="log-list">
              {outcome.data.errors.map((e, i) => (
                <li className="log-list__item" key={i} style={{ overflowWrap: 'anywhere' }}>- {e}</li>
              ))}
            </ul>
          )}
        </>
      )}
      {outcome?.kind === 'error' && <p className="status-card__error">⚠ {outcome.message}</p>}
    </div>
  )
}

// CALCMATE-REMAINING-DASHBOARD-KEEP-MIGRATION-01: dashboard.py "⬇️ 사이트
// Export(JSON)"(1322-1327) 이관 — sites 원본 row를 sites_export.json으로 내려받는다
// (Import가 읽는 site_tags/wordpress_url 포함). WP 자격증명은 포함되지 않는다.
function SiteExportPanel({ isAdmin }) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState(null)

  const handleExport = () => {
    if (running) return
    setRunning(true)
    setError(null)
    getSitesExport().then((res) => {
      setRunning(false)
      if (!res?.success) {
        setError(res?.error?.message || 'Export 요청 실패')
        return
      }
      const json = JSON.stringify(res.data?.sites || [], null, 2)
      const url = URL.createObjectURL(new Blob([json], { type: 'application/json' }))
      const a = document.createElement('a')
      a.href = url
      a.download = 'sites_export.json'
      a.click()
      URL.revokeObjectURL(url)
    })
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">⬇️ Export(JSON)</h3>
      <p className="status-card__hint">WP 자격증명/시크릿은 포함되지 않습니다.</p>
      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || running} onClick={handleExport}>
          {running ? 'Export 중...' : '⬇️ 사이트 Export(JSON)'}
        </button>
      </div>
      {error && <p className="status-card__error">⚠ {error}</p>}
    </div>
  )
}

export default function SiteManagementPanel() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [isAdmin, setIsAdmin] = useState(false)
  const [expandedId, setExpandedId] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    getSites().then((res) => {
      setResult(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
  }, [])

  // STEP P2-07: Update/Override 저장 후 onSaved()가 이 목록을 재조회하는데,
  // 최초 조회 이후의 재조회(loading=true)까지 SiteList를 통째로 언마운트하면
  // 방금 펼친 SiteEditPanel(및 그 저장 성공 메시지)이 사라져버린다 — 이미
  // 한 번 데이터를 받은 뒤에는 재조회 중에도 기존 목록을 계속 표시한다.
  const initialLoading = loading && !result
  const failed = !loading && !result?.success
  const sites = result?.data?.sites || []

  return (
    <div className="status-card" style={{ gridColumn: '1 / -1' }}>
      <h3 className="status-card__title">🌐 사이트 관리</h3>
      <div className="form-actions">
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      {initialLoading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}
      {!failed && result && (
        <SiteList
          sites={sites}
          isAdmin={isAdmin}
          expandedId={expandedId}
          onToggle={(id) => setExpandedId(expandedId === id ? null : id)}
          onSaved={load}
        />
      )}

      <div className="card-grid">
        <SiteCreateForm isAdmin={isAdmin} onCreated={load} />
        <SiteImportPanel isAdmin={isAdmin} onImported={load} />
        <SiteExportPanel isAdmin={isAdmin} />
      </div>
    </div>
  )
}
