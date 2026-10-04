import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import DashboardAiPipelinePanel from '../components/DashboardAiPipelinePanel.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-11: Dashboard "📊 AI Pipeline Monitor" React/FastAPI 이관 검증. 실제
// getDashboardAiPipeline은 이 파일의 어떤 테스트에서도 호출하지 않는다.

const DATA = {
  stages: [
    { name: '키워드 수집', model: 'RSS/Collector', status: 'completed' },
    { name: '리서치/전략', model: 'gemini-2.5-flash', status: 'completed' },
    { name: '본문 작성', model: 'gpt-4o-mini', status: 'running' },
    { name: '검수', model: 'claude-sonnet-4-6', status: 'pending' },
    { name: '이미지 생성', model: 'Pollinations', status: 'pending' },
    { name: '발행', model: 'WordPress REST', status: 'pending' },
  ],
  finished: false, has_error: false,
  cost_today: 0.1234, tokens_today: 5000,
  model_costs: { 'gemini-2.5-flash': 0.05, 'gpt-4o-mini': 0.0734 },
  last_lines: ['2026-09-06 12:00:00 [INFO] STEP 7 시작'],
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Dashboard AI Pipeline Panel (STEP P2-11)', () => {
  it('shows loading state initially', () => {
    vi.spyOn(apiClient, 'getDashboardAiPipeline').mockReturnValue(new Promise(() => {}))
    render(<DashboardAiPipelinePanel />)
    expect(screen.getByText(/불러오는 중/)).toBeInTheDocument()
  })

  it('renders all 6 stage cards with model and status', async () => {
    vi.spyOn(apiClient, 'getDashboardAiPipeline').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 'p1',
    })
    render(<DashboardAiPipelinePanel />)
    await waitFor(() => expect(screen.getByText('키워드 수집')).toBeInTheDocument())
    expect(screen.getByText('본문 작성')).toBeInTheDocument()
    expect(screen.getByText('모델: gpt-4o-mini')).toBeInTheDocument()
    expect(screen.getByText('상태: running')).toBeInTheDocument()
  })

  it('renders cost, tokens, and derived run-status text', async () => {
    vi.spyOn(apiClient, 'getDashboardAiPipeline').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 'p2',
    })
    render(<DashboardAiPipelinePanel />)
    await waitFor(() => expect(screen.getByText('$0.1234')).toBeInTheDocument())
    expect(screen.getByText('5,000')).toBeInTheDocument()
    expect(screen.getByText('🔵 진행중')).toBeInTheDocument()
  })

  it('shows "완료/대기" when finished and no error', async () => {
    vi.spyOn(apiClient, 'getDashboardAiPipeline').mockResolvedValue({
      success: true, data: { ...DATA, finished: true, has_error: false }, error: null, request_id: 'p3',
    })
    render(<DashboardAiPipelinePanel />)
    await waitFor(() => expect(screen.getByText('✅ 완료/대기')).toBeInTheDocument())
  })

  it('shows "오류" when has_error is true regardless of finished', async () => {
    vi.spyOn(apiClient, 'getDashboardAiPipeline').mockResolvedValue({
      success: true, data: { ...DATA, finished: true, has_error: true }, error: null, request_id: 'p4',
    })
    render(<DashboardAiPipelinePanel />)
    await waitFor(() => expect(screen.getByText('🔴 오류')).toBeInTheDocument())
  })

  it('renders the model-cost breakdown table when present', async () => {
    vi.spyOn(apiClient, 'getDashboardAiPipeline').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 'p5',
    })
    render(<DashboardAiPipelinePanel />)
    await waitFor(() => expect(screen.getByText('오늘 모델별 비용')).toBeInTheDocument())
    expect(screen.getByText('gemini-2.5-flash')).toBeInTheDocument()
    expect(screen.getByText('0.05')).toBeInTheDocument()
  })

  it('hides the model-cost table when model_costs is empty', async () => {
    vi.spyOn(apiClient, 'getDashboardAiPipeline').mockResolvedValue({
      success: true, data: { ...DATA, model_costs: {} }, error: null, request_id: 'p6',
    })
    render(<DashboardAiPipelinePanel />)
    await waitFor(() => expect(screen.getByText('키워드 수집')).toBeInTheDocument())
    expect(screen.queryByText('오늘 모델별 비용')).not.toBeInTheDocument()
  })

  it('renders the last log lines', async () => {
    vi.spyOn(apiClient, 'getDashboardAiPipeline').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 'p7',
    })
    render(<DashboardAiPipelinePanel />)
    await waitFor(() => expect(screen.getByText(/STEP 7 시작/)).toBeInTheDocument())
  })

  it('shows "(로그 없음)" when last_lines is empty', async () => {
    vi.spyOn(apiClient, 'getDashboardAiPipeline').mockResolvedValue({
      success: true, data: { ...DATA, last_lines: [] }, error: null, request_id: 'p8',
    })
    render(<DashboardAiPipelinePanel />)
    await waitFor(() => expect(screen.getByText('(로그 없음)')).toBeInTheDocument())
  })

  it('shows an error message on API failure', async () => {
    vi.spyOn(apiClient, 'getDashboardAiPipeline').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<DashboardAiPipelinePanel />)
    await waitFor(() => expect(screen.getByText(/API 연결 실패/)).toBeInTheDocument())
  })

  it('calls getDashboardAiPipeline again on refresh click', async () => {
    const spy = vi.spyOn(apiClient, 'getDashboardAiPipeline').mockResolvedValue({
      success: true, data: DATA, error: null, request_id: 'p9',
    })
    render(<DashboardAiPipelinePanel />)
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1))
    screen.getByRole('button', { name: /새로고침/ }).click()
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
  })
})
