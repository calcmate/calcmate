import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import SiteManagementPanel from '../components/SiteManagementPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-06: Site Management Create/Import UI 검증. 실제 postCreateSite/
// postImportSites는 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상 mock.

beforeEach(() => {
  vi.spyOn(apiClient, 'getSites').mockResolvedValue({
    success: true, data: { sites: [] }, error: null, request_id: 'l0',
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

function mockAdmin() {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
    success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1',
  })
}

function mockViewer() {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
    success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2',
  })
}

describe('Site Create form (STEP P2-06)', () => {
  it('renders the create form fields', async () => {
    mockAdmin()
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('➕ 사이트 추가')).toBeInTheDocument())
    expect(screen.getByText('사이트 이름')).toBeInTheDocument()
    expect(screen.getByText('도메인')).toBeInTheDocument()
  })

  it('disables the submit button for a non-admin viewer', async () => {
    mockViewer()
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /사이트 등록/ })).toBeDisabled())
  })

  it('submits the form and calls postCreateSite with the entered fields', async () => {
    mockAdmin()
    const spy = vi.spyOn(apiClient, 'postCreateSite').mockResolvedValue({
      success: true,
      data: { site_id: 's1', site_name: '새사이트', domain: 'new.example.com', site_type: 'calculator',
               status: 'active', platforms: [], wordpress_configured: false },
      error: null, request_id: 'c1',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /사이트 등록/ })).toBeEnabled())

    fireEvent.change(screen.getByLabelText('사이트 이름'), { target: { value: '새사이트' } })
    fireEvent.change(screen.getByLabelText('도메인'), { target: { value: 'new.example.com' } })
    fireEvent.click(screen.getByRole('button', { name: /사이트 등록/ }))

    await waitFor(() => expect(spy).toHaveBeenCalledWith(expect.objectContaining({
      type_label: '계산기', site_name: '새사이트', domain: 'new.example.com',
    })))
    await waitFor(() => expect(screen.getByText(/등록 완료/)).toBeInTheDocument())
  })

  it('shows the WordPress credential fields only when the WordPress checkbox is checked', async () => {
    mockAdmin()
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /사이트 등록/ })).toBeEnabled())
    expect(screen.queryByLabelText('WordPress URL')).not.toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('WordPress'))
    expect(screen.getByLabelText('WordPress URL')).toBeInTheDocument()
    expect(screen.getByLabelText('App Password')).toHaveAttribute('type', 'password')
  })

  it('shows a validation error message from the API (e.g. duplicate domain)', async () => {
    mockAdmin()
    vi.spyOn(apiClient, 'postCreateSite').mockResolvedValue({
      success: false, data: null,
      error: { code: 'VALIDATION_ERROR', message: "중복 도메인: 'new.example.com' 이미 등록됨" },
      request_id: null,
    })
    render(<SiteManagementPanel />)
    fireEvent.change(await screen.findByLabelText('사이트 이름'), { target: { value: 'x' } })
    fireEvent.change(screen.getByLabelText('도메인'), { target: { value: 'new.example.com' } })
    fireEvent.click(screen.getByRole('button', { name: /사이트 등록/ }))
    await waitFor(() => expect(screen.getByText(/중복 도메인/)).toBeInTheDocument())
  })

  it('never displays the entered WordPress password back to the user after submit', async () => {
    mockAdmin()
    vi.spyOn(apiClient, 'postCreateSite').mockResolvedValue({
      success: true,
      data: { site_id: 's2', site_name: 'wp사이트', domain: 'wp.example.com', site_type: 'custom',
               status: 'active', platforms: ['WordPress'], wordpress_configured: true },
      error: null, request_id: 'c2',
    })
    render(<SiteManagementPanel />)
    fireEvent.click(await screen.findByLabelText('WordPress'))
    fireEvent.change(screen.getByLabelText('사이트 이름'), { target: { value: 'wp사이트' } })
    fireEvent.change(screen.getByLabelText('도메인'), { target: { value: 'wp.example.com' } })
    fireEvent.change(screen.getByLabelText('App Password'), { target: { value: 'my-secret-pw-123' } })
    fireEvent.click(screen.getByRole('button', { name: /사이트 등록/ }))
    await waitFor(() => expect(screen.getByText(/등록 완료/)).toBeInTheDocument())
    expect(screen.queryByText(/my-secret-pw-123/)).not.toBeInTheDocument()
    // 비밀번호 입력창 자체도 제출 후 비워져야 한다.
    expect(screen.getByLabelText('App Password')).toHaveValue('')
  })

  it('calls getSites again after a successful create', async () => {
    mockAdmin()
    const listSpy = vi.spyOn(apiClient, 'getSites').mockResolvedValue({
      success: true, data: { sites: [] }, error: null, request_id: 'l1',
    })
    vi.spyOn(apiClient, 'postCreateSite').mockResolvedValue({
      success: true,
      data: { site_id: 's3', site_name: 'x', domain: 'x.com', site_type: 'calculator',
               status: 'active', platforms: [], wordpress_configured: false },
      error: null, request_id: 'c3',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(1))
    fireEvent.change(screen.getByLabelText('사이트 이름'), { target: { value: 'x' } })
    fireEvent.change(screen.getByLabelText('도메인'), { target: { value: 'x.com' } })
    fireEvent.click(screen.getByRole('button', { name: /사이트 등록/ }))
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(2))
  })
})

describe('Site Import panel (STEP P2-06)', () => {
  it('renders the import section', async () => {
    mockAdmin()
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('⬆️ Import(JSON)')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Import 실행/ })).toBeDisabled() // 파일 미선택 상태
  })

  it('disables Import execution until a file is chosen', async () => {
    mockAdmin()
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /Import 실행/ })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Import 실행/ })).toBeDisabled()
  })

  it('shows the import result summary after running', async () => {
    mockAdmin()
    const spy = vi.spyOn(apiClient, 'postImportSites').mockResolvedValue({
      success: true,
      data: { total: 3, success: 2, failed: 1, errors: ["중복 사이트명: '성공1' 이미 등록됨"] },
      error: null, request_id: 'i1',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(document.querySelector('input[type="file"]')).toBeInTheDocument())
    const input = document.querySelector('input[type="file"]')
    const file = new File([JSON.stringify([{ site_name: 'a', domain: 'a.com' }])], 'sites.json', { type: 'application/json' })
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => expect(screen.getByRole('button', { name: /Import 실행/ })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /Import 실행/ }))

    await waitFor(() => expect(spy).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText(/총 3건 \/ 성공 2건 \/ 실패 1건/)).toBeInTheDocument())
    expect(screen.getByText(/중복 사이트명/)).toBeInTheDocument()
  })
})
