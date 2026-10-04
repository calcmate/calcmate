import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import ContentSyncManualPanel from '../components/ContentSyncManualPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP S10: Content Sync Manual Sync React/FastAPI 이관 검증. 실제
// postContentSyncRunOnce는 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상
// mock으로 대체한다(실제 WordPress/Sheets 변경 없음).

const ADMIN_USER = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER_USER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }

const SUCCESS_RESULT = {
  ok: true, mode: 'recent', adapter: 'wordpress', checked: 12, changed: 2, skipped: 0,
  anomalies: [
    { flag: 'URL_CHANGED', post_id: '101', url: 'http://x/1', wp_status: 'publish', article_id: 'a1', title: '제목1' },
    { flag: 'ORPHAN_WP', post_id: '202', url: 'http://x/2', wp_status: 'publish', article_id: '' },
  ],
  anomaly_count: 2, started_at: 't1', finished_at: 't2',
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Content Sync Manual Sync (STEP S10)', () => {
  it('renders the panel with a Sync Now button', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    render(<ContentSyncManualPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /Sync Now/ })).toBeInTheDocument())
  })

  it('disables the button for a viewer', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    render(<ContentSyncManualPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /Sync Now/ })).toBeDisabled())
  })

  it('clicking Sync Now shows loading, disables the button, and prevents duplicate clicks', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const runSpy = vi.spyOn(apiClient, 'postContentSyncRunOnce').mockReturnValue(new Promise(() => {}))
    render(<ContentSyncManualPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /Sync Now/ })).toBeEnabled())

    const btn = screen.getByRole('button', { name: /Sync Now/ })
    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByRole('button', { name: /동기화 중/ })).toBeDisabled())
    fireEvent.click(screen.getByRole('button', { name: /동기화 중/ }))
    fireEvent.click(screen.getByRole('button', { name: /동기화 중/ }))

    expect(runSpy).toHaveBeenCalledTimes(1)
  })

  it('sends the selected mode ("full") when the radio is changed', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const runSpy = vi.spyOn(apiClient, 'postContentSyncRunOnce').mockResolvedValue({
      success: true, data: SUCCESS_RESULT, error: null, request_id: 'cs1',
    })
    render(<ContentSyncManualPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /Sync Now/ })).toBeEnabled())

    fireEvent.click(screen.getByLabelText(/full/))
    fireEvent.click(screen.getByRole('button', { name: /Sync Now/ }))

    await waitFor(() => expect(runSpy).toHaveBeenCalledWith('full'))
  })

  it('shows the success message with checked/changed counts and anomaly details', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postContentSyncRunOnce').mockResolvedValue({
      success: true, data: SUCCESS_RESULT, error: null, request_id: 'cs2',
    })
    render(<ContentSyncManualPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /Sync Now/ }))

    await waitFor(() => expect(screen.getByText(/동기화 완료/)).toBeInTheDocument())
    expect(screen.getByText(/검사 12건/)).toBeInTheDocument()
    expect(screen.getByText(/변경 2건/)).toBeInTheDocument()
    expect(screen.getByText(/URL_CHANGED 1/)).toBeInTheDocument()
    expect(screen.getByText(/ORPHAN_WP 1/)).toBeInTheDocument()
    expect(screen.getByText(/post_id=101/)).toBeInTheDocument()
  })

  it('shows the "동기화 미실행" message when the sync ran but ok=false', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postContentSyncRunOnce').mockResolvedValue({
      success: true,
      data: { ok: false, reason: 'adapter_not_ready', mode: 'recent', checked: 0, changed: 0, anomalies: [] },
      error: null, request_id: 'cs3',
    })
    render(<ContentSyncManualPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /Sync Now/ }))
    await waitFor(() => expect(screen.getByText(/동기화 미실행/)).toBeInTheDocument())
    expect(screen.getByText(/adapter_not_ready/)).toBeInTheDocument()
  })

  it('shows the "다른 동기화가 진행 중" message on LOCK_CONFLICT', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postContentSyncRunOnce').mockResolvedValue({
      success: false, data: null,
      error: { code: 'LOCK_CONFLICT', message: '다른 동기화가 진행 중입니다(자동 03:00 또는 다른 실행). 잠시 후 재시도하세요.' },
      request_id: null,
    })
    render(<ContentSyncManualPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /Sync Now/ }))
    await waitFor(() => expect(screen.getByText(/다른 동기화가 진행 중입니다/)).toBeInTheDocument())
  })

  it('shows a generic error message on network/server failure', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postContentSyncRunOnce').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<ContentSyncManualPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /Sync Now/ }))
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument())
  })
})
