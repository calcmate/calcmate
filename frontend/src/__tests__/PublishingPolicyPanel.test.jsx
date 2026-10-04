import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import PublishingPolicyPanel from '../components/PublishingPolicyPanel.jsx'
import * as apiClient from '../api/client.js'

// CALCMATE-BLOG-PUBLISHING-POLICY-FASTAPI-REACT-CONNECTION-IMPLEMENT-01.
// 실제 patchPublishingPolicy/patchAutoPublishing/getPublishingPolicyPreview는
// 이 파일의 어떤 테스트에서도 호출하지 않는다 — 항상 mock으로 대체한다
// (실제 config.yaml/DB/예약 변경 없음).

const ADMIN_USER = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER_USER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }

function emptyDay() {
  return { count: 0, time_ranges: [] }
}

const POLICY_OK = {
  success: true,
  data: {
    timezone: 'Asia/Seoul',
    weekdays: {
      mon: { count: 1, time_ranges: [{ start: '09:00', end: '18:00' }] },
      tue: emptyDay(), wed: emptyDay(), thu: emptyDay(), fri: emptyDay(), sat: emptyDay(), sun: emptyDay(),
    },
    max_pending_reservations: 10,
  },
  error: null,
  request_id: 'p1',
}

const AUTO_PUB_OFF = { success: true, data: { enabled: false }, error: null, request_id: 'a1' }

function mockLoads(user = ADMIN_USER) {
  vi.spyOn(apiClient, 'getPublishingPolicy').mockResolvedValue(POLICY_OK)
  vi.spyOn(apiClient, 'getAutoPublishing').mockResolvedValue(AUTO_PUB_OFF)
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(user)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('PublishingPolicyPanel — load', () => {
  it('renders the panel with all 7 weekday labels', async () => {
    mockLoads()
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByText('월요일')).toBeInTheDocument())
    for (const label of ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('renders the existing mon time_range from the loaded policy', async () => {
    mockLoads()
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByLabelText('pp-mon-0-start')).toHaveValue('09:00'))
    expect(screen.getByLabelText('pp-mon-0-end')).toHaveValue('18:00')
  })

  it('shows the generic error UI when a load call fails', async () => {
    vi.spyOn(apiClient, 'getPublishingPolicy').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    vi.spyOn(apiClient, 'getAutoPublishing').mockResolvedValue(AUTO_PUB_OFF)
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })
})

describe('PublishingPolicyPanel — per-post time_ranges (핵심 요구사항)', () => {
  it('increasing mon count to 3 creates exactly 3 independent time_range rows', async () => {
    mockLoads()
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByLabelText('pp-mon-0-start')).toBeInTheDocument())

    const monCount = screen.getAllByLabelText('발행 개수')[0]
    fireEvent.change(monCount, { target: { value: '3' } })

    await waitFor(() => expect(screen.getByLabelText('pp-mon-2-start')).toBeInTheDocument())
    expect(screen.getByLabelText('pp-mon-0-start')).toBeInTheDocument()
    expect(screen.getByLabelText('pp-mon-1-start')).toBeInTheDocument()
    // count가 3이므로 4번째(index 2 초과) range는 존재하지 않아야 한다
    expect(screen.queryByLabelText('pp-mon-3-start')).not.toBeInTheDocument()
  })

  it('decreasing count removes the extra time_range rows (not just hides them)', async () => {
    mockLoads()
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByLabelText('pp-mon-0-start')).toBeInTheDocument())

    const monCount = screen.getAllByLabelText('발행 개수')[0]
    fireEvent.change(monCount, { target: { value: '0' } })

    await waitFor(() => expect(screen.queryByLabelText('pp-mon-0-start')).not.toBeInTheDocument())
    expect(screen.getAllByText('발행 없음').length).toBeGreaterThan(0)
  })

  it('editing one range does not affect a sibling range on the same day', async () => {
    mockLoads()
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByLabelText('pp-mon-0-start')).toBeInTheDocument())

    fireEvent.change(screen.getAllByLabelText('발행 개수')[0], { target: { value: '2' } })
    await waitFor(() => expect(screen.getByLabelText('pp-mon-1-start')).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText('pp-mon-0-start'), { target: { value: '07:00' } })
    expect(screen.getByLabelText('pp-mon-0-start')).toHaveValue('07:00')
    // 2번째 range는 새로 추가된 기본값(09:00)을 그대로 유지해야 한다
    expect(screen.getByLabelText('pp-mon-1-start')).toHaveValue('09:00')
  })
})

