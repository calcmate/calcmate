import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import PipelineQuickActionPanel from '../components/PipelineQuickActionPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP S12: Dashboard Quick Action 「▶ 파이프라인 실행(전량)」React/FastAPI 이관
// 검증. 실제 postPipelineRunOnce는 이 파일의 어떤 테스트에서도 호출하지 않는다 —
// 항상 mock으로 대체한다(실제 AI 호출/이미지 생성/WordPress 발행/DB write 없음).

const ADMIN_USER = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER_USER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }

const SUCCESS_RESULT = {
  produced: 1, processed: 4, dup: 1, failed: 1, no_wp: 0, reason: 'ok',
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Pipeline Quick Action (STEP S12)', () => {
  it('renders the panel with a 파이프라인 실행 button', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    render(<PipelineQuickActionPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /파이프라인 실행/ })).toBeInTheDocument())
  })

  it('disables the button for a viewer', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    render(<PipelineQuickActionPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /파이프라인 실행/ })).toBeDisabled())
  })

  it('clicking the button shows loading, disables it, and prevents duplicate clicks', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const runSpy = vi.spyOn(apiClient, 'postPipelineRunOnce').mockReturnValue(new Promise(() => {}))
    render(<PipelineQuickActionPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /파이프라인 실행/ })).toBeEnabled())

    const btn = screen.getByRole('button', { name: /파이프라인 실행/ })
    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByRole('button', { name: /실행 중/ })).toBeDisabled())
    fireEvent.click(screen.getByRole('button', { name: /실행 중/ }))
    fireEvent.click(screen.getByRole('button', { name: /실행 중/ }))

    expect(runSpy).toHaveBeenCalledTimes(1)
  })

  it('sends no request body (mirrors the existing Streamlit call signature)', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const runSpy = vi.spyOn(apiClient, 'postPipelineRunOnce').mockResolvedValue({
      success: true, data: SUCCESS_RESULT, error: null, request_id: 'p1',
    })
    render(<PipelineQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /파이프라인 실행/ }))
    await waitFor(() => expect(runSpy).toHaveBeenCalledWith())
  })

  it('shows the success message with produced count', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postPipelineRunOnce').mockResolvedValue({
      success: true, data: SUCCESS_RESULT, error: null, request_id: 'p2',
    })
    render(<PipelineQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /파이프라인 실행/ }))

    await waitFor(() => expect(screen.getByText(/파이프라인 실행 요청 완료/)).toBeInTheDocument())
    expect(screen.getByText(/생산 1건/)).toBeInTheDocument()
  })

  it('shows an info (not success) message when produced=0', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postPipelineRunOnce').mockResolvedValue({
      success: true,
      data: { produced: 0, reason: 'no_items' },
      error: null, request_id: 'p3',
    })
    render(<PipelineQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /파이프라인 실행/ }))
    await waitFor(() => expect(screen.getByText(/생산 0건/)).toBeInTheDocument())
    expect(screen.getByText(/수집된 항목 없음/)).toBeInTheDocument()
  })

  it('shows the "다른 파이프라인 실행이 진행 중" message on LOCK_CONFLICT', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postPipelineRunOnce').mockResolvedValue({
      success: false, data: null,
      error: { code: 'LOCK_CONFLICT', message: '다른 파이프라인 실행이 진행 중입니다(Blog Scheduler 또는 다른 실행). 잠시 후 재시도하세요.' },
      request_id: null,
    })
    render(<PipelineQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /파이프라인 실행/ }))
    await waitFor(() => expect(screen.getByText(/다른 파이프라인 실행이 진행 중입니다/)).toBeInTheDocument())
  })

  it('shows a generic error message on network/server failure', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postPipelineRunOnce').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<PipelineQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /파이프라인 실행/ }))
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument())
  })
})
