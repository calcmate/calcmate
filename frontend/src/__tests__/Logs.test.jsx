import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import Logs from '../pages/Logs.jsx'
import Dashboard from '../pages/Dashboard.jsx'
import { MemoryRouter } from 'react-router-dom'
import * as apiClient from '../api/client.js'

const ERRORS_EMPTY = { success: true, data: { operation_errors: [], calculator_quality_holds: [], total: 0 }, error: null, request_id: 'e1' }
const ERRORS_WITH_DATA = {
  success: true,
  data: {
    operation_errors: [{ '실행일시': '2026-09-02 01:30', '대상정책명': 'severance-pay', '실패모듈': 'Blog Scheduler', '오류내용': 'x'.repeat(300) }],
    calculator_quality_holds: [],
    total: 1,
  },
  error: null,
  request_id: 'e2',
}
const RECENT_OK = { success: true, data: { lines: ['2026-09-02 01:30 [INFO] step done'] }, error: null, request_id: 'e3' }
const LIVE_OK = { success: true, data: { entries: [{ line: '2026-09-02 [INFO] hello', level: 'info' }], counts: { error: 0, warn: 0, info: 1 } }, error: null, request_id: 'e4' }
const COSTS_OK = {
  success: true,
  data: {
    today: { used: 0.0019, limit: 5, exceeded: false, tokens: 4985 },
    month: { used: 0.02, limit: 100, exceeded: false },
    total_cost: 1.23,
    by_provider_month: { openai: 0.5 },
    by_model_month: { 'gpt-4o': 0.5 },
    cost_manager: { pct: 0.4, paused: false },
    retry_queue: { pending_count: 0, items: [] },
  },
  error: null,
  request_id: 'e5',
}
const PIPELINE_OK = {
  success: true,
  data: { stages: [{ name: '본문 작성', model: 'gpt-4o', status: 'completed' }], finished: true, has_error: false, cost_today: 0, tokens_today: 0, model_costs: {}, last_lines: [] },
  error: null,
  request_id: 'e6',
}
const FAILURE = { success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null }

