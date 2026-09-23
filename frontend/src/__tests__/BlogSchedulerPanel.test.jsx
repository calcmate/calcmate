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

function mockLoads({ status = STATUS_ON, config = CONFIG_OK, policy = POLICY_OK, user = USER_ADMIN } = {}) {
  vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(status)
  vi.spyOn(apiClient, 'getBlogSchedulerConfig').mockResolvedValue(config)
  vi.spyOn(apiClient, 'getBlogSchedulerToday').mockResolvedValue(TODAY_EMPTY)
  vi.spyOn(apiClient, 'getBlogSchedulerHistory').mockResolvedValue(HISTORY_EMPTY)
  vi.spyOn(apiClient, 'getBlogSchedulerOneoff').mockResolvedValue({ success: true, data: { reservations: [] }, error: null, request_id: 'r7' })
  vi.spyOn(apiClient, 'getPublishingPolicy').mockResolvedValue(policy)
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(user)
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