import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import BlogSchedulerPanel from '../components/BlogSchedulerPanel.jsx'
import * as apiClient from '../api/client.js'

const STATUS_ON = {
  success: true,
  data: { name: 'blog', enabled: true, running: false, thread_alive: true },
  error: null,
  request_id: 'r1',
}
const STATUS_OFF = {
  success: true,
  data: { name: 'blog', enabled: false, running: false, thread_alive: false },
  error: null,
  request_id: 'r1off',
}
const CONFIG_OK = {
  success: true,
  data: { enabled: true, mode: 'draft', publish_slots: [{ start: '06:00', end: '06:30' }], weekday_only: false },
  error: null,
  request_id: 'r2',
}
const TODAY_EMPTY = { success: true, data: { date: '2026-09-02', schedule: [] }, error: null, request_id: 'r3' }
const HISTORY_EMPTY = { success: true, data: { records: [] }, error: null, request_id: 'r4' }
const POLICY_OK = {
  success: true,
  data: { timezone: 'Asia/Seoul', weekdays: {}, max_pending_reservations: 10 },
  error: null,
  request_id: 'r5',
}
const USER_ADMIN = { success: true, data: { role: 'admin' }, error: null, request_id: 'r6' }
const USER_VIEWER = { success: true, data: { role: 'viewer' }, error: null, request_id: 'r7' }
const TOPICS_EMPTY = { success: true, data: { topics: [] }, error: null, request_id: 'r9' }

function mockLoads({ status = STATUS_ON, config = CONFIG_OK, policy = POLICY_OK, user = USER_ADMIN, topics = TOPICS_EMPTY } = {}) {
  vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(status)
  vi.spyOn(apiClient, 'getBlogSchedulerConfig').mockResolvedValue(config)
  vi.spyOn(apiClient, 'getBlogSchedulerToday').mockResolvedValue(TODAY_EMPTY)
  vi.spyOn(apiClient, 'getBlogSchedulerHistory').mockResolvedValue(HISTORY_EMPTY)
  vi.spyOn(apiClient, 'getBlogSchedulerOneoff').mockResolvedValue({ success: true, data: { reservations: [] }, error: null, request_id: 'r7' })
  vi.spyOn(apiClient, 'getPublishingPolicy').mockResolvedValue(policy)
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(user)
  vi.spyOn(apiClient, 'getTopicPool').mockResolvedValue(topics)
}

afterEach(() => {
  vi.restoreAllMocks()
})

function getRecurringRadio(value) {
  return screen.getAllByRole('radio', { name: new RegExp(value, 'i') }).find(r => r.name === 'recurring-mode')
}

function getOneoffRadio(value) {
  return screen.getAllByRole('radio', { name: new RegExp(value, 'i') }).find(r => r.name === 'oneoff-mode')
}

describe('BlogSchedulerPanel — load', () => {
  it('renders schedule toggle with current enabled state', async () => {
    mockLoads()
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /스케줄/ })).toBeChecked())
  })

  it('renders recurring mode radios with current config mode', async () => {
    mockLoads({ config: { ...CONFIG_OK, data: { ...CONFIG_OK.data, mode: 'draft' } } })
    render(<BlogSchedulerPanel />)
    await waitFor(() => {
      const draftRadio = getRecurringRadio('Draft')
      expect(draftRadio).toBeChecked()
      const publishRadio = getRecurringRadio('배포')
      expect(publishRadio).not.toBeChecked()
    })
  })

  it('renders 7 weekday headers', async () => {
    mockLoads()
    render(<BlogSchedulerPanel />)
    await waitFor(() => {
      expect(screen.getByText('월')).toBeInTheDocument()
      expect(screen.getByText('화')).toBeInTheDocument()
      expect(screen.getByText('수')).toBeInTheDocument()
      expect(screen.getByText('목')).toBeInTheDocument()
      expect(screen.getByText('금')).toBeInTheDocument()
      expect(screen.getByText('토')).toBeInTheDocument()
      expect(screen.getByText('일')).toBeInTheDocument()
    })
  })

  it('shows the generic error UI when any load call fails', async () => {
    vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(STATUS_ON)
    vi.spyOn(apiClient, 'getBlogSchedulerConfig').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    vi.spyOn(apiClient, 'getBlogSchedulerToday').mockResolvedValue(TODAY_EMPTY)
    vi.spyOn(apiClient, 'getBlogSchedulerHistory').mockResolvedValue(HISTORY_EMPTY)
    vi.spyOn(apiClient, 'getBlogSchedulerOneoff').mockResolvedValue({ success: true, data: { reservations: [] }, error: null, request_id: 'r7' })
    vi.spyOn(apiClient, 'getPublishingPolicy').mockResolvedValue(POLICY_OK)
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(USER_ADMIN)
    vi.spyOn(apiClient, 'getTopicPool').mockResolvedValue(TOPICS_EMPTY)
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })
})