function mockAllOk() {
  vi.spyOn(apiClient, 'getErrorLogs').mockResolvedValue(ERRORS_EMPTY)
  vi.spyOn(apiClient, 'getRecentLogs').mockResolvedValue(RECENT_OK)
  vi.spyOn(apiClient, 'getLiveLogs').mockResolvedValue(LIVE_OK)
  vi.spyOn(apiClient, 'getCosts').mockResolvedValue(COSTS_OK)
  vi.spyOn(apiClient, 'getPipelineStatus').mockResolvedValue(PIPELINE_OK)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('API client — STEP 18-G', () => {
  it('exposes exactly the log/cost/pipeline read functions (no write functions)', () => {
    expect(typeof apiClient.getErrorLogs).toBe('function')
    expect(typeof apiClient.getRecentLogs).toBe('function')
    expect(typeof apiClient.getLiveLogs).toBe('function')
    expect(typeof apiClient.getPipelineStatus).toBe('function')
    expect(typeof apiClient.getCosts).toBe('function')
  })
})

describe('Logs page (/logs)', () => {
  it('renders empty-state messages when there is no data', async () => {
    mockAllOk()
    render(<Logs />)
    await waitFor(() => expect(screen.getByText('최근 오류가 없습니다.')).toBeInTheDocument())
    expect(screen.getByText('품질보류 항목이 없습니다.')).toBeInTheDocument()
  })

  it('renders a long error message without crashing and keeps it in the DOM as text', async () => {
    vi.spyOn(apiClient, 'getErrorLogs').mockResolvedValue(ERRORS_WITH_DATA)
    vi.spyOn(apiClient, 'getRecentLogs').mockResolvedValue(RECENT_OK)
    vi.spyOn(apiClient, 'getLiveLogs').mockResolvedValue(LIVE_OK)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(COSTS_OK)
    vi.spyOn(apiClient, 'getPipelineStatus').mockResolvedValue(PIPELINE_OK)
    render(<Logs />)
    await waitFor(() => expect(screen.getByText(/severance-pay/)).toBeInTheDocument())
    expect(screen.getByText(new RegExp('x'.repeat(50)))).toBeInTheDocument()
  })

  it('shows cost figures from the API, not hardcoded numbers', async () => {
    mockAllOk()
    render(<Logs />)
    await waitFor(() => expect(screen.getByText(/\$0\.0019/)).toBeInTheDocument())
  })

  it('shows "데이터 없음" when a cost figure is missing rather than fabricating a number', async () => {
    vi.spyOn(apiClient, 'getErrorLogs').mockResolvedValue(ERRORS_EMPTY)
    vi.spyOn(apiClient, 'getRecentLogs').mockResolvedValue(RECENT_OK)
    vi.spyOn(apiClient, 'getLiveLogs').mockResolvedValue(LIVE_OK)
    vi.spyOn(apiClient, 'getPipelineStatus').mockResolvedValue(PIPELINE_OK)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue({
      success: true,
      data: { ...COSTS_OK.data, today: { used: null, limit: null, exceeded: false, tokens: null } },
      error: null, request_id: 'e7',
    })
    render(<Logs />)
    await waitFor(() => expect(screen.getAllByText('데이터 없음').length).toBeGreaterThan(0))
  })

  it('live log level filter re-fetches with the selected level', async () => {
    mockAllOk()
    render(<Logs />)
    await waitFor(() => expect(screen.getByLabelText('필터')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('필터'), { target: { value: 'error' } })
    await waitFor(() => expect(apiClient.getLiveLogs).toHaveBeenCalledWith('error'))
  })

  it('shows the generic error UI when a panel API fails', async () => {
    vi.spyOn(apiClient, 'getErrorLogs').mockResolvedValue(FAILURE)
    vi.spyOn(apiClient, 'getRecentLogs').mockResolvedValue(RECENT_OK)
    vi.spyOn(apiClient, 'getLiveLogs').mockResolvedValue(LIVE_OK)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(COSTS_OK)
    vi.spyOn(apiClient, 'getPipelineStatus').mockResolvedValue(PIPELINE_OK)
    render(<Logs />)
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })

  it('does not render any write/refresh-triggering mutation button beyond refresh', () => {
    mockAllOk()
    render(<Logs />)
    // "재발행", "제거", "재개" 같은 쓰기 액션 버튼이 없어야 한다.
    expect(screen.queryByRole('button', { name: /재발행/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /재개/ })).not.toBeInTheDocument()
  })
})

describe('Dashboard Recent Activity (STEP 18-G extension)', () => {
  it('renders the Dashboard status card and Recent Activity panel', async () => {
    vi.spyOn(apiClient, 'getHealth').mockResolvedValue({ success: true, data: { status: 'ok', service: 'calcmate-api' }, error: null, request_id: 'd1' })
    vi.spyOn(apiClient, 'getDashboardStatus').mockResolvedValue({ success: true, data: { api: 'ok', dashboard: 'fastapi', workers: {} }, error: null, request_id: 'd2' })
    vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue({ success: true, data: { name: 'blog', enabled: false, running: false, thread_alive: false }, error: null, request_id: 'd3' })
    vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue({ success: true, data: { name: 'calculator', enabled: false, running: false, thread_alive: false }, error: null, request_id: 'd4' })
    vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue({ success: true, data: { name: 'content_sync', enabled: false, running: false, thread_alive: false }, error: null, request_id: 'd5' })
    vi.spyOn(apiClient, 'getRecentLogs').mockResolvedValue(RECENT_OK)
    vi.spyOn(apiClient, 'getErrorLogs').mockResolvedValue(ERRORS_EMPTY)

    render(
      <MemoryRouter initialEntries={['/']}>
        <Dashboard />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('Dashboard')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('🕒 Recent Activity')).toBeInTheDocument())
    expect(screen.getByText('최근 오류 0건')).toBeInTheDocument()
  })
})
