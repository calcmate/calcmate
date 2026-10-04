import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import SiteManagementPanel from '../components/SiteManagementPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-04: Site Management 조회(READ-ONLY) React/FastAPI 이관 검증. 실제
// getSites는 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상 mock으로 대체.
// STEP P2-06: 컴포넌트가 getCurrentUser()도 호출하게 되어(➕ 사이트 추가/Import
// 폼의 admin 게이트), 모든 테스트에서 기본으로 admin으로 mock한다 — 실제
// Create/Import 폼 자체의 검증은 SiteManagementCreate.test.jsx에서 한다.

beforeEach(() => {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
    success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u0',
  })
})

const SITES = [
  {
    site_id: 'site_1', site_name: '테스트 사이트', domain: 'example.com',
    site_type: 'custom', status: 'active', platforms: ['WordPress', 'Calculator'],
    wordpress_configured: true,
  },
  {
    site_id: 'site_2', site_name: '비활성 사이트', domain: 'inactive.com',
    site_type: 'policy', status: 'inactive', platforms: [],
    wordpress_configured: false,
  },
]

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Site Management Panel (STEP P2-04)', () => {
  it('shows loading state initially', () => {
    vi.spyOn(apiClient, 'getSites').mockReturnValue(new Promise(() => {}))
    render(<SiteManagementPanel />)
    expect(screen.getByText(/불러오는 중/)).toBeInTheDocument()
  })

  it('renders site name, domain, and platform badges', async () => {
    vi.spyOn(apiClient, 'getSites').mockResolvedValue({
      success: true, data: { sites: SITES }, error: null, request_id: 's1',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('테스트 사이트')).toBeInTheDocument())
    expect(screen.getByText('example.com')).toBeInTheDocument()
    // "WordPress"는 배지와 STEP P2-06의 추가 폼 체크박스 라벨에도 나타나므로
    // getAllByText로 최소 1개 이상(배지) 존재하는지만 확인한다.
    expect(screen.getAllByText('WordPress').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Calculator').length).toBeGreaterThan(0)
    expect(screen.getByText(/WordPress 연동됨/)).toBeInTheDocument()
  })

  it('shows "Platform 미설정" and "미연동" for a site with no platforms', async () => {
    vi.spyOn(apiClient, 'getSites').mockResolvedValue({
      success: true, data: { sites: SITES }, error: null, request_id: 's2',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('비활성 사이트')).toBeInTheDocument())
    expect(screen.getByText(/Platform 미설정/)).toBeInTheDocument()
    expect(screen.getByText(/WordPress 미연동/)).toBeInTheDocument()
  })

  it('shows the empty state when there are no sites (matches current real environment)', async () => {
    vi.spyOn(apiClient, 'getSites').mockResolvedValue({
      success: true, data: { sites: [] }, error: null, request_id: 's3',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('등록된 사이트가 없습니다.')).toBeInTheDocument())
  })

  it('shows an error message on API failure', async () => {
    vi.spyOn(apiClient, 'getSites').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText(/API 연결 실패/)).toBeInTheDocument())
  })

  it('never renders raw secret-looking strings even if present in a malformed response', async () => {
    vi.spyOn(apiClient, 'getSites').mockResolvedValue({
      success: true,
      data: { sites: [{ ...SITES[0], wordpress_app_password: 'should-never-appear' }] },
      error: null, request_id: 's4',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('테스트 사이트')).toBeInTheDocument())
    expect(screen.queryByText(/should-never-appear/)).not.toBeInTheDocument()
  })

  it('calls getSites again on refresh click', async () => {
    const spy = vi.spyOn(apiClient, 'getSites').mockResolvedValue({
      success: true, data: { sites: SITES }, error: null, request_id: 's5',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    screen.getByRole('button', { name: /새로고침/ }).click()
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })
})
