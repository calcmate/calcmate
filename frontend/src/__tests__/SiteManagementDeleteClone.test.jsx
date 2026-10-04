import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import SiteManagementPanel from '../components/SiteManagementPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-09: Site Management Hard Delete/Clone UI 검증. 실제 deleteSite/
// postCloneSite는 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상 mock.

const SITE = {
  site_id: 's1', site_name: '삭제복제사이트', domain: 'delclone.example.com', site_type: 'calculator',
  status: 'active', platforms: [], wordpress_configured: false,
}

function mockSites(sites) {
  vi.spyOn(apiClient, 'getSites').mockResolvedValue({
    success: true, data: { sites }, error: null, request_id: 'l0',
  })
}

beforeEach(() => {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
    success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1',
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

function cardFor(name) {
  return screen.getByText(name).closest('.status-card')
}

describe('Site delete control (STEP P2-09)', () => {
  it('keeps the delete-execute button disabled until "DELETE" is typed exactly', async () => {
    mockSites([SITE])
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('삭제복제사이트')).toBeInTheDocument())
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /⛔ 영구 삭제$/ }))
    const execBtn = card.getByRole('button', { name: /⛔ 영구 삭제 실행/ })
    expect(execBtn).toBeDisabled()

    fireEvent.change(card.getByPlaceholderText('DELETE'), { target: { value: 'delete' } })
    expect(execBtn).toBeDisabled()

    fireEvent.change(card.getByPlaceholderText('DELETE'), { target: { value: 'DELETE' } })
    expect(execBtn).toBeEnabled()
  })

  it('calls deleteSite with the confirmation text and shows success', async () => {
    mockSites([SITE])
    const spy = vi.spyOn(apiClient, 'deleteSite').mockResolvedValue({
      success: true, data: { site_id: 's1', deleted: true }, error: null, request_id: 'd1',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('삭제복제사이트')).toBeInTheDocument())
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /⛔ 영구 삭제$/ }))
    fireEvent.change(card.getByPlaceholderText('DELETE'), { target: { value: 'DELETE' } })
    fireEvent.click(card.getByRole('button', { name: /⛔ 영구 삭제 실행/ }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('s1', 'DELETE'))
    await waitFor(() => expect(within(cardFor('삭제복제사이트')).getByText(/영구 삭제되었습니다/)).toBeInTheDocument())
  })

  it('shows an error message when delete fails', async () => {
    mockSites([SITE])
    vi.spyOn(apiClient, 'deleteSite').mockResolvedValue({
      success: false, data: null, error: { code: 'NOT_FOUND', message: '사이트를 찾을 수 없습니다' }, request_id: null,
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('삭제복제사이트')).toBeInTheDocument())
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /⛔ 영구 삭제$/ }))
    fireEvent.change(card.getByPlaceholderText('DELETE'), { target: { value: 'DELETE' } })
    fireEvent.click(card.getByRole('button', { name: /⛔ 영구 삭제 실행/ }))
    await waitFor(() => expect(within(cardFor('삭제복제사이트')).getByText(/사이트를 찾을 수 없습니다/)).toBeInTheDocument())
  })

  it('disables the delete-execute button for a non-admin viewer even with correct confirmation', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
      success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2',
    })
    mockSites([SITE])
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('삭제복제사이트')).toBeInTheDocument())
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /⛔ 영구 삭제$/ }))
    fireEvent.change(card.getByPlaceholderText('DELETE'), { target: { value: 'DELETE' } })
    expect(card.getByRole('button', { name: /⛔ 영구 삭제 실행/ })).toBeDisabled()
  })

  it('re-fetches the site list after a successful delete', async () => {
    mockSites([SITE])
    vi.spyOn(apiClient, 'deleteSite').mockResolvedValue({
      success: true, data: { site_id: 's1', deleted: true }, error: null, request_id: 'd2',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(apiClient.getSites).toHaveBeenCalledTimes(1))
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /⛔ 영구 삭제$/ }))
    fireEvent.change(card.getByPlaceholderText('DELETE'), { target: { value: 'DELETE' } })
    fireEvent.click(card.getByRole('button', { name: /⛔ 영구 삭제 실행/ }))
    await waitFor(() => expect(apiClient.getSites).toHaveBeenCalledTimes(2))
  })
})

