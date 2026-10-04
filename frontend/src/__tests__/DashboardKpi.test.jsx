import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import DashboardKpiPanel from '../components/DashboardKpiPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-01: Dashboard Home/KPI React/FastAPI 이관 검증. 실제 getDashboardKpi는
// 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상 mock으로 대체한다.

const KPI_RESULT = {
  system: { value: '정상', sub: '6/6 OK' },
  workflow: { value: '전략', sub: '현재 단계' },
  ai_task: { value: 'gpt-4o', sub: '활성 모델' },
  today: { value: '3건', sub: '발행 / 생성 57' },
  cost: { value: '$1.23', sub: '/ $5 (25%)' },
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Dashboard KPI Panel (STEP P2-01)', () => {
  it('shows loading state initially', async () => {
    vi.spyOn(apiClient, 'getDashboardKpi').mockReturnValue(new Promise(() => {}))
    render(<DashboardKpiPanel />)
    expect(screen.getByText(/불러오는 중/)).toBeInTheDocument()
  })

  it('renders all 5 KPI cards with values and sub text', async () => {
    vi.spyOn(apiClient, 'getDashboardKpi').mockResolvedValue({
      success: true, data: KPI_RESULT, error: null, request_id: 'k1',
    })
    render(<DashboardKpiPanel />)
    await waitFor(() => expect(screen.getByText('정상')).toBeInTheDocument())
    expect(screen.getByText('6/6 OK')).toBeInTheDocument()
    expect(screen.getByText('전략')).toBeInTheDocument()
    expect(screen.getByText('gpt-4o')).toBeInTheDocument()
    expect(screen.getByText('3건')).toBeInTheDocument()
    expect(screen.getByText('발행 / 생성 57')).toBeInTheDocument()
    expect(screen.getByText('$1.23')).toBeInTheDocument()
    expect(screen.getByText('/ $5 (25%)')).toBeInTheDocument()
  })

  it('shows the 5 card labels', async () => {
    vi.spyOn(apiClient, 'getDashboardKpi').mockResolvedValue({
      success: true, data: KPI_RESULT, error: null, request_id: 'k2',
    })
    render(<DashboardKpiPanel />)
    await waitFor(() => expect(screen.getByText(/시스템/)).toBeInTheDocument())
    expect(screen.getByText(/Workflow/)).toBeInTheDocument()
    expect(screen.getByText(/AI 작업/)).toBeInTheDocument()
    expect(screen.getByText(/오늘/)).toBeInTheDocument()
    expect(screen.getByText(/AI 비용/)).toBeInTheDocument()
  })

  it('shows an empty-safe dash when a card value is missing', async () => {
    vi.spyOn(apiClient, 'getDashboardKpi').mockResolvedValue({
      success: true,
      data: { system: {}, workflow: {}, ai_task: {}, today: {}, cost: {} },
      error: null, request_id: 'k3',
    })
    render(<DashboardKpiPanel />)
    await waitFor(() => expect(screen.getAllByText('—').length).toBeGreaterThan(0))
  })

  it('shows an error message on API failure (e.g. 403 for non-admin)', async () => {
    vi.spyOn(apiClient, 'getDashboardKpi').mockResolvedValue({ detail: 'Forbidden' })
    render(<DashboardKpiPanel />)
    await waitFor(() => expect(screen.getByText(/API 연결 실패/)).toBeInTheDocument())
  })

  it('shows an error message on network failure', async () => {
    vi.spyOn(apiClient, 'getDashboardKpi').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<DashboardKpiPanel />)
    await waitFor(() => expect(screen.getByText(/API 연결 실패/)).toBeInTheDocument())
  })

  it('calls getDashboardKpi again on refresh click', async () => {
    const spy = vi.spyOn(apiClient, 'getDashboardKpi').mockResolvedValue({
      success: true, data: KPI_RESULT, error: null, request_id: 'k4',
    })
    render(<DashboardKpiPanel />)
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    screen.getByRole('button', { name: /새로고침/ }).click()
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })
})