describe('BlogSchedulerPanel — Save', () => {
  it('calls patchBlogSchedulerConfig and patchPublishingPolicy with current form values', async () => {
    mockLoads()
    const blogPatchSpy = vi.spyOn(apiClient, 'patchBlogSchedulerConfig').mockResolvedValue({
      success: true, data: CONFIG_OK.data, error: null, request_id: 'r5',
    })
    const policyPatchSpy = vi.spyOn(apiClient, 'patchPublishingPolicy').mockResolvedValue({
      success: true, data: POLICY_OK.data, error: null, request_id: 'r6',
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '스케줄 저장' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '스케줄 저장' }))

    await waitFor(() => expect(blogPatchSpy).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(policyPatchSpy).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByText('스케줄이 저장되었습니다.')).toBeInTheDocument())
  })

  it('shows an error message when save fails, without pretending success', async () => {
    mockLoads()
    vi.spyOn(apiClient, 'patchBlogSchedulerConfig').mockResolvedValue({
      success: false, data: null, error: { code: 'VALIDATION_ERROR', message: 'slot start must be before end' }, request_id: null,
    })
    vi.spyOn(apiClient, 'patchPublishingPolicy').mockResolvedValue({
      success: true, data: POLICY_OK.data, error: null, request_id: 'r6',
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '스케줄 저장' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '스케줄 저장' }))

    await waitFor(() => expect(screen.getByText(/slot start must be before end/)).toBeInTheDocument())
    expect(screen.queryByText('스케줄이 저장되었습니다.')).not.toBeInTheDocument()
  })
})

describe('BlogSchedulerPanel — Schedule OFF + One-off', () => {
  it('enables 1회 생성 button regardless of schedule enabled state', async () => {
    mockLoads({ status: STATUS_OFF })
    render(<BlogSchedulerPanel />)
    await waitFor(() => {
      const draftRadio = getRecurringRadio('Draft')
      expect(draftRadio).toBeChecked()
      const publishRadio = getRecurringRadio('배포')
      expect(publishRadio).not.toBeChecked()
    })
    await waitFor(() => expect(screen.getByRole('button', { name: '1회 생성' })).toBeEnabled())
  })
})

describe('BlogSchedulerPanel — 1회 생성 (runBlogSchedulerOnceOneoff)', () => {
  it('calls runBlogSchedulerOnceOneoff with selected mode=draft exactly once', async () => {
    mockLoads()
    const runSpy = vi.spyOn(apiClient, 'runBlogSchedulerOnceOneoff').mockResolvedValue({
      success: true, data: { produced: 1, results: [{ status: 'SUCCESS' }] }, error: null, request_id: 'r7',
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '1회 생성' })).toBeEnabled())

    fireEvent.click(screen.getByRole('button', { name: '1회 생성' }))

    await waitFor(() => expect(runSpy).toHaveBeenCalledTimes(1))
    expect(runSpy).toHaveBeenCalledWith('draft')
    await waitFor(() => expect(screen.getByText(/1회 생성 완료 \(생성 1건\)/)).toBeInTheDocument())
  })

  it('calls runBlogSchedulerOnceOneoff with mode=publish when selected', async () => {
    mockLoads()
    const runSpy = vi.spyOn(apiClient, 'runBlogSchedulerOnceOneoff').mockResolvedValue({
      success: true, data: { produced: 1, results: [{ status: 'SUCCESS' }] }, error: null, request_id: 'r8',
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '1회 생성' })).toBeEnabled())

    const publishRadio = getOneoffRadio('배포')
    fireEvent.click(publishRadio)
    await waitFor(() => expect(publishRadio).toBeChecked())

    fireEvent.click(screen.getByRole('button', { name: '1회 생성' }))

    await waitFor(() => expect(runSpy).toHaveBeenCalledTimes(1))
    expect(runSpy).toHaveBeenCalledWith('publish')
    await waitFor(() => expect(screen.getByText(/1회 생성 완료 \(생성 1건\)/)).toBeInTheDocument())
  })

  it('shows an error message when run-once fails without claiming success', async () => {
    mockLoads()
    vi.spyOn(apiClient, 'runBlogSchedulerOnceOneoff').mockResolvedValue({
      success: false, data: null, error: { code: 'LOCK_CONFLICT', message: '다른 실행이 진행 중입니다' }, request_id: null,
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '1회 생성' })).toBeEnabled())

    fireEvent.click(screen.getByRole('button', { name: '1회 생성' }))

    await waitFor(() => expect(screen.getByText(/다른 실행이 진행 중입니다/)).toBeInTheDocument())
    expect(screen.queryByText(/1회 생성 완료/)).not.toBeInTheDocument()
  })
})