describe('Site clone form (STEP P2-09)', () => {
  it('pre-fills the new site name with "(복사본)" suffix and leaves domain/WP fields blank', async () => {
    mockSites([SITE])
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('삭제복제사이트')).toBeInTheDocument())
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /📑 복제$/ }))
    expect(card.getByLabelText('새 사이트명')).toHaveValue('삭제복제사이트 (복사본)')
    expect(card.getByLabelText('새 도메인')).toHaveValue('')
    expect(card.getByLabelText('WordPress URL')).toHaveValue('')
    expect(card.getByLabelText('App Password')).toHaveValue('')
  })

  it('submits the clone form and calls postCloneSite with the entered fields', async () => {
    mockSites([SITE])
    const spy = vi.spyOn(apiClient, 'postCloneSite').mockResolvedValue({
      success: true,
      data: { site_id: 's2', site_name: '삭제복제사이트 (복사본)', domain: 'clone.example.com',
               site_type: 'calculator', status: 'active', platforms: [], wordpress_configured: false },
      error: null, request_id: 'c1',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('삭제복제사이트')).toBeInTheDocument())
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /📑 복제$/ }))
    fireEvent.change(card.getByLabelText('새 도메인'), { target: { value: 'clone.example.com' } })
    fireEvent.click(card.getByRole('button', { name: /📑 복제 실행/ }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('s1', expect.objectContaining({
      site_name: '삭제복제사이트 (복사본)', domain: 'clone.example.com',
    })))
    await waitFor(() => expect(within(cardFor('삭제복제사이트')).getByText(/복제 완료/)).toBeInTheDocument())
  })

  it('never displays the entered WordPress password back to the user after submit', async () => {
    mockSites([SITE])
    vi.spyOn(apiClient, 'postCloneSite').mockResolvedValue({
      success: true,
      data: { site_id: 's3', site_name: '복제됨', domain: 'wp-clone.example.com',
               site_type: 'custom', status: 'active', platforms: [], wordpress_configured: true },
      error: null, request_id: 'c2',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('삭제복제사이트')).toBeInTheDocument())
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /📑 복제$/ }))
    fireEvent.change(card.getByLabelText('새 도메인'), { target: { value: 'wp-clone.example.com' } })
    fireEvent.change(card.getByLabelText('App Password'), { target: { value: 'clone-secret-pw' } })
    fireEvent.click(card.getByRole('button', { name: /📑 복제 실행/ }))
    await waitFor(() => expect(within(cardFor('삭제복제사이트')).getByText(/복제 완료/)).toBeInTheDocument())
    expect(screen.queryByText(/clone-secret-pw/)).not.toBeInTheDocument()
    expect(within(cardFor('삭제복제사이트')).getByLabelText('App Password')).toHaveValue('')
  })

  it('shows a validation error message from the API (e.g. duplicate domain)', async () => {
    mockSites([SITE])
    vi.spyOn(apiClient, 'postCloneSite').mockResolvedValue({
      success: false, data: null,
      error: { code: 'VALIDATION_ERROR', message: "중복 도메인: 'clone.example.com' 이미 등록됨" },
      request_id: null,
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('삭제복제사이트')).toBeInTheDocument())
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /📑 복제$/ }))
    fireEvent.change(card.getByLabelText('새 도메인'), { target: { value: 'clone.example.com' } })
    fireEvent.click(card.getByRole('button', { name: /📑 복제 실행/ }))
    await waitFor(() => expect(within(cardFor('삭제복제사이트')).getByText(/중복 도메인/)).toBeInTheDocument())
  })

  it('disables the clone-execute button for a non-admin viewer', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
      success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2',
    })
    mockSites([SITE])
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('삭제복제사이트')).toBeInTheDocument())
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /📑 복제$/ }))
    expect(card.getByRole('button', { name: /📑 복제 실행/ })).toBeDisabled()
  })

  it('re-fetches the site list after a successful clone', async () => {
    mockSites([SITE])
    vi.spyOn(apiClient, 'postCloneSite').mockResolvedValue({
      success: true,
      data: { site_id: 's4', site_name: '복제됨2', domain: 'clone2.example.com',
               site_type: 'calculator', status: 'active', platforms: [], wordpress_configured: false },
      error: null, request_id: 'c3',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(apiClient.getSites).toHaveBeenCalledTimes(1))
    const card = within(cardFor('삭제복제사이트'))
    fireEvent.click(card.getByRole('button', { name: /📑 복제$/ }))
    fireEvent.change(card.getByLabelText('새 도메인'), { target: { value: 'clone2.example.com' } })
    fireEvent.click(card.getByRole('button', { name: /📑 복제 실행/ }))
    await waitFor(() => expect(apiClient.getSites).toHaveBeenCalledTimes(2))
  })
})
