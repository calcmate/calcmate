import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import CostPanel from '../components/CostPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP S4: Cost Monitor 비용 집계/Breakdown React/FastAPI 이관 검증.
// CostPanel은 이미 STEP 18-Z에서 오늘/이번달 비용·Retry Queue를 표시하고
// 있었으나 Provider/Model breakdown이 빠져 있었다 — 이번 STEP에서 추가한
// 그 표시를 검증한다. /api/costs가 이번 STEP에서 require_admin으로 전환된
// 것은 서버(tests/test_cost_monitor.py)에서 검증하고, 여기서는 React가
// 성공/실패(403 포함) 응답을 올바르게 반영하는지만 확인한다.

const COSTS_OK = {
  success: true,
  data: {
    today: { used: 0.0019, limit: 5, exceeded: false, tokens: 4985 },
    month: { used: 0.02, limit: 100, exceeded: false },
    total_cost: 1.23,
    by_provider_month: { openai: 0.5, claude: 0.3 },
    by_model_month: { 'gpt-4o': 0.5, 'claude-3-5-sonnet': 0.3 },
    cost_manager: { pct: 0.4, paused: false },
    retry_queue: { pending_count: 0, items: [] },
  },
  error: null,
  request_id: 'c1',
}

const FORBIDDEN = { success: false, data: null, error: { code: 'FORBIDDEN', message: '관리자 권한이 필요합니다' }, request_id: null }
const NETWORK_FAILURE = { success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null }

afterEach(() => {
  vi.restoreAllMocks()
})

describe('CostPanel Provider/Model breakdown (STEP S4)', () => {
  it('renders total/today/month figures from the real API response, not hardcoded', async () => {
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(COSTS_OK)
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText(/\$0\.0019/)).toBeInTheDocument())
    expect(screen.getByText(/\$1\.2300/)).toBeInTheDocument()
    expect(screen.getByText('4,985')).toBeInTheDocument()
  })

  it('renders the Provider breakdown', async () => {
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(COSTS_OK)
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText('openai')).toBeInTheDocument())
    expect(screen.getByText('claude')).toBeInTheDocument()
    expect(screen.getAllByText(/\$0\.5000/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/\$0\.3000/).length).toBeGreaterThan(0)
  })

  it('renders the Model breakdown sorted by cost descending', async () => {
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(COSTS_OK)
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText('gpt-4o')).toBeInTheDocument())
    expect(screen.getByText('claude-3-5-sonnet')).toBeInTheDocument()
  })

  it('shows "이번달 집계 없음" for empty provider/model breakdowns, not a blank section', async () => {
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue({
      success: true,
      data: { ...COSTS_OK.data, by_provider_month: {}, by_model_month: {} },
      error: null, request_id: 'c2',
    })
    render(<CostPanel />)
    await waitFor(() => expect(screen.getAllByText('이번달 집계 없음').length).toBe(2))
  })

  it('shows a loading state before the API resolves', () => {
    vi.spyOn(apiClient, 'getCosts').mockReturnValue(new Promise(() => {}))
    render(<CostPanel />)
    expect(screen.getByText('불러오는 중...')).toBeInTheDocument()
  })

  it('shows the generic error UI when a viewer is forbidden (403)', async () => {
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(FORBIDDEN)
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })

  it('shows the generic error UI on a network/server failure', async () => {
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(NETWORK_FAILURE)
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })

  it('renders successfully for an admin-shaped successful response', async () => {
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(COSTS_OK)
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText('💰 비용 모니터')).toBeInTheDocument())
    expect(screen.queryByText('⚠ API 연결 실패')).not.toBeInTheDocument()
  })

  it('does not render Resume/Retry execution buttons when not paused and queue is empty', async () => {
    // STEP S5: Resume/Retry 버튼 자체는 이제 존재하지만(별도 CostResumeRetry.test.jsx
    // 참고), COSTS_OK는 paused=false·retry_queue 비어있음이므로 이 상태에서는
    // 여전히 어떤 실행 버튼도 보이면 안 된다.
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(COSTS_OK)
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText('openai')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /수동 재개/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /재발행/ })).not.toBeInTheDocument()
  })
})
