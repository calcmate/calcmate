import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { GenerateCalculatorPanel } from '../pages/Calculators.jsx'
import * as apiClient from '../api/client.js'

// STEP S2: Contract Prefill / Instance 복원 React UI 연결 검증.
// P0-5에서 이미 만들어진 FastAPI endpoint(get_contract_prefill/get_contract_instance)를
// React가 실제로 호출하고, 응답 값을 폼에 반영하는지 확인한다. 또한 legal_refs/
// scope_exclusions가 더 이상 빈 배열로 하드코딩되지 않고 generation 요청에 그대로
// 전달되는지 확인한다(이번 STEP의 핵심 버그 수정).

const AUTH_ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u2' }

afterEach(() => {
  vi.restoreAllMocks()
})

async function switchToModeB() {
  await waitFor(() => expect(screen.getByLabelText(/Mode B/)).toBeInTheDocument())
  fireEvent.click(screen.getByLabelText(/Mode B/))
  await waitFor(() => expect(screen.getByLabelText('확정 slug *')).toBeInTheDocument())
}

async function fillSlug(value = 'annual-leave-remaining') {
  fireEvent.change(screen.getByLabelText('확정 slug *'), { target: { value } })
}

describe('Contract Prefill / Instance 복원 (STEP S2)', () => {
  it('calls getContractPrefill() with the entered slug and fills the form from the real response fields', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    const prefillSpy = vi.spyOn(apiClient, 'getContractPrefill').mockResolvedValue({
      success: true,
      data: {
        found: true, entry: {}, slug: 'annual-leave-remaining', name: '연차 잔여일 계산기', category: '노무/급여',
        input_fields: ['years_of_service', 'used_days'], output_fields: ['total_days', 'remaining_days'],
        scope_exclusions: ['근로기준법 제60조 제1항 인용 금지'], legal_refs: ['labor_standards_act_60'],
        message: '',
      },
      error: null, request_id: 'p1',
    })

    render(<GenerateCalculatorPanel />)
    await switchToModeB()
    await fillSlug()
    fireEvent.click(screen.getByRole('button', { name: '📥 Registry에서 불러오기' }))

    await waitFor(() => expect(prefillSpy).toHaveBeenCalledWith('annual-leave-remaining'))
    await waitFor(() => expect(screen.getByLabelText('Input fields (쉼표 구분) *')).toHaveValue('years_of_service, used_days'))
    expect(screen.getByLabelText('Output fields (쉼표 구분) *')).toHaveValue('total_days, remaining_days')
    // legal_refs/scope_exclusions가 화면에 실제로 표시되어야 한다(더 이상 빈 배열이 아님).
    expect(screen.getByText('labor_standards_act_60')).toBeInTheDocument()
    expect(screen.getByText('근로기준법 제60조 제1항 인용 금지')).toBeInTheDocument()
  })

  it('does not overwrite the form when Registry has no entry for the slug (found=false is a normal state, not an error)', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'getContractPrefill').mockResolvedValue({
      success: true,
      data: { found: false, entry: null, slug: 'brand-new-slug', name: '', category: '',
              input_fields: [], output_fields: [], scope_exclusions: [], legal_refs: [],
              message: "Registry v3에 'brand-new-slug' 엔트리가 없습니다" },
      error: null, request_id: 'p2',
    })

    render(<GenerateCalculatorPanel />)
    await switchToModeB()
    await fillSlug('brand-new-slug')
    fireEvent.click(screen.getByRole('button', { name: '📥 Registry에서 불러오기' }))

    await waitFor(() => expect(screen.getByText(/엔트리가 없습니다/)).toBeInTheDocument())
    expect(screen.getByLabelText('Input fields (쉼표 구분) *')).toHaveValue('')
  })

  it('calls getContractInstance() and restores formula/test_cases/formula_status', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    const instanceSpy = vi.spyOn(apiClient, 'getContractInstance').mockResolvedValue({
      success: true,
      data: {
        found: true, instance: {}, slug: 'annual-leave-remaining', name: '연차 잔여일 계산기',
        input_fields: ['years_of_service'], output_fields: ['total_days'],
        scope_exclusions: [], formula: '{"total_days": "years_of_service * 1.25"}',
        formula_status: 'operator_confirmed',
        test_cases: [{ input: { years_of_service: 12 }, expected: { total_days: 15 } }],
        message: '',
      },
      error: null, request_id: 'i1',
    })

    render(<GenerateCalculatorPanel />)
    await switchToModeB()
    await fillSlug()
    fireEvent.click(screen.getByRole('button', { name: '📂 Contract Instance 불러오기' }))

    await waitFor(() => expect(instanceSpy).toHaveBeenCalledWith('annual-leave-remaining'))
    await waitFor(() => expect(screen.getByText(/operator_confirmed/)).toBeInTheDocument())
    expect(screen.getByLabelText('Formula (문자열 또는 JSON)')).toHaveValue('{"total_days": "years_of_service * 1.25"}')
  })

  it('treats "no saved instance" as a normal state, not an error', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'getContractInstance').mockResolvedValue({
      success: true,
      data: { found: false, instance: null, slug: 'annual-leave-remaining', name: '',
              input_fields: [], output_fields: [], scope_exclusions: [], formula: null,
              formula_status: '', test_cases: [], message: "Contract instance가 없습니다: 'annual-leave-remaining'" },
      error: null, request_id: 'i2',
    })

    render(<GenerateCalculatorPanel />)
    await switchToModeB()
    await fillSlug()
    fireEvent.click(screen.getByRole('button', { name: '📂 Contract Instance 불러오기' }))

    await waitFor(() => expect(screen.getByText(/Contract instance가 없습니다/)).toBeInTheDocument())
    // 오류(status-card__error)가 아니라 정상 안내(status-card__hint)로 표시되어야 한다.
    const hintEl = screen.getByText(/Contract instance가 없습니다/)
    expect(hintEl.className).toContain('status-card__hint')
  })

  it('shows an error message when the prefill API call itself fails (network/server error)', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'getContractPrefill').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: '조회 실패(mock)' }, request_id: null,
    })

    render(<GenerateCalculatorPanel />)
    await switchToModeB()
    await fillSlug()
    fireEvent.click(screen.getByRole('button', { name: '📥 Registry에서 불러오기' }))

    await waitFor(() => expect(screen.getByText(/조회 실패\(mock\)/)).toBeInTheDocument())
  })

  it('sends the loaded legal_refs/scope_exclusions (not empty arrays) in the generation request payload', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'getContractPrefill').mockResolvedValue({
      success: true,
      data: {
        found: true, entry: {}, slug: 'annual-leave-remaining', name: '연차 잔여일 계산기', category: '노무/급여',
        input_fields: ['years_of_service'], output_fields: ['total_days'],
        scope_exclusions: ['금지 표현 A'], legal_refs: ['labor_standards_act_60'],
        message: '',
      },
      error: null, request_id: 'p3',
    })
    const generateSpy = vi.spyOn(apiClient, 'postContractGenerate').mockResolvedValue({
      status: 200, body: { success: true, data: { job_id: 'j1', status: 'queued' }, error: null, request_id: 'g1' },
    })
    vi.spyOn(apiClient, 'getContractGenerationJob').mockResolvedValue({
      success: true,
      data: { job_id: 'j1', status: 'running', slug_or_name: 'x', created_at: 't', started_at: 't', finished_at: null, error: null, result: null },
      error: null, request_id: 'j',
    })

    render(<GenerateCalculatorPanel />)
    await switchToModeB()
    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '테스트' } })
    await fillSlug()
    fireEvent.click(screen.getByRole('button', { name: '📥 Registry에서 불러오기' }))
    await waitFor(() => expect(screen.getByText('labor_standards_act_60')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '📋 Contract 기반 생성' }))

    await waitFor(() => expect(generateSpy).toHaveBeenCalled())
    const payload = generateSpy.mock.calls[0][0]
    expect(payload.legal_refs).toEqual(['labor_standards_act_60'])
    expect(payload.scope_exclusions).toEqual(['금지 표현 A'])
  })

  it('prefill/instance buttons require admin (disabled for viewers)', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
      success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u3',
    })
    render(<GenerateCalculatorPanel />)
    await switchToModeB()
    await fillSlug()
    expect(screen.getByRole('button', { name: '📥 Registry에서 불러오기' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '📂 Contract Instance 불러오기' })).toBeDisabled()
  })
})
