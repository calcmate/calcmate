import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import SitePagesDeployPanel from '../components/SitePagesDeployPanel.jsx'
import * as apiClient from '../api/client.js'

// SITE-PAGE-DEPLOYMENT-02 — 사이트 페이지 배포 패널. 모든 client 호출은 mock이며 실제
// 생성/파일 저장/Git/GitHub 배포는 일어나지 않는다.
const ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }
const ok = (data) => ({ success: true, data, error: null, request_id: 'r' })
const fail = (code, message) => ({ success: false, data: null, error: { code, message }, request_id: 'r' })
const FILES = ['index.html', 'site.css', 'about/index.html', 'privacy/index.html', 'terms/index.html',
  'contact/index.html', '404.html', 'sitemap.xml', 'robots.txt']
const PREVIEW = ok({
  count: 9, site_url: 'https://calcmate.kr/',
  pages: FILES.map((p) => ({ path: p, content: p.endsWith('.html') ? `<h1>${p}</h1>` : `TEXT ${p}`, size: 10 })),
})

beforeEach(() => {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN)
})

afterEach(() => {
  vi.restoreAllMocks()
})

async function renderReady() {
  render(<SitePagesDeployPanel />)
  await waitFor(() => expect(screen.getByRole('button', { name: '페이지 미리보기' })).toBeEnabled())
}

