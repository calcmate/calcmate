import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import CalculatorQuickActionPanel from '../components/CalculatorQuickActionPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP S11: Dashboard Quick Action 「🧮 계산기 생성」React/FastAPI 이관 검증. 실제
// postCalculatorRunOnce는 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상
// mock으로 대체한다(실제 AI 호출/DB write 없음).

const ADMIN_USER = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER_USER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }

const SUCCESS_RESULT = {
  produced: 1, processed: 3, failed: 0, dup: 1, quality_hold: 0, hold_skip: 1,
  reason: '정상완료', attempted: 1,
  published: { keyword: '퇴직금 계산법', title: '퇴직금 계산법 총정리', status: 'completed' },
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Calculator Quick Action (STEP S11)', () => {
  it('renders the panel with a 계산기 생성 button', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    render(<CalculatorQuickActionPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /계산기 생성/ })).toBeInTheDocument())
  })

  it('disables the button for a viewer', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    render(<CalculatorQuickActionPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /계산기 생성/ })).toBeDisabled())
  })

  it('clicking the button shows loading, disables it, and prevents duplicate clicks', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const runSpy = vi.spyOn(apiClient, 'postCalculatorRunOnce').mockReturnValue(new Promise(() => {}))
    render(<CalculatorQuickActionPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /계산기 생성/ })).toBeEnabled())

    const btn = screen.getByRole('button', { name: /계산기 생성/ })
    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByRole('button', { name: /생성 중/ })).toBeDisabled())
    fireEvent.click(screen.getByRole('button', { name: /생성 중/ }))
    fireEvent.click(screen.getByRole('button', { name: /생성 중/ }))

    expect(runSpy).toHaveBeenCalledTimes(1)
  })

  it('sends no request body (mirrors the existing Streamlit call signature)', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const runSpy = vi.spyOn(apiClient, 'postCalculatorRunOnce').mockResolvedValue({
      success: true, data: SUCCESS_RESULT, error: null, request_id: 'c1',
    })
    render(<CalculatorQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /계산기 생성/ }))
    await waitFor(() => expect(runSpy).toHaveBeenCalledWith())
  })

  it('shows the success message with produced count and published title', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postCalculatorRunOnce').mockResolvedValue({
      success: true, data: SUCCESS_RESULT, error: null, request_id: 'c2',
    })
    render(<CalculatorQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /계산기 생성/ }))

    await waitFor(() => expect(screen.getByText(/계산기 생성 요청 완료/)).toBeInTheDocument())
    expect(screen.getByText(/생산 1건/)).toBeInTheDocument()
    expect(screen.getByText(/퇴직금 계산법 총정리/)).toBeInTheDocument()
  })

  it('shows an info (not success) message when produced=0', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postCalculatorRunOnce').mockResolvedValue({
      success: true,
      data: { produced: 0, reason: 'no_calculators' },
      error: null, request_id: 'c3',
    })
    render(<CalculatorQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /계산기 생성/ }))
    await waitFor(() => expect(screen.getByText(/생산 0건/)).toBeInTheDocument())
    expect(screen.getByText(/활성 계산기 없음/)).toBeInTheDocument()
  })

  it('shows the "다른 계산기 생성 실행이 진행 중" message on LOCK_CONFLICT', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postCalculatorRunOnce').mockResolvedValue({
      success: false, data: null,
      error: { code: 'LOCK_CONFLICT', message: '다른 계산기 생성 실행이 진행 중입니다. 잠시 후 재시도하세요.' },
      request_id: null,
    })
    render(<CalculatorQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /계산기 생성/ }))
    await waitFor(() => expect(screen.getByText(/다른 계산기 생성 실행이 진행 중입니다/)).toBeInTheDocument())
  })

  it('shows a generic error message on network/server failure', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postCalculatorRunOnce').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<CalculatorQuickActionPanel />)
    fireEvent.click(await screen.findByRole('button', { name: /계산기 생성/ }))
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument())
  })
})
