import { useEffect, useState } from 'react'
import { getCurrentUser, postSitePagesPreview, postSitePagesSave, postSitePagesDeploy } from '../api/client.js'

// 🌐 사이트 페이지 배포 — SITE-PAGE-DEPLOYMENT-02: dashboard.py "🌐 사이트 페이지 배포"
// (계산기 관리 탭 하단, L1881-1930) 이관. 전역 설정(SITE_URL/SITE_NAME) 기준으로
// 메인 홈·소개·개인정보처리방침·이용약관·문의하기 등 9개 공통 파일을 만든다(현재 Site와 무관).
// 배포는 서버가 로컬 Git으로 9개 파일만 1회 commit하고 원격과 동기화돼 있을 때만 push한다
// (GitHub Actions가 Pages에 반영). 원본의 파일별 GitHub Contents API 업로드는 쓰지 않는다.
const SITE_PAGE_FILES = [
  'index.html', 'site.css', 'about/index.html', 'privacy/index.html', 'terms/index.html',
  'contact/index.html', '404.html', 'sitemap.xml', 'robots.txt',
]

function errorText(res, fallback) {
  if (res?.error?.message) return res.error.message
  if (res?.detail) return typeof res.detail === 'string' ? res.detail : '요청이 거부되었습니다.'
  return fallback
}

export default function SitePagesDeployPanel() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [busy, setBusy] = useState(null)            // 'preview' | 'save' | 'deploy' | null
  const [preview, setPreview] = useState(null)      // {count, site_url, pages}
  const [selected, setSelected] = useState('index.html')
  const [notice, setNotice] = useState(null)        // {kind: 'success'|'error'|'info', text, extra}

  useEffect(() => {
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
  }, [])

  async function run(kind, fn) {
    if (busy) return
    setBusy(kind)
    setNotice(null)
    try {
      return await fn()
    } finally {
      setBusy(null)
    }
  }

  const handlePreview = () => run('preview', async () => {
    const res = await postSitePagesPreview()
    if (res?.success) {
      setPreview(res.data)
      if (!res.data.pages.some((p) => p.path === selected)) setSelected(res.data.pages[0]?.path || null)
    } else {
      setNotice({ kind: 'error', text: `미리보기 실패: ${errorText(res, '요청 실패')}` })
    }
  })

  const handleSave = () => run('save', async () => {
    const res = await postSitePagesSave()
    if (res?.success && res.data?.ok) {
      setNotice({ kind: 'success', text: `✅ ${res.data.target} 에 ${res.data.count}개 파일 저장(Git commit/push 없음)` })
    } else if (res?.success) {
      setNotice({ kind: 'error', text: `일부 파일 저장 실패: ${(res.data.failed || []).map((f) => f.path).join(', ')}` })
    } else {
      setNotice({ kind: 'error', text: `로컬 저장 실패: ${errorText(res, '요청 실패')}` })
    }
  })

  const handleDeploy = () => run('deploy', async () => {
    const res = await postSitePagesDeploy()
    if (!res?.success) {
      const busyText = res?.error?.code === 'LOCK_CONFLICT' ? '다른 배포가 진행 중입니다 — ' : ''
      setNotice({ kind: 'error', text: `배포하지 않음 — ${busyText}${errorText(res, '요청 실패')}` })
      return
    }
    const d = res.data
    if (d.ok && d.pushed) {
      setNotice({ kind: 'success', text: `✅ 사이트 페이지 배포 완료 — ${d.files.length}개 파일 · commit ${String(d.commit || '').slice(0, 7)} → ${d.pages_url}` })
    } else if (d.ok) {
      setNotice({ kind: 'info', text: `ℹ ${d.message}` })
    } else {
      setNotice({ kind: 'error', text: `배포하지 않음 — ${d.message}` })
    }
  })

  const current = preview?.pages?.find((p) => p.path === selected)
  const htmlPages = (preview?.pages || []).filter((p) => !p.path.endsWith('.css'))
  const isHtml = selected && selected.endsWith('.html')

  return (
    <div className="status-card" data-testid="site-pages-deploy-panel">
      <h3 className="status-card__title">🌐 사이트 페이지 배포</h3>
      <p className="status-card__hint">
        메인 홈 + 소개 / 개인정보처리방침 / 이용약관 / 문의하기 페이지(전역 설정 기준)를 생성해 미리보고,
        로컬에 저장하거나 GitHub Pages에 배포합니다.
      </p>
      <ul className="today-list" aria-label="사이트 페이지 목록">
        {SITE_PAGE_FILES.map((p) => <li key={p}>{p}</li>)}
      </ul>

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || Boolean(busy)} onClick={handlePreview}>
          {busy === 'preview' ? '생성 중...' : '페이지 미리보기'}
        </button>
        <button type="button" className="refresh-btn" disabled={!isAdmin || Boolean(busy)} onClick={handleSave}>
          {busy === 'save' ? '저장 중...' : '💾 로컬 저장'}
        </button>
        <button type="button" className="refresh-btn" disabled={!isAdmin || Boolean(busy)} onClick={handleDeploy}>
          {busy === 'deploy' ? '배포 중...' : '🚀 사이트 페이지 배포'}
        </button>
      </div>

      {notice && (
        <p className={notice.kind === 'success' ? 'status-card__success' : notice.kind === 'info' ? 'status-card__hint' : 'status-card__error'}>
          {notice.text}
        </p>
      )}

      {preview && (
        <div data-testid="site-pages-preview">
          <p className="status-card__hint">생성 {preview.count}개 · {preview.site_url}</p>
          <div className="form-row">
            <label className="form-label" htmlFor="site-page-select">페이지 선택</label>
            <select id="site-page-select" className="form-select" value={selected || ''}
                    onChange={(e) => setSelected(e.target.value)}>
              {htmlPages.map((p) => <option key={p.path} value={p.path}>{p.path}</option>)}
            </select>
          </div>
          {current && (isHtml
            ? <iframe title="사이트 페이지 미리보기" sandbox="allow-scripts" srcDoc={current.content}
                      style={{ width: '100%', height: 500, border: 0 }} />
            : <pre data-testid="site-page-text">{current.content}</pre>)}
        </div>
      )}
    </div>
  )
}
