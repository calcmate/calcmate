import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import CostPanel from '../components/CostPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP S5: Cost Monitor Manual Resume / Retry Queue React/FastAPI 이관 검증.
// 실제 postCostResume/postCostRetry는 이 파일의 어떤 테스트에서도 호출하지
// 않는다 — 항상 mock으로 대체한다(실제 WordPress 발행/cost_state.json 변경 없음).

const ADMIN_USER = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER_USER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }

function costsResponse(overrides = {}) {
  return {
    success: true,
    data: {
      today: { used: 0.5, limit: 5, exceeded: false, tokens: 1000 },
      month: { used: 1, limit: 100, exceeded: false },
      total_cost: 10,
      by_provider_month: {},
      by_model_month: {},
      cost_manager: { pct: 40, paused: false },
      retry_queue: { pending_count: 0, items: [] },
      ...overrides,
    },
    error: null,
    request_id: 'c1',
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Manual Resume (STEP S5)', () => {
  it('does not show the Resume button when cost_manager is not paused', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(costsResponse({ cost_manager: { pct: 40, paused: false } }))
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText('🟢 정상')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /수동 재개/ })).not.toBeInTheDocument()
  })

  it('shows the Resume button when paused, enabled for admin', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(costsResponse({ cost_manager: { pct: 100, paused: true } }))
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /수동 재개/ })).toBeEnabled())
  })

  it('disables the Resume button for a viewer even when paused', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(costsResponse({ cost_manager: { pct: 100, paused: true } }))
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /수동 재개/ })).toBeDisabled())
  })

  it('clicking Resume shows loading, calls the API, and reloads status on success', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const getCostsSpy = vi.spyOn(apiClient, 'getCosts')
    getCostsSpy.mockResolvedValueOnce(costsResponse({ cost_manager: { pct: 100, paused: true } }))
    let resolveResume
    vi.spyOn(apiClient, 'postCostResume').mockReturnValue(new Promise((res) => { resolveResume = res }))

    render(<CostPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /수동 재개/ })).toBeEnabled())

    fireEvent.click(screen.getByRole('button', { name: /수동 재개/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /재개 중/ })).toBeDisabled())

    getCostsSpy.mockResolvedValueOnce(costsResponse({ cost_manager: { pct: 0, paused: false } }))
    resolveResume({ success: true, data: { ok: true, message: '재개됨' }, error: null, request_id: 'r1' })

    await waitFor(() => expect(screen.getByText(/재개됨/)).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('🟢 정상')).toBeInTheDocument())
    expect(getCostsSpy).toHaveBeenCalledTimes(2)
  })

  it('shows a server error and keeps existing state on failure', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(costsResponse({ cost_manager: { pct: 100, paused: true } }))
    vi.spyOn(apiClient, 'postCostResume').mockResolvedValue({
      success: true, data: { ok: false, message: '일시정지 상태가 아닙니다' }, error: null, request_id: 'r2',
    })
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /수동 재개/ })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /수동 재개/ }))
    await waitFor(() => expect(screen.getByText(/일시정지 상태가 아닙니다/)).toBeInTheDocument())
    // 실패했으므로 여전히 paused 표시가 유지되어야 한다(재조회하지 않음).
    expect(screen.getByText('⛔ 일시정지')).toBeInTheDocument()
  })

  it('prevents duplicate clicks while a resume request is in flight', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(costsResponse({ cost_manager: { pct: 100, paused: true } }))
    const resumeSpy = vi.spyOn(apiClient, 'postCostResume').mockReturnValue(new Promise(() => {}))
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /수동 재개/ })).toBeEnabled())

    const btn = screen.getByRole('button', { name: /수동 재개/ })
    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByRole('button', { name: /재개 중/ })).toBeDisabled())
    fireEvent.click(screen.getByRole('button', { name: /재개 중/ }))
    fireEvent.click(screen.getByRole('button', { name: /재개 중/ }))

    expect(resumeSpy).toHaveBeenCalledTimes(1)
  })
})

