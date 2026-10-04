import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import StrategyRoom from '../pages/StrategyRoom.jsx'
import * as apiClient from '../api/client.js'

// STEP S8: Strategy Room React/FastAPI 이관 검증. 실제 postStrategyRoomRun은
// 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상 mock으로 대체한다(실제
// AI 호출 없음).

const ADMIN_USER = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER_USER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }

const FULL_RESULT = {
  new_category_candidates: ['재테크'],
  rss_recommendations: ['https://example.test/feed'],
  rewrite_candidates: [],
  best_publish_time: ['09:00'],
  monetization_suggestions: '테스트 제안',
  auto_topic_expansion_eligible: {
    condition_1_adsense_post: true,
    condition_2_post_count: false,
    condition_3_ctr: false,
    condition_4_positive_recommendation: true,
    all_met: false,
  },
  summary: '테스트 요약입니다',
  _tokens: 1234,
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Strategy Room (STEP S8)', () => {
  it('renders the Strategy Room area with an execute button', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    render(<StrategyRoom />)
    await waitFor(() => expect(screen.getByText('🧠 전략회의실')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /전략회의실 실행/ })).toBeInTheDocument()
  })

  it('disables the execute button for a viewer', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    render(<StrategyRoom />)
    await waitFor(() => expect(screen.getByRole('button', { name: /전략회의실 실행/ })).toBeDisabled())
  })

  it('shows a loading state while running and prevents duplicate clicks', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const runSpy = vi.spyOn(apiClient, 'postStrategyRoomRun').mockReturnValue(new Promise(() => {}))
    render(<StrategyRoom />)
    await waitFor(() => expect(screen.getByRole('button', { name: /전략회의실 실행/ })).toBeEnabled())

    fireEvent.click(screen.getByRole('button', { name: /전략회의실 실행/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /분석 중/ })).toBeDisabled())
    fireEvent.click(screen.getByRole('button', { name: /분석 중/ }))

    expect(runSpy).toHaveBeenCalledTimes(1)
  })

  it('shows the full result structure on success', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postStrategyRoomRun').mockResolvedValue({
      success: true,
      data: { enabled: true, result: FULL_RESULT, error: null },
      error: null, request_id: 'sr1',
    })
    render(<StrategyRoom />)
    await waitFor(() => expect(screen.getByRole('button', { name: /전략회의실 실행/ })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /전략회의실 실행/ }))

    await waitFor(() => expect(screen.getByText('테스트 요약입니다')).toBeInTheDocument())
    expect(screen.getByText('재테크')).toBeInTheDocument()
    expect(screen.getByText('https://example.test/feed')).toBeInTheDocument()
    expect(screen.getByText('09:00')).toBeInTheDocument()
    expect(screen.getByText('테스트 제안')).toBeInTheDocument()
    expect(screen.getAllByText(/1234/).length).toBeGreaterThan(0)
    // 리스트가 빈 항목("리라이팅 후보")은 "추천 없음"으로 표시되어야 한다.
    expect(screen.getByText('추천 없음')).toBeInTheDocument()
  })

  it('shows the AUTO_TOPIC_EXPANSION eligibility conditions', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postStrategyRoomRun').mockResolvedValue({
      success: true,
      data: { enabled: true, result: FULL_RESULT, error: null },
      error: null, request_id: 'sr2',
    })
    render(<StrategyRoom />)
    fireEvent.click(await screen.findByRole('button', { name: /전략회의실 실행/ }))
    await waitFor(() => expect(screen.getByText('🚦 AUTO_TOPIC_EXPANSION 전환 조건')).toBeInTheDocument())
    expect(screen.getAllByText('✅').length).toBe(2)
    expect(screen.getAllByText('❌').length).toBe(3)
  })

  it('shows the disabled-config warning when ENABLE_STRATEGY_ROOM is off', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postStrategyRoomRun').mockResolvedValue({
      success: true,
      data: { enabled: false, result: {}, error: null },
      error: null, request_id: 'sr3',
    })
    render(<StrategyRoom />)
    fireEvent.click(await screen.findByRole('button', { name: /전략회의실 실행/ }))
    await waitFor(() => expect(screen.getByText(/ENABLE_STRATEGY_ROOM/)).toBeInTheDocument())
  })

  it('shows the empty-result guidance message when result is empty but no error', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postStrategyRoomRun').mockResolvedValue({
      success: true,
      data: { enabled: true, result: {}, error: null },
      error: null, request_id: 'sr4',
    })
    render(<StrategyRoom />)
    fireEvent.click(await screen.findByRole('button', { name: /전략회의실 실행/ }))
    await waitFor(() => expect(screen.getByText(/빈 결과를 반환했습니다/)).toBeInTheDocument())
  })

  it('shows an error message when the server reports a failure', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postStrategyRoomRun').mockResolvedValue({
      success: true,
      data: { enabled: true, result: {}, error: '전략회의실 실행 중 오류: boom' },
      error: null, request_id: 'sr5',
    })
    render(<StrategyRoom />)
    fireEvent.click(await screen.findByRole('button', { name: /전략회의실 실행/ }))
    await waitFor(() => expect(screen.getByText(/전략회의실 실행 중 오류: boom/)).toBeInTheDocument())
  })

  it('shows a network/server error when the request itself fails', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'postStrategyRoomRun').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<StrategyRoom />)
    fireEvent.click(await screen.findByRole('button', { name: /전략회의실 실행/ }))
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument())
  })
})
