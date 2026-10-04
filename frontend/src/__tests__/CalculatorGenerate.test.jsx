import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { GenerateCalculatorPanel } from '../pages/Calculators.jsx'
import * as apiClient from '../api/client.js'

// STEP 4-H-6: 폴링 간격을 짧게 줘 실제 시간 기반 폴링을 빠르게 검증한다
// (fake timer 없이 실제 setTimeout을 그대로 사용 — 기존 테스트 스위트 관례 유지).
const FAST_POLL_MS = 5

const AUTH_VIEWER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u1' }
const AUTH_ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u2' }

function jobResponse(overrides) {
  return {
    success: true,
    data: {
      job_id: 'job-1', status: 'running', slug_or_name: '테스트계산기',
      created_at: 't0', started_at: 't0', finished_at: null, error: null, result: null,
      ...overrides,
    },
    error: null, request_id: 'j',
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

function renderPanel(props = {}) {
  return render(<GenerateCalculatorPanel pollIntervalMs={FAST_POLL_MS} pollMaxAttempts={5} {...props} />)
}

async function fillAndSubmit(name = '테스트계산기') {
  fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: name } })
  fireEvent.click(screen.getByRole('button', { name: /생성 시작/ }))
}

describe('GenerateCalculatorPanel (STEP 4-H-6)', () => {
  it('viewer sees the form disabled', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_VIEWER)
    renderPanel()
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    expect(screen.getByLabelText('계산기명 *')).toBeDisabled()
    expect(screen.getByRole('button', { name: /생성 시작/ })).toBeDisabled()
  })

  // ── UI Test 1 — 정상 요청 ────────────────────────────────────────────
  it('normal flow: submit → job_id → polling → succeeded', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    const postSpy = vi.spyOn(apiClient, 'postCalculatorGenerate').mockResolvedValue({
      status: 200,
      body: { success: true, data: { job_id: 'job-1', status: 'queued' }, error: null, request_id: 'g1' },
    })
    let calls = 0
    vi.spyOn(apiClient, 'getCalculatorGenerationJob').mockImplementation(async () => {
      calls += 1
      if (calls < 2) return jobResponse({ status: 'running' })
      return jobResponse({
        status: 'succeeded',
        result: { slug: 'test-calc', name: '테스트계산기', message: '✅ 저장 완료' },
      })
    })

    renderPanel()
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await fillAndSubmit()

    expect(postSpy).toHaveBeenCalledWith({
      name: '테스트계산기', category: '', description: '', tier: 2,
    })

    await waitFor(() => expect(screen.getByText('✅ 생성 완료')).toBeInTheDocument())
    expect(screen.getByText('test-calc')).toBeInTheDocument()
    expect(screen.getByText('✅ 저장 완료')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /생성 시작/ })).toBeEnabled()
  })

  // ── UI Test 2 — 409 ──────────────────────────────────────────────────
  it('409 shows a clear busy message and does not start polling', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'postCalculatorGenerate').mockResolvedValue({
      status: 409,
      body: { detail: '이미 생성 작업이 실행 중입니다. 완료 후 다시 시도하세요.' },
    })
    const jobSpy = vi.spyOn(apiClient, 'getCalculatorGenerationJob').mockResolvedValue(jobResponse())

    renderPanel()
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await fillAndSubmit()

    await waitFor(
      () => expect(screen.getByText(/현재 다른 계산기 생성 작업이 진행 중입니다\./)).toBeInTheDocument(),
      { timeout: 3000 }
    )
    expect(jobSpy).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /생성 시작/ })).toBeEnabled()
  })

  // ── UI Test 3 — failed ───────────────────────────────────────────────
  it('failed job shows the error and stops polling', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'postCalculatorGenerate').mockResolvedValue({
      status: 200,
      body: { success: true, data: { job_id: 'job-1', status: 'queued' }, error: null, request_id: 'g1' },
    })
    const jobSpy = vi.spyOn(apiClient, 'getCalculatorGenerationJob').mockResolvedValue(
      jobResponse({ status: 'failed', error: 'AI 호출 실패(mock)' })
    )

    renderPanel()
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await fillAndSubmit()

    await waitFor(() => expect(screen.getByText(/AI 호출 실패/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /생성 시작/ })).toBeEnabled()

    const callsAfterFailure = jobSpy.mock.calls.length
    await new Promise((r) => setTimeout(r, FAST_POLL_MS * 3))
    expect(jobSpy.mock.calls.length).toBe(callsAfterFailure) // 종료 후 더 이상 폴링하지 않음
  })

  // ── UI Test 4 — polling timeout ──────────────────────────────────────
  it('polling stops after max attempts and shows a timeout message', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'postCalculatorGenerate').mockResolvedValue({
      status: 200,
      body: { success: true, data: { job_id: 'job-1', status: 'queued' }, error: null, request_id: 'g1' },
    })
    const jobSpy = vi.spyOn(apiClient, 'getCalculatorGenerationJob').mockResolvedValue(
      jobResponse({ status: 'running' }) // 영원히 running
    )

    renderPanel({ pollMaxAttempts: 3 })
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await fillAndSubmit()

    await waitFor(
      () => expect(screen.getByText(/작업 상태 확인 시간이 초과되었습니다\./)).toBeInTheDocument(),
      { timeout: 4000 }
    )
    expect(screen.getByRole('button', { name: /생성 시작/ })).toBeEnabled()

    const callsAtTimeout = jobSpy.mock.calls.length
    await new Promise((r) => setTimeout(r, FAST_POLL_MS * 5))
    expect(jobSpy.mock.calls.length).toBe(callsAtTimeout) // timeout 후 polling 종료(무한 반복 아님)
  })

  // ── UI Test 5 — 중복 클릭 방지 ─────────────────────────────────────────
  it('prevents duplicate POST from rapid re-clicks while submitting', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    let resolvePost
    const postSpy = vi.spyOn(apiClient, 'postCalculatorGenerate').mockReturnValue(
      new Promise((resolve) => { resolvePost = resolve })
    )

    renderPanel()
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '중복클릭계산기' } })
    const btn = screen.getByRole('button', { name: /생성 시작/ })
    fireEvent.click(btn)
    await waitFor(() => expect(btn).toBeDisabled())
    fireEvent.click(btn) // 비활성화 상태에서의 재클릭은 무시되어야 한다

    resolvePost({
      status: 200,
      body: { success: true, data: { job_id: 'job-1', status: 'succeeded' }, error: null, request_id: 'g1' },
    })
    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(1))
  })

  // ── UI Test 6 — secret 보호 ───────────────────────────────────────────
  it('never renders leaked secret strings from the backend response', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'postCalculatorGenerate').mockResolvedValue({
      status: 200,
      body: { success: true, data: { job_id: 'job-1', status: 'queued' }, error: null, request_id: 'g1' },
    })
    const SECRET = 'sk-should-never-render-4h6'
    vi.spyOn(apiClient, 'getCalculatorGenerationJob').mockResolvedValue(
      jobResponse({
        status: 'succeeded',
        result: { slug: 'safe-calc', name: '안전계산기', message: '저장 완료' },
        // 백엔드가 실수로라도 secret을 흘려도(가정) job 자체에는 없는 것이 정상이지만,
        // UI가 result 외 필드를 그대로 렌더링하지 않는지까지 확인하기 위해 API key
        // 유사 필드를 job 응답에 얹어 본다 — UI는 result.slug/name/message만 그린다.
        api_key_should_not_render: SECRET,
      })
    )

    const { container } = renderPanel()
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await fillAndSubmit()

    await waitFor(() => expect(screen.getByText('✅ 생성 완료')).toBeInTheDocument())
    expect(container.innerHTML).not.toContain(SECRET)
  })
})