// CALCMATE-DASHBOARD-SCHEDULE-UI-API-FIX-IMPLEMENT-01 — R3(source 표시) / L1(오류 표시)
const DEFAULT_NOTICE = /저장된 정책이 없어 기본값을 표시하고 있습니다/
const BLOG_SAVE_OK = { success: true, data: CONFIG_OK.data, error: null, request_id: 's1' }
const POLICY_SAVE_OK = { success: true, data: POLICY_OK.data, error: null, request_id: 's2' }

async function renderAndSave({ blog, policy }) {
  mockLoads()
  vi.spyOn(apiClient, 'patchBlogSchedulerConfig').mockResolvedValue(blog)
  vi.spyOn(apiClient, 'patchPublishingPolicy').mockResolvedValue(policy)
  render(<BlogSchedulerPanel />)
  await waitFor(() => expect(screen.getByRole('button', { name: '스케줄 저장' })).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: '스케줄 저장' }))
}

describe('BlogSchedulerPanel — policy source (R3)', () => {
  it('shows the default-policy notice when source=default, without saving anything', async () => {
    mockLoads({ policy: { ...POLICY_OK, data: { ...POLICY_OK.data, source: 'default' } } })
    const blogPatch = vi.spyOn(apiClient, 'patchBlogSchedulerConfig')
    const policyPatch = vi.spyOn(apiClient, 'patchPublishingPolicy')
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByText(DEFAULT_NOTICE)).toBeInTheDocument())
    expect(blogPatch).not.toHaveBeenCalled()
    expect(policyPatch).not.toHaveBeenCalled()
  })

  it('does not show the notice when source=config', async () => {
    mockLoads({ policy: { ...POLICY_OK, data: { ...POLICY_OK.data, source: 'config' } } })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '스케줄 저장' })).toBeInTheDocument())
    expect(screen.queryByText(DEFAULT_NOTICE)).not.toBeInTheDocument()
  })
})