describe('SitePagesDeployPanel', () => {
  it('renders the panel with the 9 site page files and 3 buttons', async () => {
    await renderReady()
    const items = Array.from(screen.getByRole('list', { name: '사이트 페이지 목록' }).querySelectorAll('li')).map((l) => l.textContent)
    expect(items).toEqual(FILES)
    expect(screen.getByRole('button', { name: /로컬 저장/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: /사이트 페이지 배포/ })).toBeEnabled()
  })

  it('viewer cannot use any action', async () => {
    apiClient.getCurrentUser.mockResolvedValue(VIEWER)
    const spy = vi.spyOn(apiClient, 'postSitePagesDeploy')
    render(<SitePagesDeployPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '페이지 미리보기' })).toBeDisabled())
    expect(screen.getByRole('button', { name: /사이트 페이지 배포/ })).toBeDisabled()
    expect(spy).not.toHaveBeenCalled()
  })

  it('preview loads pages, defaults to index, and selection switches the preview (css excluded)', async () => {
    const spy = vi.spyOn(apiClient, 'postSitePagesPreview').mockResolvedValue(PREVIEW)
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: '페이지 미리보기' }))
    expect(await screen.findByText('생성 9개 · https://calcmate.kr/')).toBeInTheDocument()
    expect(spy).toHaveBeenCalledTimes(1)
    const options = Array.from(screen.getByLabelText('페이지 선택').querySelectorAll('option')).map((o) => o.value)
    expect(options).not.toContain('site.css')
    expect(options).toHaveLength(8)
    expect(screen.getByTitle('사이트 페이지 미리보기')).toHaveAttribute('srcdoc', '<h1>index.html</h1>')
    fireEvent.change(screen.getByLabelText('페이지 선택'), { target: { value: 'about/index.html' } })
    expect(screen.getByTitle('사이트 페이지 미리보기')).toHaveAttribute('srcdoc', '<h1>about/index.html</h1>')
    fireEvent.change(screen.getByLabelText('페이지 선택'), { target: { value: 'robots.txt' } })
    expect(screen.getByTestId('site-page-text')).toHaveTextContent('TEXT robots.txt')
  })

  it('preview failure shows the server error', async () => {
    vi.spyOn(apiClient, 'postSitePagesPreview').mockResolvedValue(fail('SITE_PAGES_BUILD_FAILED', '사이트 페이지 생성 실패(RuntimeError)'))
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: '페이지 미리보기' }))
    expect(await screen.findByText(/미리보기 실패: 사이트 페이지 생성 실패/)).toBeInTheDocument()
  })

  it('local save shows saved count and target', async () => {
    vi.spyOn(apiClient, 'postSitePagesSave').mockResolvedValue(ok({ ok: true, count: 9, saved: FILES, failed: [], target: 'data/workspace/_site/' }))
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: /로컬 저장/ }))
    expect(await screen.findByText(/data\/workspace\/_site\/ 에 9개 파일 저장/)).toBeInTheDocument()
  })

  it('deploy shows loading, prevents duplicate clicks, then success with API-provided info', async () => {
    let resolve
    const spy = vi.spyOn(apiClient, 'postSitePagesDeploy').mockReturnValue(new Promise((r) => { resolve = r }))
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: /사이트 페이지 배포/ }))
    const loading = await screen.findByRole('button', { name: '배포 중...' })
    expect(loading).toBeDisabled()
    expect(screen.getByRole('button', { name: '페이지 미리보기' })).toBeDisabled()
    fireEvent.click(loading)
    fireEvent.click(loading)
    expect(spy).toHaveBeenCalledTimes(1)
    resolve(ok({ ok: true, pushed: true, committed: true, commit: 'abcdef1234567', files: FILES.map((f) => `data/workspace/_site/${f}`),
      message: '사이트 페이지 배포 완료', pages_url: 'https://calcmate.kr/' }))
    expect(await screen.findByText(/사이트 페이지 배포 완료 — 9개 파일 · commit abcdef1 → https:\/\/calcmate.kr\//)).toBeInTheDocument()
  })

  it('deploy blocked by the server shows "배포하지 않음" with the reason', async () => {
    vi.spyOn(apiClient, 'postSitePagesDeploy').mockResolvedValue(ok({ ok: false, pushed: false, committed: false,
      message: '배포 중단 — remote_diverged: state=behind', files: [], pages_url: 'https://calcmate.kr/' }))
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: /사이트 페이지 배포/ }))
    expect(await screen.findByText(/배포하지 않음 — 배포 중단 — remote_diverged: state=behind/)).toBeInTheDocument()
  })

  it('no-change deploy is shown as info', async () => {
    vi.spyOn(apiClient, 'postSitePagesDeploy').mockResolvedValue(ok({ ok: true, pushed: false, committed: false,
      message: '변경 없음 — 이미 배포된 사이트 페이지', files: [], pages_url: 'https://calcmate.kr/' }))
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: /사이트 페이지 배포/ }))
    expect(await screen.findByText(/변경 없음 — 이미 배포된 사이트 페이지/)).toBeInTheDocument()
  })

  it('lock conflict and 401/403 responses are shown as not deployed', async () => {
    vi.spyOn(apiClient, 'postSitePagesDeploy')
      .mockResolvedValueOnce(fail('LOCK_CONFLICT', 'wp_blog_deploy.lock 보유 중'))
      .mockResolvedValueOnce({ detail: 'Not authenticated' })
      .mockResolvedValueOnce({ detail: 'admin role required' })
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: /사이트 페이지 배포/ }))
    expect(await screen.findByText(/배포하지 않음 — 다른 배포가 진행 중입니다 — wp_blog_deploy.lock/)).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: /사이트 페이지 배포/ }))
    expect(await screen.findByText(/배포하지 않음 — Not authenticated/)).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: /사이트 페이지 배포/ }))
    expect(await screen.findByText(/배포하지 않음 — admin role required/)).toBeInTheDocument()
  })

  it('never renders credential-like values from the response', async () => {
    vi.spyOn(apiClient, 'postSitePagesDeploy').mockResolvedValue(ok({ ok: false, pushed: false, committed: false,
      message: 'GITHUB_TOKEN 미설정 — 배포 건너뜀', files: [], pages_url: 'https://calcmate.kr/' }))
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: /사이트 페이지 배포/ }))
    expect(await screen.findByText(/GITHUB_TOKEN 미설정/)).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/ghp_[A-Za-z0-9]+/)
  })
})
