import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import DashboardProgressPanel from '../components/DashboardProgressPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-02: Dashboard 진행 현황 React/FastAPI 이관 검증. 실제
// getDashboardProgress는 이 파일의 어떤 테스트에서도 호출하지 않는다.

const DATA = {
  total: 4, completed: 2, pct: 50, failed: 1, running: 0,
  next: '2026-09-06T10:00:00', retry_pending: 3,
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Dashboard Progress Panel (STEP P2-02)', () => {
  it('shows loading state initially', () => {
    vi.spyOn(apiClient, 'getDashboardProgress').mockReturnValue(new Promise(() => {}))
    render(<DashboardProgressPanel />)
    expect(screen.getByText(/불러오는 중/)).toBeInTheDocument()
  })

  it('renders the progress text and 4 metrics', async () => {
    vi.spyOn(apiClient, 'getDashboardProgress').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 'p1',
    })
    render(<DashboardProgressPanel />)
    await waitFor(() => expect(screen.getByText(/오늘 일정 2\/4 \(50%\)/)).toBeInTheDocument())
    expect(screen.getByText('3')).toBeInTheDocument() // Retry 대기
    expect(screen.getByText('1')).toBeInTheDocument() // 실패
    expect(screen.getByText('0')).toBeInTheDocument() // 진행중
    expect(screen.getByText('2026-09-06T10:00:00')).toBeInTheDocument()
  })

  it('shows a dash for next when there is no upcoming slot', async () => {
    vi.spyOn(apiClient, 'getDashboardProgress').mockResolvedValue({
      success: true, data: { ...DATA, next: null }, error: null, request_id: 'p2',
    })
    render(<DashboardProgressPanel />)
    await waitFor(() => expect(screen.getByText('-')).toBeInTheDocument())
  })

  it('shows a dash for retry_pending when the source failed (string "—")', async () => {
    vi.spyOn(apiClient, 'getDashboardProgress').mockResolvedValue({
      success: true, data: { ...DATA, retry_pending: '—' }, error: null, request_id: 'p3',
    })
    render(<DashboardProgressPanel />)
    await waitFor(() => expect(screen.getByText('—')).toBeInTheDocument())
  })

  it('handles zero total without crashing', async () => {
    vi.spyOn(apiClient, 'getDashboardProgress').mockResolvedValue({
      success: true,
      data: { total: 0, completed: 0, pct: 0, failed: 0, running: 0, next: null, retry_pending: 0 },
      error: null, request_id: 'p4',
    })
    render(<DashboardProgressPanel />)
    await waitFor(() => expect(screen.getByText(/오늘 일정 0\/0 \(0%\)/)).toBeInTheDocument())
  })

  it('shows an error message on API failure', async () => {
    vi.spyOn(apiClient, 'getDashboardProgress').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<DashboardProgressPanel />)
    await waitFor(() => expect(screen.getByText(/API 연결 실패/)).toBeInTheDocument())
  })

  it('calls getDashboardProgress again on refresh click', async () => {
    const spy = vi.spyOn(apiClient, 'getDashboardProgress').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 'p5',
    })
    render(<DashboardProgressPanel />)
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    screen.getByRole('button', { name: /새로고침/ }).click()
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })
})