describe('Retry Queue 수동 재시도 (STEP S5)', () => {
  const PENDING_ITEMS = [
    { id: 'p1', title: '테스트 제목1', created_at: '2026-09-05T10:00', error: '연결 실패' },
    { id: 'p2', title: '테스트 제목2', created_at: '2026-09-05T11:00', error: '타임아웃' },
  ]

  it('renders each pending item with an identifiable name and a Retry button', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(
      costsResponse({ retry_queue: { pending_count: 2, items: PENDING_ITEMS } })
    )
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText(/테스트 제목1/)).toBeInTheDocument())
    expect(screen.getByText(/테스트 제목2/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /재발행/ }).length).toBe(2)
  })

  it('viewer cannot use the Retry button', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(
      costsResponse({ retry_queue: { pending_count: 1, items: [PENDING_ITEMS[0]] } })
    )
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /재발행/ })).toBeDisabled())
  })

  it('clicking Retry on one item shows loading only for that item and reloads on success', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const getCostsSpy = vi.spyOn(apiClient, 'getCosts')
    getCostsSpy.mockResolvedValueOnce(
      costsResponse({ retry_queue: { pending_count: 2, items: PENDING_ITEMS } })
    )
    let resolveRetry
    vi.spyOn(apiClient, 'postCostRetry').mockReturnValue(new Promise((res) => { resolveRetry = res }))

    render(<CostPanel />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: /재발행/ }).length).toBe(2))

    const buttons = screen.getAllByRole('button', { name: /재발행/ })
    fireEvent.click(buttons[0])

    await waitFor(() => expect(screen.getByRole('button', { name: /재시도 중/ })).toBeDisabled())
    // 두 번째 item의 버튼은 여전히 "재발행"으로 남아 있어야 한다(독립적 loading).
    expect(screen.getAllByRole('button', { name: /^🔁 재발행$/ }).length).toBe(1)

    getCostsSpy.mockResolvedValueOnce(
      costsResponse({ retry_queue: { pending_count: 1, items: [PENDING_ITEMS[1]] } })
    )
    resolveRetry({ success: true, data: { ok: true, message: '재발행 성공: http://x' }, error: null, request_id: 'rt1' })

    await waitFor(() => expect(screen.getByText(/재발행 성공/)).toBeInTheDocument())
    expect(apiClient.postCostRetry).toHaveBeenCalledWith('p1')
  })

  it('shows a per-item error on failure without affecting other items', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(
      costsResponse({ retry_queue: { pending_count: 2, items: PENDING_ITEMS } })
    )
    vi.spyOn(apiClient, 'postCostRetry').mockResolvedValue({
      success: true, data: { ok: false, message: '재발행 실패: WordPress 연결 거부' }, error: null, request_id: 'rt2',
    })
    render(<CostPanel />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: /재발행/ }).length).toBe(2))

    fireEvent.click(screen.getAllByRole('button', { name: /재발행/ })[0])
    await waitFor(() => expect(screen.getByText(/재발행 실패/)).toBeInTheDocument())
    // 두 item 모두 여전히 목록에 남아 있어야 한다(재조회 안 함, 실패는 제거되지 않음).
    expect(screen.getByText(/테스트 제목1/)).toBeInTheDocument()
    expect(screen.getByText(/테스트 제목2/)).toBeInTheDocument()
  })

  it('prevents duplicate clicks on the same item while in flight', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(
      costsResponse({ retry_queue: { pending_count: 1, items: [PENDING_ITEMS[0]] } })
    )
    const retrySpy = vi.spyOn(apiClient, 'postCostRetry').mockReturnValue(new Promise(() => {}))
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /재발행/ })).toBeEnabled())

    fireEvent.click(screen.getByRole('button', { name: /재발행/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /재시도 중/ })).toBeDisabled())
    fireEvent.click(screen.getByRole('button', { name: /재시도 중/ }))

    expect(retrySpy).toHaveBeenCalledTimes(1)
  })

  it('shows "대기 0건" and no list when the queue is empty', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(costsResponse())
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText('대기 0건')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /재발행/ })).not.toBeInTheDocument()
  })
})
