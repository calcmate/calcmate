import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import SiteManagementPanel from '../components/SiteManagementPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-08: Site Management Activate/Deactivate/Archive/Restore UI 검증.
// 실제 postActivateSite/postDeactivateSite/postArchiveSite/postRestoreSite는
// 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상 mock.

const ACTIVE_SITE = {
  site_id: 's1', site_name: '활성사이트', domain: 'active.example.com', site_type: 'calculator',
  status: 'active', platforms: [], wordpress_configured: false,
}
const INACTIVE_SITE = { ...ACTIVE_SITE, site_id: 's2', site_name: '비활성사이트', status: 'inactive' }
const ARCHIVED_SITE = { ...ACTIVE_SITE, site_id: 's3', site_name: '보관사이트', status: 'archived' }

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

describe('Site status controls (STEP P2-08)', () => {
  it('shows deactivate + archive buttons for an active site (no restore)', async () => {
    mockSites([ACTIVE_SITE])
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('활성사이트')).toBeInTheDocument())
    const card = within(cardFor('활성사이트'))
    expect(card.getByRole('button', { name: /⏸ 비활성화/ })).toBeInTheDocument()
    expect(card.getByRole('button', { name: /🗑️ 보관/ })).toBeInTheDocument()
    expect(card.queryByRole('button', { name: /♻️ 복원/ })).not.toBeInTheDocument()
  })

  it('shows activate + archive buttons for an inactive site', async () => {
    mockSites([INACTIVE_SITE])
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('비활성사이트')).toBeInTheDocument())
    const card = within(cardFor('비활성사이트'))
    expect(card.getByRole('button', { name: /▶ 활성화/ })).toBeInTheDocument()
    expect(card.getByRole('button', { name: /🗑️ 보관/ })).toBeInTheDocument()
  })

  it('shows only the restore button for an archived site (no activate/deactivate/archive)', async () => {
    mockSites([ARCHIVED_SITE])
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('보관사이트')).toBeInTheDocument())
    const card = within(cardFor('보관사이트'))
    expect(card.getByRole('button', { name: /♻️ 복원/ })).toBeInTheDocument()
    expect(card.queryByRole('button', { name: /활성화/ })).not.toBeInTheDocument()
    expect(card.queryByRole('button', { name: /보관/ })).not.toBeInTheDocument()
  })

  it('calls postDeactivateSite and shows success on click', async () => {
    mockSites([ACTIVE_SITE])
    const spy = vi.spyOn(apiClient, 'postDeactivateSite').mockResolvedValue({
      success: true, data: { ...ACTIVE_SITE, status: 'inactive' }, error: null, request_id: 'd1',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('활성사이트')).toBeInTheDocument())
    const card = within(cardFor('활성사이트'))
    fireEvent.click(card.getByRole('button', { name: /⏸ 비활성화/ }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('s1'))
    await waitFor(() => expect(within(cardFor('활성사이트')).getByText(/비활성화되었습니다/)).toBeInTheDocument())
  })

  it('calls postActivateSite and shows success on click', async () => {
    mockSites([INACTIVE_SITE])
    const spy = vi.spyOn(apiClient, 'postActivateSite').mockResolvedValue({
      success: true, data: { ...INACTIVE_SITE, status: 'active' }, error: null, request_id: 'a1',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('비활성사이트')).toBeInTheDocument())
    fireEvent.click(within(cardFor('비활성사이트')).getByRole('button', { name: /▶ 활성화/ }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('s2'))
  })

  it('calls postArchiveSite and shows success on click', async () => {
    mockSites([ACTIVE_SITE])
    const spy = vi.spyOn(apiClient, 'postArchiveSite').mockResolvedValue({
      success: true, data: { ...ACTIVE_SITE, status: 'archived' }, error: null, request_id: 'ar1',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('활성사이트')).toBeInTheDocument())
    fireEvent.click(within(cardFor('활성사이트')).getByRole('button', { name: /🗑️ 보관/ }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('s1'))
    await waitFor(() => expect(within(cardFor('활성사이트')).getByText(/보관되었습니다/)).toBeInTheDocument())
  })

  it('calls postRestoreSite and shows success on click', async () => {
    mockSites([ARCHIVED_SITE])
    const spy = vi.spyOn(apiClient, 'postRestoreSite').mockResolvedValue({
      success: true, data: { ...ARCHIVED_SITE, status: 'inactive' }, error: null, request_id: 'r1',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('보관사이트')).toBeInTheDocument())
    fireEvent.click(within(cardFor('보관사이트')).getByRole('button', { name: /♻️ 복원/ }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('s3'))
    await waitFor(() => expect(within(cardFor('보관사이트')).getByText(/복원되었습니다/)).toBeInTheDocument())
  })

  it('shows an error message when the action fails', async () => {
    mockSites([ACTIVE_SITE])
    vi.spyOn(apiClient, 'postArchiveSite').mockResolvedValue({
      success: false, data: null, error: { code: 'NOT_FOUND', message: '사이트를 찾을 수 없습니다' }, request_id: null,
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('활성사이트')).toBeInTheDocument())
    fireEvent.click(within(cardFor('활성사이트')).getByRole('button', { name: /🗑️ 보관/ }))
    await waitFor(() => expect(within(cardFor('활성사이트')).getByText(/사이트를 찾을 수 없습니다/)).toBeInTheDocument())
  })

  it('disables all status buttons for a non-admin viewer', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
      success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2',
    })
    mockSites([ACTIVE_SITE])
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('활성사이트')).toBeInTheDocument())
    const card = within(cardFor('활성사이트'))
    expect(card.getByRole('button', { name: /⏸ 비활성화/ })).toBeDisabled()
    expect(card.getByRole('button', { name: /🗑️ 보관/ })).toBeDisabled()
  })

  it('re-fetches the site list after a successful status change', async () => {
    mockSites([ACTIVE_SITE])
    vi.spyOn(apiClient, 'postArchiveSite').mockResolvedValue({
      success: true, data: { ...ACTIVE_SITE, status: 'archived' }, error: null, request_id: 'ar2',
    })
    render(<SiteManagementPanel />)
    await waitFor(() => expect(apiClient.getSites).toHaveBeenCalledTimes(1))
    fireEvent.click(within(cardFor('활성사이트')).getByRole('button', { name: /🗑️ 보관/ }))
    await waitFor(() => expect(apiClient.getSites).toHaveBeenCalledTimes(2))
  })

  it('prevents duplicate clicks while a request is in flight', async () => {
    mockSites([ACTIVE_SITE])
    let resolvePromise
    const spy = vi.spyOn(apiClient, 'postArchiveSite').mockReturnValue(
      new Promise((resolve) => { resolvePromise = resolve })
    )
    render(<SiteManagementPanel />)
    await waitFor(() => expect(screen.getByText('활성사이트')).toBeInTheDocument())
    const btn = within(cardFor('활성사이트')).getByRole('button', { name: /🗑️ 보관/ })
    fireEvent.click(btn)
    await waitFor(() => expect(btn).toBeDisabled())
    fireEvent.click(btn)
    fireEvent.click(btn)
    resolvePromise({ success: true, data: { ...ACTIVE_SITE, status: 'archived' }, error: null, request_id: 'ar3' })
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
  })
})
