import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import DashboardStatusSummaryPanel from '../components/DashboardStatusSummaryPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-10: Dashboard "📊 현황" React/FastAPI 이관 검증. 실제
// getDashboardStatusSummary는 이 파일의 어떤 테스트에서도 호출하지 않는다.

const DATA = {
  statuses: [
    { status: '대기', icon: '🟡', count: 2 },
    { status: '작성중', icon: '🔵', count: 1 },
    { status: '검수대기', icon: '🟠', count: 0 },
    { status: '발행완료', icon: '🟢', count: 7 },
    { status: '이미지오류', icon: '🔴', count: 0 },
    { status: '재처리대기', icon: '⚫', count: 0 },
  ],
  today_published: 0, daily_goal: 1, progress_percent: 0,
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Dashboard Status Summary Panel (STEP P2-10)', () => {
  it('shows loading state initially', () => {
    vi.spyOn(apiClient, 'getDashboardStatusSummary').mockReturnValue(new Promise(() => {}))
    render(<DashboardStatusSummaryPanel />)
    expect(screen.getByText(/불러오는 중/)).toBeInTheDocument()
  })

  it('renders all 6 status counts with their icons', async () => {
    vi.spyOn(apiClient, 'getDashboardStatusSummary').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 's1',
    })
    render(<DashboardStatusSummaryPanel />)
    await waitFor(() => expect(screen.getByText('🟡 대기')).toBeInTheDocument())
    expect(screen.getByText('🔵 작성중')).toBeInTheDocument()
    expect(screen.getByText('🟠 검수대기')).toBeInTheDocument()
    expect(screen.getByText('🟢 발행완료')).toBeInTheDocument()
    expect(screen.getByText('🔴 이미지오류')).toBeInTheDocument()
    expect(screen.getByText('⚫ 재처리대기')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
  })

  it('renders the today-published/goal text and progress bar', async () => {
    vi.spyOn(apiClient, 'getDashboardStatusSummary').mockResolvedValue({
      success: true, data: { ...DATA, today_published: 2, daily_goal: 4, progress_percent: 50 },
      error: null, request_id: 's2',
    })
    render(<DashboardStatusSummaryPanel />)
    await waitFor(() => expect(screen.getByText('오늘 발행: 2/4')).toBeInTheDocument())
    const progress = document.querySelector('progress')
    expect(progress).toHaveAttribute('value', '50')
    expect(progress).toHaveAttribute('max', '100')
  })

  it('shows an empty-state hint when all counts are zero', async () => {
    vi.spyOn(apiClient, 'getDashboardStatusSummary').mockResolvedValue({
      success: true,
      data: {
        statuses: DATA.statuses.map((s) => ({ ...s, count: 0 })),
        today_published: 0, daily_goal: 3, progress_percent: 0,
      },
      error: null, request_id: 's3',
    })
    render(<DashboardStatusSummaryPanel />)
    await waitFor(() => expect(screen.getByText('등록된 글이 없습니다.')).toBeInTheDocument())
  })

  it('shows an error message on API failure', async () => {
    vi.spyOn(apiClient, 'getDashboardStatusSummary').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<DashboardStatusSummaryPanel />)
    await waitFor(() => expect(screen.getByText(/API 연결 실패/)).toBeInTheDocument())
  })

  it('calls getDashboardStatusSummary again on refresh click', async () => {
    const spy = vi.spyOn(apiClient, 'getDashboardStatusSummary').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 's4',
    })
    render(<DashboardStatusSummaryPanel />)
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    screen.getByRole('button', { name: /새로고침/ }).click()
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })
})
