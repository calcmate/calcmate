import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import IntegratedRunQuickActionPanel from '../components/IntegratedRunQuickActionPanel.jsx'
import CurrentSiteCard from '../components/CurrentSiteCard.jsx'
import { CurrentSiteProvider, useCurrentSiteSelection } from '../components/CurrentSiteContext.jsx'
import Dashboard from '../pages/Dashboard.jsx'
import { useState } from 'react'
import * as apiClient from '../api/client.js'

// STEP S13: Dashboard Quick Action 「▶ 실행」(통합 실행) React/FastAPI 이관
// 검증. 실제 postIntegratedRunOnce는 이 파일의 어떤 테스트에서도 호출하지
// 않는다 — 항상 mock으로 대체한다.

const ADMIN_USER = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER_USER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }

const BLOG_RESULT = { produced: 1, processed: 4, dup: 1, failed: 1, no_wp: 0, reason: 'ok' }

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Integrated Run Quick Action (STEP S13)', () => {
  it('renders the panel with a ▶ 실행 button', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    render(<IntegratedRunQuickActionPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /▶ 실행/ })).toBeInTheDocument())
  })

  it('disables the button for a viewer', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    render(<IntegratedRunQuickActionPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /▶ 실행/ })).toBeDisabled())
  })

  it('clicking the button shows loading, disables it, and prevents duplicate clicks', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const runSpy = vi.spyOn(apiClient, 'postIntegratedRunOnce').mockReturnValue(new Promise(() => {}))
    render(<IntegratedRunQuickActionPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /▶ 실행/ })).toBeEnabled())

    const btn = screen.getByRole('button', { name: /▶ 실행/ })
    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByRole('button', { name: /실행 중/ })).toBeDisabled())
    fireEvent.click(screen.getByRole('button', { name: /실행 중/ }))
    fireEvent.click(screen.getByRole('button', { name: /실행 중/ }))

    expect(runSpy).toHaveBeenCalledTimes(1)
  })

  it('calls postIntegratedRunOnce on click', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const runSpy = vi.spyOn(apiClient, 'postIntegratedRunOnce').mockResolvedValue({
      success: true, data: BLOG_RESULT, error: null, request_id: 'i1',
    })
    render(<IntegratedRunQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /▶ 실행/ }))
    await waitFor(() => expect(runSpy).toHaveBeenCalled())
  })

  it('shows the success message with produced count for a dict result (single-pipeline branch)', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postIntegratedRunOnce').mockResolvedValue({
      success: true, data: BLOG_RESULT, error: null, request_id: 'i2',
    })
    render(<IntegratedRunQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /▶ 실행/ }))
    await waitFor(() => expect(screen.getByText(/실행 요청 완료/)).toBeInTheDocument())
    expect(screen.getByText(/생산 1건/)).toBeInTheDocument()
  })

  it('shows the fixed string message for a string result (sequential branch)', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postIntegratedRunOnce').mockResolvedValue({
      success: true, data: '계산기→블로그 순차 완료', error: null, request_id: 'i3',
    })
    render(<IntegratedRunQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /▶ 실행/ }))
    await waitFor(() => expect(screen.getByText(/계산기→블로그 순차 완료/)).toBeInTheDocument())
  })

  it('shows an info (not success) message when produced=0', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postIntegratedRunOnce').mockResolvedValue({
      success: true,
      data: { produced: 0, reason: 'no_items' },
      error: null, request_id: 'i4',
    })
    render(<IntegratedRunQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /▶ 실행/ }))
    await waitFor(() => expect(screen.getByText(/생산 0건/)).toBeInTheDocument())
    expect(screen.getByText(/수집된 항목 없음/)).toBeInTheDocument()
  })

  it('shows a busy message on LOCK_CONFLICT', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postIntegratedRunOnce').mockResolvedValue({
      success: false, data: null,
      error: { code: 'LOCK_CONFLICT', message: '다른 계산기 생성 실행이 진행 중입니다. 잠시 후 재시도하세요.' },
      request_id: null,
    })
    render(<IntegratedRunQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /▶ 실행/ }))
    await waitFor(() => expect(screen.getByText(/다른 계산기 생성 실행이 진행 중입니다/)).toBeInTheDocument())
  })

  it('shows a generic error message on network/server failure', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postIntegratedRunOnce').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<IntegratedRunQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /▶ 실행/ }))
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument())
  })
})

