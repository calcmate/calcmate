import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import DashboardPipelineStatusPanel from '../components/DashboardPipelineStatusPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-02: Dashboard Workflow(파이프라인 다이어그램) React/FastAPI 이관 검증.
// 실제 getDashboardPipelineStatus는 이 파일의 어떤 테스트에서도 호출하지 않는다.

const DATA = {
  blog: [
    { icon: '📥', label: '수집', status: 'completed' },
    { icon: '🧠', label: '전략', status: 'running' },
    { icon: '🚀', label: '발행', status: 'pending' },
  ],
  calculator: [
    { icon: '🔑', label: '키워드' },
    { icon: '🌐', label: '배포' },
  ],
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Dashboard Pipeline Status Panel (STEP P2-02)', () => {
  it('shows loading state initially', () => {
    vi.spyOn(apiClient, 'getDashboardPipelineStatus').mockReturnValue(new Promise(() => {}))
    render(<DashboardPipelineStatusPanel />)
    expect(screen.getByText(/불러오는 중/)).toBeInTheDocument()
  })

  it('renders blog and calculator step labels', async () => {
    vi.spyOn(apiClient, 'getDashboardPipelineStatus').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 'w1',
    })
    render(<DashboardPipelineStatusPanel />)
    await waitFor(() => expect(screen.getByText(/수집/)).toBeInTheDocument())
    expect(screen.getByText(/전략/)).toBeInTheDocument()
    expect(screen.getByText(/발행/)).toBeInTheDocument()
    expect(screen.getByText(/키워드/)).toBeInTheDocument()
    expect(screen.getByText(/배포/)).toBeInTheDocument()
  })

  it('shows the two section titles in order', async () => {
    vi.spyOn(apiClient, 'getDashboardPipelineStatus').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 'w2',
    })
    render(<DashboardPipelineStatusPanel />)
    await waitFor(() => expect(screen.getByText(/블로그 파이프라인/)).toBeInTheDocument())
    expect(screen.getByText(/계산기 파이프라인/)).toBeInTheDocument()
  })

  it('shows empty state when no steps are returned', async () => {
    vi.spyOn(apiClient, 'getDashboardPipelineStatus').mockResolvedValue({
      success: true, data: { blog: [], calculator: [] }, error: null, request_id: 'w3',
    })
    render(<DashboardPipelineStatusPanel />)
    await waitFor(() => expect(screen.getAllByText('No Data').length).toBe(2))
  })

  it('shows an error message on API failure', async () => {
    vi.spyOn(apiClient, 'getDashboardPipelineStatus').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<DashboardPipelineStatusPanel />)
    await waitFor(() => expect(screen.getByText(/API 연결 실패/)).toBeInTheDocument())
  })

  it('calls getDashboardPipelineStatus again on refresh click', async () => {
    const spy = vi.spyOn(apiClient, 'getDashboardPipelineStatus').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 'w4',
    })
    render(<DashboardPipelineStatusPanel />)
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    screen.getByRole('button', { name: /새로고침/ }).click()
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })
})
