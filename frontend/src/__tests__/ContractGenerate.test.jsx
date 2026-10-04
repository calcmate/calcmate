import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { GenerateCalculatorPanel } from '../pages/Calculators.jsx'
import * as apiClient from '../api/client.js'

// P0-5: Mode B(Contract 기반 생성) UI 검증. 폴링은 CalculatorGenerate.test.jsx와
// 동일하게 실제 setTimeout을 짧게 줘서 검증한다(fake timer 없음 — 기존 관례 유지).

const AUTH_ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u2' }

function contractJobResponse(overrides) {
  return {
    success: true,
    data: {
      job_id: 'cjob-1', status: 'running', slug_or_name: 'contract:fake-slug',
      created_at: 't0', started_at: 't0', finished_at: null, error: null, result: null,
      ...overrides,
    },
    error: null, request_id: 'j',
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

async function switchToModeB() {
  await waitFor(() => expect(screen.getByLabelText(/Mode B/)).toBeInTheDocument())
  fireEvent.click(screen.getByLabelText(/Mode B/))
  await waitFor(() => expect(screen.getByLabelText('확정 slug *')).toBeInTheDocument())
}

describe('ContractModePanel (P0-5)', () => {
  it('mode selector switches from Mode A form to Mode B contract form', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    render(<GenerateCalculatorPanel />)
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await switchToModeB()
    expect(screen.getByLabelText('Input fields (쉼표 구분) *')).toBeInTheDocument()
    expect(screen.getByLabelText('Output fields (쉼표 구분) *')).toBeInTheDocument()
  })

  it('slug check shows conflict result', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'postContractSlugCheck').mockResolvedValue({
      success: true,
      data: { slug: 'annual-leave-remaining', conflict: true, message: "'annual-leave-remaining' 슬러그가 이미 존재합니다." },
      error: null, request_id: 's1',
    })
    render(<GenerateCalculatorPanel />)
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await switchToModeB()

    fireEvent.change(screen.getByLabelText('확정 slug *'), { target: { value: 'annual-leave-remaining' } })
    fireEvent.click(screen.getByRole('button', { name: '슬러그 확인' }))

    await waitFor(() => expect(screen.getByText(/이미 존재합니다/)).toBeInTheDocument())
  })

  it('slug check shows available result', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'postContractSlugCheck').mockResolvedValue({
      success: true, data: { slug: 'brand-new-slug', conflict: false, message: '' },
      error: null, request_id: 's2',
    })
    render(<GenerateCalculatorPanel />)
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await switchToModeB()

    fireEvent.change(screen.getByLabelText('확정 slug *'), { target: { value: 'brand-new-slug' } })
    fireEvent.click(screen.getByRole('button', { name: '슬러그 확인' }))

    await waitFor(() => expect(screen.getByText(/사용 가능한 슬러그입니다/)).toBeInTheDocument())
  })

  it('formula validation shows a FAIL sample with expected vs actual', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'postContractFormulaValidate').mockResolvedValue({
      success: true,
      data: {
        valid: true, message: '', all_samples_pass: false, formula_status: 'pending_validation',
        sample_results: [
          { input: { a: 1 }, expected: { total: 12 }, output: { total: 12 }, match: true },
          { input: { a: 2 }, expected: { total: 20 }, output: { total: 18 }, match: false },
        ],
      },
      error: null, request_id: 'v1',
    })
    render(<GenerateCalculatorPanel />)
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await switchToModeB()

    fireEvent.change(screen.getByLabelText('Formula (문자열 또는 JSON)'), { target: { value: '{"total": "a"}' } })
    fireEvent.click(screen.getByRole('button', { name: '🔍 Formula 검증' }))

    await waitFor(() => expect(screen.getByText(/샘플 검증 실패/)).toBeInTheDocument())
    expect(screen.getByText(/❌ 샘플 2/)).toBeInTheDocument()
    expect(screen.getByText(/✅ 샘플 1/)).toBeInTheDocument()
  })

  it('generate → poll → succeeded shows contract validation and blocks save until operator_confirmed', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'postContractGenerate').mockResolvedValue({
      status: 200,
      body: { success: true, data: { job_id: 'cjob-1', status: 'queued' }, error: null, request_id: 'g1' },
    })
    vi.spyOn(apiClient, 'getContractGenerationJob').mockResolvedValue(
      contractJobResponse({
        status: 'succeeded',
        result: {
          slug: 'fake-slug', name: '가짜 계산기', tier: 2,
          formula_valid: true, formula_msg: '',
          contract: { slug: 'fake-slug', formula_status: 'pending_validation' },
          contract_validation: { valid: true },
          post_generation_sample_validation: { all_samples_pass: false, sample_results: [] },
          hold_messages: [],
        },
      })
    )

    render(<GenerateCalculatorPanel />)
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await switchToModeB()

    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '가짜 계산기' } })
    fireEvent.change(screen.getByLabelText('확정 slug *'), { target: { value: 'fake-slug' } })
    fireEvent.click(screen.getByRole('button', { name: '📋 Contract 기반 생성' }))

    await waitFor(() => expect(screen.getByText(/Contract 검증 통과/)).toBeInTheDocument())
    expect(screen.getByText(/Formula 상태: pending_validation/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /calculators \+ app_templates 저장/ })).toBeDisabled()
    expect(screen.getByText(/저장하려면 Formula 검증 통과/)).toBeInTheDocument()
  })

  it('save is enabled and calls postContractSave when operator_confirmed and contract valid', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'postContractGenerate').mockResolvedValue({
      status: 200,
      body: { success: true, data: { job_id: 'cjob-2', status: 'queued' }, error: null, request_id: 'g2' },
    })
    vi.spyOn(apiClient, 'getContractGenerationJob').mockResolvedValue(
      contractJobResponse({
        status: 'succeeded',
        result: {
          slug: 'fake-slug-2', name: '가짜 계산기2', tier: 2,
          formula_valid: true, formula_msg: '',
          contract: { slug: 'fake-slug-2', formula_status: 'operator_confirmed' },
          contract_validation: { valid: true },
          post_generation_sample_validation: { all_samples_pass: true, sample_results: [] },
          hold_messages: [],
        },
      })
    )
    const saveSpy = vi.spyOn(apiClient, 'postContractSave').mockResolvedValue({
      success: true, data: { ok: true, slug: 'fake-slug-2', message: '✅ 저장 완료(mock)' },
      error: null, request_id: 'sv1',
    })

    render(<GenerateCalculatorPanel />)
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await switchToModeB()

    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '가짜 계산기2' } })
    fireEvent.change(screen.getByLabelText('확정 slug *'), { target: { value: 'fake-slug-2' } })
    fireEvent.click(screen.getByRole('button', { name: '📋 Contract 기반 생성' }))

    const saveBtn = await screen.findByRole('button', { name: /calculators \+ app_templates 저장/ })
    await waitFor(() => expect(saveBtn).toBeEnabled())
    fireEvent.click(saveBtn)

    await waitFor(() => expect(saveSpy).toHaveBeenCalledWith('cjob-2', 'fake-slug-2'))
    await waitFor(() => expect(screen.getByText(/저장 완료\(mock\)/)).toBeInTheDocument())
  })

  it('save stays blocked when contract_validation is invalid even if formula is operator_confirmed', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
    vi.spyOn(apiClient, 'postContractGenerate').mockResolvedValue({
      status: 200,
      body: { success: true, data: { job_id: 'cjob-3', status: 'queued' }, error: null, request_id: 'g3' },
    })
    vi.spyOn(apiClient, 'getContractGenerationJob').mockResolvedValue(
      contractJobResponse({
        status: 'succeeded',
        result: {
          slug: 'fake-slug-3', name: '가짜 계산기3', tier: 2,
          formula_valid: true, formula_msg: '',
          contract: { slug: 'fake-slug-3', formula_status: 'operator_confirmed' },
          contract_validation: { valid: false },
          post_generation_sample_validation: null,
          hold_messages: [],
        },
      })
    )
    const saveSpy = vi.spyOn(apiClient, 'postContractSave')

    render(<GenerateCalculatorPanel />)
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toBeInTheDocument())
    await switchToModeB()

    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '가짜 계산기3' } })
    fireEvent.change(screen.getByLabelText('확정 slug *'), { target: { value: 'fake-slug-3' } })
    fireEvent.click(screen.getByRole('button', { name: '📋 Contract 기반 생성' }))

    await waitFor(() => expect(screen.getAllByText(/Contract 불일치/).length).toBeGreaterThan(0))
    const saveBtn = await screen.findByRole('button', { name: /calculators \+ app_templates 저장/ })
    expect(saveBtn).toBeDisabled()
    expect(saveSpy).not.toHaveBeenCalled()
  })
})