describe('PublishingPolicyPanel — 저장', () => {
  it('calls patchPublishingPolicy with weekday->count->time_ranges[] structure (not a single range)', async () => {
    mockLoads()
    const patchSpy = vi.spyOn(apiClient, 'patchPublishingPolicy').mockResolvedValue({
      success: true, data: POLICY_OK.data, error: null, request_id: 'r1',
    })
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '💾 Publishing Policy 저장' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '💾 Publishing Policy 저장' }))

    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1))
    const payload = patchSpy.mock.calls[0][0]
    expect(payload.timezone).toBe('Asia/Seoul')
    expect(payload.weekdays.mon).toEqual({ count: 1, time_ranges: [{ start: '09:00', end: '18:00' }] })
    expect(payload.max_pending_reservations).toBe(10)
    await waitFor(() => expect(screen.getByText('✅ Publishing Policy 저장 완료')).toBeInTheDocument())
  })

  it('shows a validation error message when save fails, without pretending success', async () => {
    mockLoads()
    vi.spyOn(apiClient, 'patchPublishingPolicy').mockResolvedValue({
      success: false, data: null,
      error: { code: 'VALIDATION_ERROR', message: "PUBLISHING_POLICY 검증 실패: [...]" },
      request_id: null,
    })
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '💾 Publishing Policy 저장' })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '💾 Publishing Policy 저장' }))

    await waitFor(() => expect(screen.getByText(/검증 실패/)).toBeInTheDocument())
    expect(screen.queryByText('✅ Publishing Policy 저장 완료')).not.toBeInTheDocument()
  })

  it('disables save buttons for a non-admin viewer', async () => {
    mockLoads(VIEWER_USER)
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: '💾 Publishing Policy 저장' })).toBeDisabled())
    expect(screen.getByRole('button', { name: '💾 자동 발행 스위치 저장' })).toBeDisabled()
  })
})

describe('PublishingPolicyPanel — AUTO_PUBLISHING 토글', () => {
  it('toggling the switch and saving calls patchAutoPublishing with the new value', async () => {
    mockLoads()
    const patchSpy = vi.spyOn(apiClient, 'patchAutoPublishing').mockResolvedValue({
      success: true, data: { enabled: true }, error: null, request_id: 'r2',
    })
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /자동 발행 사용/ })).not.toBeChecked())

    fireEvent.click(screen.getByRole('checkbox', { name: /자동 발행 사용/ }))
    fireEvent.click(screen.getByRole('button', { name: '💾 자동 발행 스위치 저장' }))

    await waitFor(() => expect(patchSpy).toHaveBeenCalledWith({ enabled: true }))
    await waitFor(() => expect(screen.getByText(/저장 완료 · enabled=true/)).toBeInTheDocument())
  })
})

describe('PublishingPolicyPanel — 미리보기 (read-only)', () => {
  it('calls getPublishingPolicyPreview and renders the returned slots without creating a reservation', async () => {
    mockLoads()
    const previewSpy = vi.spyOn(apiClient, 'getPublishingPolicyPreview').mockResolvedValue({
      success: true,
      data: {
        timezone: 'Asia/Seoul',
        days: [
          { date: '2026-09-28', weekday: 'mon', slots: [{ scheduled_at: '2026-09-28T10:51:00+09:00', start: '09:00', end: '18:00' }] },
          { date: '2026-09-29', weekday: 'tue', slots: [] },
        ],
      },
      error: null,
      request_id: 'pv1',
    })
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /미리보기/ })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /미리보기/ }))

    await waitFor(() => expect(previewSpy).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(screen.getByText(/2026-09-28T10:51:00\+09:00/)).toBeInTheDocument())
  })

  it('shows an error message when preview fails', async () => {
    mockLoads()
    vi.spyOn(apiClient, 'getPublishingPolicyPreview').mockResolvedValue({
      success: false, data: null, error: { code: 'VALIDATION_ERROR', message: '미리보기 실패' }, request_id: null,
    })
    render(<PublishingPolicyPanel />)
    await waitFor(() => expect(screen.getByRole('button', { name: /미리보기/ })).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /미리보기/ }))

    await waitFor(() => expect(screen.getByText('⚠ 미리보기 실패')).toBeInTheDocument())
  })
})
