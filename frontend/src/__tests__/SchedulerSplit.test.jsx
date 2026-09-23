import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import CalculatorScheduler from '../pages/CalculatorScheduler.jsx'
import BlogScheduler from '../pages/BlogScheduler.jsx'
import App from '../App.jsx'
import * as apiClient from '../api/client.js'

// STEP V1-OPS-04: 계산기 Scheduler / 블로그 Scheduler 분리 검증.
// 기존 Scheduler.jsx(/scheduler)는 변경하지 않았으므로 그 화면의 테스트는
// 기존 파일(App.test.jsx)에서 그대로 유지된다 — 이 파일은 새로 추가한
// /calculator-scheduler, /blog-scheduler 두 페이지만 검증한다.

const SCHEDULER_STATUS = (name) => ({
  success: true,
  data: { name, enabled: name === 'blog', running: false, thread_alive: false },
  error: null,
  request_id: `r-${name}`,
})

const BLOG_CONFIG = {
  success: true,
  data: { enabled: true, mode: 'draft', publish_slots: [{ start: '06:00', end: '06:30' }], weekday_only: false },
  error: null,
  request_id: 'bc1',
}
const BLOG_TODAY = { success: true, data: { date: '2026-09-04', schedule: [] }, error: null, request_id: 'bt1' }
const BLOG_HISTORY = { success: true, data: { records: [] }, error: null, request_id: 'bh1' }

afterEach(() => {
  vi.restoreAllMocks()
})

describe('CalculatorScheduler page (/calculator-scheduler)', () => {
  it('renders only the Calculator Scheduler card, not Blog Scheduler or Content Sync', async () => {
    vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue(SCHEDULER_STATUS('calculator'))

    render(
      <MemoryRouter initialEntries={['/calculator-scheduler']}>
        <Routes>
          <Route path="/calculator-scheduler" element={<CalculatorScheduler />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByRole('heading', { name: /계산기 Scheduler/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Calculator Scheduler')).toBeInTheDocument())
    expect(screen.queryByText('Blog Scheduler')).not.toBeInTheDocument()
    expect(screen.queryByText('Content Sync')).not.toBeInTheDocument()
    // 조회 전용 — 실행/토글 버튼이 없어야 한다
    expect(screen.queryByRole('button', { name: /실행/ })).not.toBeInTheDocument()
  })

  it('shows API failure state without crashing', async () => {
    vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(
      <MemoryRouter initialEntries={['/calculator-scheduler']}>
        <Routes>
          <Route path="/calculator-scheduler" element={<CalculatorScheduler />} />
        </Routes>
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })
})

describe('BlogScheduler page (/blog-scheduler)', () => {
  const ONEROFF_EMPTY = { success: true, data: { reservations: [] }, error: null, request_id: 'r7' }
  const POLICY_OK = { success: true, data: { timezone: 'Asia/Seoul', weekdays: {}, max_pending_reservations: 10 }, error: null, request_id: 'r5' }
  const USER_ADMIN = { success: true, data: { role: 'admin' }, error: null, request_id: 'r6' }

  function mockBlogSchedulerDeps() {
    vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(SCHEDULER_STATUS('blog'))
    vi.spyOn(apiClient, 'getBlogSchedulerConfig').mockResolvedValue(BLOG_CONFIG)
    vi.spyOn(apiClient, 'getBlogSchedulerToday').mockResolvedValue(BLOG_TODAY)
    vi.spyOn(apiClient, 'getBlogSchedulerHistory').mockResolvedValue(BLOG_HISTORY)
    vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue(SCHEDULER_STATUS('content_sync'))
    vi.spyOn(apiClient, 'getBlogSchedulerOneoff').mockResolvedValue(ONEROFF_EMPTY)
    vi.spyOn(apiClient, 'getPublishingPolicy').mockResolvedValue(POLICY_OK)
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(USER_ADMIN)
  }

  it('renders Blog Scheduler panel (Save/Run controls) and Content Sync, not Calculator Scheduler', async () => {
    mockBlogSchedulerDeps()

    render(
      <MemoryRouter initialEntries={['/blog-scheduler']}>
        <Routes>
          <Route path="/blog-scheduler" element={<BlogScheduler />} />
        </Routes>
      </MemoryRouter>
    )

    expect(screen.getByRole('heading', { name: /블로그 스케줄/, level: 1 })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '블로그 스케줄', level: 3 })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '스케줄 저장' })).toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole('button', { name: '1회 생성' })).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('Content Sync')).toBeInTheDocument())
    expect(screen.queryByText('Calculator Scheduler')).not.toBeInTheDocument()
  })
})

describe('Navigation to the split scheduler pages via Sidebar links', () => {
  const ONEROFF_EMPTY = { success: true, data: { reservations: [] }, error: null, request_id: 'r7' }
  const POLICY_OK = { success: true, data: { timezone: 'Asia/Seoul', weekdays: {}, max_pending_reservations: 10 }, error: null, request_id: 'r5' }
  const USER_ADMIN = { success: true, data: { role: 'admin' }, error: null, request_id: 'r6' }

  function mockAllForApp() {
    vi.spyOn(apiClient, 'getHealth').mockResolvedValue({ success: true, data: { status: 'ok' }, error: null, request_id: 'h' })
    vi.spyOn(apiClient, 'getDashboardStatus').mockResolvedValue({ success: true, data: {}, error: null, request_id: 'd' })
    vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(SCHEDULER_STATUS('blog'))
    vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue(SCHEDULER_STATUS('calculator'))
    vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue(SCHEDULER_STATUS('content_sync'))
    vi.spyOn(apiClient, 'getBlogSchedulerConfig').mockResolvedValue(BLOG_CONFIG)
    vi.spyOn(apiClient, 'getBlogSchedulerToday').mockResolvedValue(BLOG_TODAY)
    vi.spyOn(apiClient, 'getBlogSchedulerHistory').mockResolvedValue(BLOG_HISTORY)
    vi.spyOn(apiClient, 'getBlogSchedulerOneoff').mockResolvedValue(ONEROFF_EMPTY)
    vi.spyOn(apiClient, 'getPublishingPolicy').mockResolvedValue(POLICY_OK)
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(USER_ADMIN)
  }

  it('direct URL access to /calculator-scheduler renders the calculator scheduler page', async () => {
    mockAllForApp()
    render(
      <MemoryRouter initialEntries={['/calculator-scheduler']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('heading', { name: /계산기 Scheduler/ })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Calculator Scheduler')).toBeInTheDocument())
  })

it('direct URL access to /blog-scheduler renders the blog scheduler page', async () => {
    mockAllForApp()
    render(
      <MemoryRouter initialEntries={['/blog-scheduler']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('heading', { name: /블로그 스케줄/, level: 1 })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '블로그 스케줄', level: 3 })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '스케줄 저장' })).toBeInTheDocument())
  })

  it('the old combined /scheduler route still works unchanged (existing feature preserved)', async () => {
    mockAllForApp()
    render(
      <MemoryRouter initialEntries={['/scheduler']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('heading', { name: 'Scheduler' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('블로그 스케줄')).toBeInTheDocument())
    expect(screen.getByText('Calculator Scheduler')).toBeInTheDocument()
    expect(screen.getByText('Content Sync')).toBeInTheDocument()
  })
})