describe('BlogSchedulerPanel — save error reporting (L1)', () => {
  it('shows 422 detail-array messages with the failing side label', async () => {
    await renderAndSave({
      blog: BLOG_SAVE_OK,
      policy: { detail: [{ loc: ['body', 'weekdays'], msg: 'Field required', type: 'missing' }] },
    })
    await waitFor(() => expect(screen.getByText(/발행 정책: Field required/)).toBeInTheDocument())
    expect(screen.queryByText('스케줄이 저장되었습니다.')).not.toBeInTheDocument()
    expect(apiClient.patchBlogSchedulerConfig).not.toHaveBeenCalled()   // 정책 실패 → blog PATCH 없음
  })

  it.each([
    ['401', 'Unauthorized'],
    ['403', 'Forbidden'],
    ['404', 'Not Found'],
  ])('shows the %s detail instead of an empty error', async (_code, detail) => {
    await renderAndSave({ blog: { detail }, policy: { detail } })
    await waitFor(() =>
      expect(screen.getByText(new RegExp(`발행 정책: ${detail} \\(반복 스케줄은 저장하지 않았습니다\\)`))).toBeInTheDocument()
    )
    expect(apiClient.patchBlogSchedulerConfig).not.toHaveBeenCalled()
    expect(screen.queryByText(/일부만 저장되었습니다/)).not.toBeInTheDocument()
    expect(screen.queryByText('스케줄이 저장되었습니다.')).not.toBeInTheDocument()
  })

  // SAVE-ORDER-FIX-01 TEST A: 정책 실패 시 blog/config PATCH 자체가 없어야 한다(count ≥ 1에서도)
  it('does not call blog/config when publishing-policy fails, even with count >= 1', async () => {
    mockLoads()
    const blogPatch = vi.spyOn(apiClient, 'patchBlogSchedulerConfig').mockResolvedValue(BLOG_SAVE_OK)
    vi.spyOn(apiClient, 'patchPublishingPolicy').mockResolvedValue({
      success: false, data: null, error: { code: 'VALIDATION_ERROR', message: 'count mismatch' }, request_id: null,
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '스케줄 저장' })).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('월 개수'), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: '스케줄 저장' }))

    await waitFor(() =>
      expect(screen.getByText(/발행 정책: count mismatch \(반복 스케줄은 저장하지 않았습니다\)/)).toBeInTheDocument()
    )
    expect(blogPatch).not.toHaveBeenCalled()
    expect(screen.queryByText('스케줄이 저장되었습니다.')).not.toBeInTheDocument()
    expect(apiClient.getPublishingPolicy).toHaveBeenCalledTimes(1)   // load() 재호출 없음
    expect(screen.getByLabelText('월 개수').value).toBe('1')          // 편집값 유지
  })

  // SAVE-ORDER-FIX-01 TEST B: 정책 성공 + blog 실패 → 부분 저장, load() 없음, 편집값 유지
  it('reports a partial save when policy succeeds but blog/config fails, without reloading', async () => {
    mockLoads()
    vi.spyOn(apiClient, 'patchPublishingPolicy').mockResolvedValue(POLICY_SAVE_OK)
    vi.spyOn(apiClient, 'patchBlogSchedulerConfig').mockResolvedValue({ detail: 'Not Found' })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '스케줄 저장' })).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('월 개수'), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: '스케줄 저장' }))

    await waitFor(() =>
      expect(screen.getByText(/일부만 저장되었습니다 \(발행 정책 저장됨\)\. 반복 스케줄: Not Found/)).toBeInTheDocument()
    )
    expect(screen.queryByText('스케줄이 저장되었습니다.')).not.toBeInTheDocument()
    expect(apiClient.getPublishingPolicy).toHaveBeenCalledTimes(1)
    expect(screen.getByLabelText('월 개수').value).toBe('1')
  })

  it('keeps showing network errors', async () => {
    await renderAndSave({
      blog: { success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'Failed to fetch' }, request_id: null },
      policy: POLICY_SAVE_OK,
    })
    await waitFor(() => expect(screen.getByText(/반복 스케줄: Failed to fetch/)).toBeInTheDocument())
  })

  it('shows the success message only when both PATCHes succeed (policy first, then blog, then reload)', async () => {
    await renderAndSave({ blog: BLOG_SAVE_OK, policy: POLICY_SAVE_OK })
    await waitFor(() => expect(screen.getByText('스케줄이 저장되었습니다.')).toBeInTheDocument())
    const policyOrder = apiClient.patchPublishingPolicy.mock.invocationCallOrder[0]
    const blogOrder = apiClient.patchBlogSchedulerConfig.mock.invocationCallOrder[0]
    expect(policyOrder).toBeLessThan(blogOrder)
    await waitFor(() => expect(apiClient.getPublishingPolicy).toHaveBeenCalledTimes(2))   // load() 재호출
  })
})