// ══════════════════════════════════════════════════════════════════════════
// CURRENT-SITE-02: 현재 Site(dashboard.py current_site_id) — 첫 번째 Site 기본,
// 선택 변경, 상태 무관 선택, site_id 전달, 목록 변경 시 교정. 저장하지 않는다.
// ══════════════════════════════════════════════════════════════════════════
const SITES = [
  { site_id: 'site-A', site_name: 'Site A', status: 'active', platforms: ['Calculator'] },
  { site_id: 'site-B', site_name: 'Site B', status: 'inactive', platforms: ['WordPress', 'Calculator'] },
  { site_id: 'site-C', site_name: 'Site C', status: 'archived', platforms: [] },
]
const sitesRes = (sites) => ({ success: true, data: { sites }, error: null, request_id: 's' })

function SiteHarness() {
  const sel = useCurrentSiteSelection()
  return (
    <div>
      <CurrentSiteCard sites={sel.sites} currentSite={sel.currentSite} currentSiteId={sel.currentSiteId}
                       onChange={sel.setCurrentSiteId} error={sel.error} />
      <IntegratedRunQuickActionPanel site={sel.currentSite} />
    </div>
  )
}

function App({ initiallyShown = true }) {
  const [shown, setShown] = useState(initiallyShown)
  return (
    <CurrentSiteProvider>
      <button type="button" onClick={() => setShown((v) => !v)}>toggle-home</button>
      {shown && <SiteHarness />}
    </CurrentSiteProvider>
  )
}

function mockBase(sites = SITES) {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
  vi.spyOn(apiClient, 'getGeneralSettings').mockResolvedValue({ success: true, data: { WORDPRESS_URL: 'https://wp.test', TELEGRAM_BOT_TOKEN: { configured: true }, TELEGRAM_CHAT_ID: { configured: true } } })
  vi.spyOn(apiClient, 'getOperationsSettings').mockResolvedValue({ success: true, data: { ENABLE_STRATEGY_ROOM: true } })
  vi.spyOn(apiClient, 'getCalculators').mockResolvedValue({ success: true, data: { calculators: [{ slug: 'x' }] } })
  return vi.spyOn(apiClient, 'getSites').mockResolvedValue(sitesRes(sites))
}

