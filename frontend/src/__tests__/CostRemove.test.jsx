import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import CostPanel from '../components/CostPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP S6: Retry Queue Manual Remove React/FastAPI 이관 검증.
// 실제 postCostRemove는 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상
// mock으로 대체한다(실제 data/retry/pending_posts.json 변경 없음).

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

const PENDING_ITEMS = [
  { id: 'p1', title: '테스트 제목1', created_at: '2026-09-05T10:00', error: '연결 실패' },
  { id: 'p2', title: '테스트 제목2', created_at: '2026-09-05T11:00', error: '타임아웃' },
]

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Retry Queue 수동 제거 (STEP S6)', () => {
  it('renders a Remove button alongside Retry for each pending item', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(
      costsResponse({ retry_queue: { pending_count: 2, items: PENDING_ITEMS } })
    )
    render(<CostPanel />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: /^🗑 제거$/ }).length).toBe(2))
    expect(screen.getAllByRole('button', { name: /^🔁 재발행$/ }).length).toBe(2)
  })

  it('disables the Remove button for a viewer', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(
      costsResponse({ retry_queue: { pending_count: 1, items: [PENDING_ITEMS[0]] } })
    )
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /^🗑 제거$/ })).toBeDisabled())
  })

  it('clicking Remove shows loading only for that item, calls the API, and reloads on success', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const getCostsSpy = vi.spyOn(apiClient, 'getCosts')
    getCostsSpy.mockResolvedValueOnce(
      costsResponse({ retry_queue: { pending_count: 2, items: PENDING_ITEMS } })
    )
    let resolveRemove
    const removeSpy = vi.spyOn(apiClient, 'postCostRemove').mockReturnValue(new Promise((res) => { resolveRemove = res }))

    render(<CostPanel />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: /^🗑 제거$/ }).length).toBe(2))

    const removeButtons = screen.getAllByRole('button', { name: /^🗑 제거$/ })
    fireEvent.click(removeButtons[0])

    await waitFor(() => expect(screen.getByRole('button', { name: /제거 중/ })).toBeDisabled())
    // 두 번째 item은 여전히 정상 "제거" 버튼으로 남아 있어야 한다(독립적 loading).
    expect(screen.getAllByRole('button', { name: /^🗑 제거$/ }).length).toBe(1)

    getCostsSpy.mockResolvedValueOnce(
      costsResponse({ retry_queue: { pending_count: 1, items: [PENDING_ITEMS[1]] } })
    )
    resolveRemove({ success: true, data: { ok: true, message: '제거됨' }, error: null, request_id: 'rm1' })

    // 성공 메시지는 item이 사라진 뒤에도 남아 있어야 한다(배너, S5와 동일한 설계).
    await waitFor(() => expect(screen.getByText(/제거됨/)).toBeInTheDocument())
    expect(removeSpy).toHaveBeenCalledWith('p1')
    // p1은 최신 재조회 결과에서 빠졌으므로 목록에서 사라져야 한다.
    await waitFor(() => expect(screen.queryByText(/테스트 제목1/)).not.toBeInTheDocument())
    expect(screen.getByText(/테스트 제목2/)).toBeInTheDocument()
  })

  it('shows a per-item error and keeps the item in the list on failure', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(
      costsResponse({ retry_queue: { pending_count: 2, items: PENDING_ITEMS } })
    )
    vi.spyOn(apiClient, 'postCostRemove').mockResolvedValue({
      success: true, data: { ok: false, message: '제거 실패: 파일 잠김' }, error: null, request_id: 'rm2',
    })
    render(<CostPanel />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: /^🗑 제거$/ }).length).toBe(2))

    fireEvent.click(screen.getAllByRole('button', { name: /^🗑 제거$/ })[0])
    await waitFor(() => expect(screen.getByText(/제거 실패/)).toBeInTheDocument())
    // 실패했으므로 두 item 모두 그대로 남아 있어야 한다(재조회 안 함).
    expect(screen.getByText(/테스트 제목1/)).toBeInTheDocument()
    expect(screen.getByText(/테스트 제목2/)).toBeInTheDocument()
  })

  it('prevents duplicate clicks on the same item while removal is in flight', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(
      costsResponse({ retry_queue: { pending_count: 1, items: [PENDING_ITEMS[0]] } })
    )
    const removeSpy = vi.spyOn(apiClient, 'postCostRemove').mockReturnValue(new Promise(() => {}))
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /^🗑 제거$/ })).toBeEnabled())

    fireEvent.click(screen.getByRole('button', { name: /^🗑 제거$/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /제거 중/ })).toBeDisabled())
    fireEvent.click(screen.getByRole('button', { name: /제거 중/ }))

    expect(removeSpy).toHaveBeenCalledTimes(1)
  })

  it('disables both Retry and Remove for an item while either is in flight', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(
      costsResponse({ retry_queue: { pending_count: 1, items: [PENDING_ITEMS[0]] } })
    )
    vi.spyOn(apiClient, 'postCostRemove').mockReturnValue(new Promise(() => {}))
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /^🗑 제거$/ })).toBeEnabled())

    fireEvent.click(screen.getByRole('button', { name: /^🗑 제거$/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /재발행/ })).toBeDisabled())
  })

  it('independently removing two different items does not interfere with each other', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    const getCostsSpy = vi.spyOn(apiClient, 'getCosts')
    getCostsSpy.mockResolvedValueOnce(
      costsResponse({ retry_queue: { pending_count: 2, items: PENDING_ITEMS } })
    )
    const removeSpy = vi.spyOn(apiClient, 'postCostRemove').mockImplementation((id) =>
      Promise.resolve({ success: true, data: { ok: true, message: `제거됨(${id})` }, error: null, request_id: id })
    )
    getCostsSpy.mockResolvedValue(costsResponse({ retry_queue: { pending_count: 0, items: [] } }))

    render(<CostPanel />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: /^🗑 제거$/ }).length).toBe(2))

    const buttons = screen.getAllByRole('button', { name: /^🗑 제거$/ })
    fireEvent.click(buttons[0])
    fireEvent.click(buttons[1])

    await waitFor(() => expect(removeSpy).toHaveBeenCalledTimes(2))
    expect(removeSpy).toHaveBeenCalledWith('p1')
    expect(removeSpy).toHaveBeenCalledWith('p2')
  })

  it('does not render the Remove button when the queue is empty', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getCosts').mockResolvedValue(costsResponse())
    render(<CostPanel />)
    await waitFor(() => expect(screen.getByText('대기 0건')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /제거/ })).not.toBeInTheDocument()
  })
})