// CALCMATE-STREAMLIT-RESERVATION-API-IMPLEMENT-01: Topic 예약 / Planner
describe('BlogSchedulerPanel — Topic 예약 (createOneoffReservation)', () => {
  const TOPICS_ONE = {
    success: true,
    data: { topics: [{ topic_id: 'topic_1', title: '테스트 토픽', status: 'approved' }] },
    error: null, request_id: 'r9',
  }

  it('renders approved topics from getTopicPool in the select', async () => {
    mockLoads({ topics: TOPICS_ONE })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByText('테스트 토픽')).toBeInTheDocument())
  })

  it('shows a hint when there are no approved topics', async () => {
    mockLoads()
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByText('현재 승인된(approved) Topic이 없습니다.')).toBeInTheDocument())
  })

  it('calls createOneoffReservation with date/time/mode/topicId and shows the result', async () => {
    mockLoads({ topics: TOPICS_ONE })
    const createSpy = vi.spyOn(apiClient, 'createOneoffReservation').mockResolvedValue({
      success: true, data: { id: 'oneoff_1', scheduled_at: '2026-10-01T14:00:00+09:00', mode: 'draft', duplicate: false },
      error: null, request_id: 'r10',
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByText('테스트 토픽')).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText('예약 날짜'), { target: { value: '2026-10-01' } })
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'topic_1' } })
    fireEvent.click(screen.getByRole('button', { name: '📌 1회성 예약 추가' }))

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1))
    expect(createSpy).toHaveBeenCalledWith({
      scheduledAt: '2026-10-01T14:00:00+09:00', mode: 'draft', topicId: 'topic_1',
    })
    await waitFor(() => expect(screen.getByText(/예약 추가됨/)).toBeInTheDocument())
  })

  it('requires a date before submitting', async () => {
    mockLoads()
    const createSpy = vi.spyOn(apiClient, 'createOneoffReservation')
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '📌 1회성 예약 추가' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '📌 1회성 예약 추가' }))

    await waitFor(() => expect(screen.getByText(/예약 날짜를 입력하세요/)).toBeInTheDocument())
    expect(createSpy).not.toHaveBeenCalled()
  })

  it('shows a duplicate notice instead of claiming a new reservation was added', async () => {
    mockLoads()
    vi.spyOn(apiClient, 'createOneoffReservation').mockResolvedValue({
      success: true, data: { id: 'oneoff_1', scheduled_at: '2026-10-01T14:00:00+09:00', mode: 'draft', duplicate: true },
      error: null, request_id: 'r11',
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '📌 1회성 예약 추가' })).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('예약 날짜'), { target: { value: '2026-10-01' } })

    fireEvent.click(screen.getByRole('button', { name: '📌 1회성 예약 추가' }))

    await waitFor(() => expect(screen.getByText(/동일 시각·모드의 대기 중 예약이 이미 있습니다/)).toBeInTheDocument())
  })

  it('shows an error message when reservation creation fails', async () => {
    mockLoads()
    vi.spyOn(apiClient, 'createOneoffReservation').mockResolvedValue({
      success: false, data: null, error: { code: 'VALIDATION_ERROR', message: '허용되지 않는 mode' }, request_id: null,
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '📌 1회성 예약 추가' })).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('예약 날짜'), { target: { value: '2026-10-01' } })

    fireEvent.click(screen.getByRole('button', { name: '📌 1회성 예약 추가' }))

    await waitFor(() => expect(screen.getByText(/허용되지 않는 mode/)).toBeInTheDocument())
  })
})

describe('BlogSchedulerPanel — Planner 실행 (runPlannerOnce)', () => {
  it('calls runPlannerOnce and shows the scheduled count', async () => {
    mockLoads()
    const runSpy = vi.spyOn(apiClient, 'runPlannerOnce').mockResolvedValue({
      success: true, data: { scheduled: 2, reason: '', results: [] }, error: null, request_id: 'r12',
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '▶ Planner 지금 실행' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '▶ Planner 지금 실행' }))

    await waitFor(() => expect(runSpy).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByText('2건 예약 생성됨')).toBeInTheDocument())
  })

  it('shows the reason when no reservation was scheduled', async () => {
    mockLoads()
    vi.spyOn(apiClient, 'runPlannerOnce').mockResolvedValue({
      success: true, data: { scheduled: 0, reason: 'no_approved_topics', results: [] }, error: null, request_id: 'r13',
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '▶ Planner 지금 실행' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '▶ Planner 지금 실행' }))

    await waitFor(() => expect(screen.getByText(/예약 생성 없음 — no_approved_topics/)).toBeInTheDocument())
  })

  it('shows an error message when the planner run fails', async () => {
    mockLoads()
    vi.spyOn(apiClient, 'runPlannerOnce').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'Failed to fetch' }, request_id: null,
    })
    render(<BlogSchedulerPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '▶ Planner 지금 실행' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '▶ Planner 지금 실행' }))

    await waitFor(() => expect(screen.getByText(/Failed to fetch/)).toBeInTheDocument())
  })
})