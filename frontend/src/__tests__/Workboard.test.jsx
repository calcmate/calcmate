import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import Workboard from '../pages/Workboard.jsx'
import * as apiClient from '../api/client.js'

// STEP S9: Kanban/Workboard React/FastAPI 이관 검증. 읽기 전용 — drag&drop이나
// 상태 변경 버튼이 절대 없어야 한다.

const SIX_COLUMNS = [
  { title: '🟡 수집중', count: 2, items: [{ id: '1', title: '수집중 글' }, { id: '2', title: '수집중 글2' }] },
  { title: '🔵 작성중', count: 1, items: [{ id: '3', title: '작성중 글' }] },
  { title: '🟠 검수중', count: 1, items: [{ id: '4', title: '검수중 글' }] },
  { title: '⏳ 발행대기', count: 0, items: [] },
  { title: '🟢 발행완료', count: 1, items: [{ id: '8', title: '발행완료 글' }] },
  { title: '🔴 오류', count: 0, items: [] },
]

function workboardResponse(columns = SIX_COLUMNS) {
  return { success: true, data: { columns }, error: null, request_id: 'w1' }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Workboard/Kanban (STEP S9)', () => {
  it('renders the page title and all 6 columns', async () => {
    vi.spyOn(apiClient, 'getWorkboard').mockResolvedValue(workboardResponse())
    render(<Workboard />)
    await waitFor(() => expect(screen.getByText('📋 작업 현황 보드')).toBeInTheDocument())
    for (const col of SIX_COLUMNS) {
      expect(screen.getByText(col.title)).toBeInTheDocument()
    }
  })

  it('renders cards with their titles inside the correct column', async () => {
    vi.spyOn(apiClient, 'getWorkboard').mockResolvedValue(workboardResponse())
    render(<Workboard />)
    await waitFor(() => expect(screen.getByText(/수집중 글2/)).toBeInTheDocument())
    expect(screen.getByText(/작성중 글/)).toBeInTheDocument()
    expect(screen.getByText(/검수중 글/)).toBeInTheDocument()
    expect(screen.getByText(/발행완료 글/)).toBeInTheDocument()
  })

  it('renders an empty column correctly (no crash, hint text shown)', async () => {
    vi.spyOn(apiClient, 'getWorkboard').mockResolvedValue(workboardResponse())
    render(<Workboard />)
    await waitFor(() => expect(screen.getAllByText('항목 없음').length).toBe(2)) // 발행대기, 오류
  })

  it('shows a loading state before the API resolves', () => {
    vi.spyOn(apiClient, 'getWorkboard').mockReturnValue(new Promise(() => {}))
    render(<Workboard />)
    expect(screen.getByText('불러오는 중...')).toBeInTheDocument()
  })

  it('shows the generic error UI on API failure', async () => {
    vi.spyOn(apiClient, 'getWorkboard').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<Workboard />)
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })

  it('shows the real column counts from the API, not hardcoded', async () => {
    vi.spyOn(apiClient, 'getWorkboard').mockResolvedValue(workboardResponse())
    render(<Workboard />)
    await waitFor(() => expect(screen.getByText('📋 작업 현황 보드')).toBeInTheDocument())
    expect(screen.getAllByText('2').length).toBeGreaterThan(0)
    expect(screen.getAllByText('1').length).toBeGreaterThan(0)
  })

  it('does not render any drag-and-drop or write action control (read-only)', async () => {
    vi.spyOn(apiClient, 'getWorkboard').mockResolvedValue(workboardResponse())
    render(<Workboard />)
    await waitFor(() => expect(screen.getByText('📋 작업 현황 보드')).toBeInTheDocument())
    // "새로고침" 버튼 하나만 있어야 한다 — 상태 변경/이동/삭제 버튼이 없어야 한다.
    const buttons = screen.getAllByRole('button')
    expect(buttons.length).toBe(1)
    expect(buttons[0]).toHaveTextContent('새로고침')
    // 카드가 draggable 속성을 갖지 않는지도 확인.
    const draggableEls = document.querySelectorAll('[draggable="true"]')
    expect(draggableEls.length).toBe(0)
  })
})