describe('Current Site (CURRENT-SITE-02)', () => {
  it('A: 첫 번째 Site가 기본 선택된다(정렬하지 않음)', async () => {
    mockBase([SITES[2], SITES[0], SITES[1]])
    render(<App />)
    expect(await screen.findByText('🏢 현재 Site: Site C')).toBeInTheDocument()
    expect(screen.getByLabelText('Site 변경')).toHaveValue('site-C')
  })

  it('B/C: Site 변경 시 현재 Site와 실행 대상/Platform 표시가 바뀐다', async () => {
    mockBase()
    render(<App />)
    expect(await screen.findByText('🏢 현재 Site: Site A')).toBeInTheDocument()
    expect(screen.getByTestId('integrated-run-target')).toHaveTextContent('대상: Site A · Platform: Calculator')
    fireEvent.change(screen.getByLabelText('Site 변경'), { target: { value: 'site-B' } })
    expect(await screen.findByText('🏢 현재 Site: Site B')).toBeInTheDocument()
    expect(screen.getByTestId('integrated-run-target')).toHaveTextContent('대상: Site B · Platform: WordPress + Calculator')
    // WP+Calc → 실행 방식 선택 표시(dashboard.py qa_order)
    expect(screen.getByRole('radiogroup', { name: '실행 방식' })).toBeInTheDocument()
  })

  it('카드는 원본처럼 설정 기준 Platform/활성 Feature를 표시한다', async () => {
    mockBase()
    render(<App />)
    expect(await screen.findByText((_, el) => el?.tagName === 'P' && /^Platform: WordPress\s+\+\s+Calculator$/.test(el.textContent))).toBeInTheDocument()
    expect(screen.getByText('활성 Feature: Scheduler / AI Assistant / Cost Manager / Retry Queue / Telegram / Strategy')).toBeInTheDocument()
  })

  it('D: 통합 실행 요청에 선택 site_id(와 실행 방식)가 전달된다', async () => {
    mockBase()
    const runSpy = vi.spyOn(apiClient, 'postIntegratedRunOnce').mockResolvedValue({ success: true, data: '계산기→블로그 순차 완료', error: null, request_id: 'r' })
    render(<App />)
    await screen.findByText('🏢 현재 Site: Site A')
    await waitFor(() => expect(screen.getByRole('button', { name: /▶ 실행/ })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /▶ 실행/ }))
    await waitFor(() => expect(runSpy).toHaveBeenCalledWith(undefined, 'site-A'))
    fireEvent.change(screen.getByLabelText('Site 변경'), { target: { value: 'site-B' } })
    fireEvent.click(await screen.findByLabelText('WordPress만'))
    fireEvent.click(screen.getByRole('button', { name: /▶ 실행/ }))
    await waitFor(() => expect(runSpy).toHaveBeenLastCalledWith('WordPress만', 'site-B'))
  })

  it('E: inactive/archived Site도 목록에 있고 선택할 수 있다', async () => {
    mockBase()
    render(<App />)
    await screen.findByText('🏢 현재 Site: Site A')
    const options = Array.from(screen.getByLabelText('Site 변경').querySelectorAll('option')).map((o) => o.textContent)
    expect(options).toEqual(['Site A', 'Site B (inactive)', 'Site C (archived)'])
    fireEvent.change(screen.getByLabelText('Site 변경'), { target: { value: 'site-C' } })
    expect(await screen.findByText('🏢 현재 Site: Site C')).toBeInTheDocument()
    expect(screen.getByTestId('integrated-run-target')).toHaveTextContent('Platform 미설정 → 기본 블로그 파이프라인 실행')
  })

  it('F: Site 목록이 비면 기본 사이트로 표시되고 site_id 없이 실행한다', async () => {
    mockBase([])
    const runSpy = vi.spyOn(apiClient, 'postIntegratedRunOnce').mockResolvedValue({ success: true, data: BLOG_RESULT, error: null, request_id: 'r' })
    render(<App />)
    expect(await screen.findByText('등록 사이트 없음 — 기본 사이트')).toBeInTheDocument()
    expect(screen.getByText('🏢 현재 Site: CalcMate')).toBeInTheDocument()
    expect(screen.queryByLabelText('Site 변경')).not.toBeInTheDocument()
    expect(screen.getByTestId('integrated-run-target')).toHaveTextContent('대상: 기본(CalcMate)')
    await waitFor(() => expect(screen.getByRole('button', { name: /▶ 실행/ })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /▶ 실행/ }))
    await waitFor(() => expect(runSpy).toHaveBeenCalledWith(undefined, undefined))
  })

  it('선택은 화면 이동(언마운트/재마운트) 동안 유지되고 저장소에는 쓰지 않는다', async () => {
    mockBase()
    const setItem = vi.spyOn(Storage.prototype, 'setItem')
    render(<App />)
    await screen.findByText('🏢 현재 Site: Site A')
    fireEvent.change(screen.getByLabelText('Site 변경'), { target: { value: 'site-B' } })
    await screen.findByText('🏢 현재 Site: Site B')
    fireEvent.click(screen.getByRole('button', { name: 'toggle-home' }))
    fireEvent.click(screen.getByRole('button', { name: 'toggle-home' }))
    expect(await screen.findByText('🏢 현재 Site: Site B')).toBeInTheDocument()
    expect(setItem).not.toHaveBeenCalled()
  })

  it('G: 선택한 Site가 목록에서 사라지면 현재 목록의 첫 번째 Site로 교정된다', async () => {
    const getSitesSpy = mockBase()
    render(<App />)
    await screen.findByText('🏢 현재 Site: Site A')
    fireEvent.change(screen.getByLabelText('Site 변경'), { target: { value: 'site-B' } })
    await screen.findByText('🏢 현재 Site: Site B')
    getSitesSpy.mockResolvedValue(sitesRes([SITES[2], SITES[0]]))     // site-B 삭제됨
    fireEvent.click(screen.getByRole('button', { name: 'toggle-home' }))
    fireEvent.click(screen.getByRole('button', { name: 'toggle-home' }))
    expect(await screen.findByText('🏢 현재 Site: Site C')).toBeInTheDocument()
    expect(screen.getByLabelText('Site 변경')).toHaveValue('site-C')
  })

  it('실제 Dashboard 화면에 현재 Site 카드가 있고 통합 실행 패널에 대상이 표시된다', async () => {
    mockBase()
    render(<CurrentSiteProvider><Dashboard /></CurrentSiteProvider>)
    expect(await screen.findByTestId('current-site-card')).toBeInTheDocument()
    expect(await screen.findByText('🏢 현재 Site: Site A')).toBeInTheDocument()
    expect(screen.getByTestId('integrated-run-target')).toHaveTextContent('대상: Site A')
  })
})
