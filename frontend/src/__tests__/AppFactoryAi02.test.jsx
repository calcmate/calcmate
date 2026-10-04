import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { GenerateCalculatorPanel } from '../pages/Calculators.jsx'
import * as apiClient from '../api/client.js'

// CALCMATE-STREAMLIT-REMAINING-MIGRATION-APP-FACTORY-02 — App Factory AI UI 검증.
// 모든 client 호출은 mock: 실제 AI 호출·생성·저장은 일어나지 않는다. 기존 Dashboard
// 테스트(step23_2/23_3/24_2/25_2/26_1)의 UX 계약(추천은 표시만, Tier2-B 연동, 기존 입력
// 덮어쓰기 방지, slug는 비어 있을 때만 자동 제안)을 React 수준에서 검증한다.

const ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }
const ok = (data) => ({ success: true, data, error: null, request_id: 'r' })
const fail = (code, message) => ({ success: false, data: null, error: { code, message }, request_id: 'r' })

let generateSpy, saveSpy, previewSpy, contractGenSpy, contractSaveSpy

beforeEach(() => {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN)
  vi.spyOn(apiClient, 'postAiTier2bDetect').mockResolvedValue(ok({ detected: false }))
  vi.spyOn(apiClient, 'postContractSlugSuggest').mockResolvedValue(ok({ slug: 'auto-slug' }))
  generateSpy = vi.spyOn(apiClient, 'postCalculatorGenerate')
  previewSpy = vi.spyOn(apiClient, 'postCalculatorPreviewGenerate')
  saveSpy = vi.spyOn(apiClient, 'postCalculatorPreviewSave')
  contractGenSpy = vi.spyOn(apiClient, 'postContractGenerate')
  contractSaveSpy = vi.spyOn(apiClient, 'postContractSave')
})

afterEach(() => {
  vi.restoreAllMocks()
})

function expectNoGenerateOrSave() {
  expect(generateSpy).not.toHaveBeenCalled()
  expect(previewSpy).not.toHaveBeenCalled()
  expect(saveSpy).not.toHaveBeenCalled()
  expect(contractGenSpy).not.toHaveBeenCalled()
  expect(contractSaveSpy).not.toHaveBeenCalled()
}

async function renderModeB() {
  render(<GenerateCalculatorPanel pollIntervalMs={5} pollMaxAttempts={5} />)
  fireEvent.click(await screen.findByLabelText(/Mode B/))
  await screen.findByLabelText('계산기명 *')
}

// ── 기본 정보: 아이디어 / Mode / Tier / Tier2-B ─────────────────────────────
describe('App Factory 기본 정보 AI 보조', () => {
  it('키워드 아이디어 제안이 이름/카테고리/설명을 채우고 생성·저장은 하지 않는다', async () => {
    const spy = vi.spyOn(apiClient, 'postAiSuggestIdea').mockResolvedValue(ok({ name: '육아휴직 급여 계산기', category: '노무/급여', desc: '월 급여 기준' }))
    await renderModeB()
    fireEvent.change(screen.getByLabelText('키워드로 아이디어 생성'), { target: { value: '육아휴직' } })
    fireEvent.click(screen.getByRole('button', { name: /키워드로 제안/ }))
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toHaveValue('육아휴직 급여 계산기'))
    expect(screen.getByLabelText('카테고리')).toHaveValue('노무/급여')
    expect(screen.getByLabelText('설명')).toHaveValue('월 급여 기준')
    expect(spy).toHaveBeenCalledWith('육아휴직')
    expectNoGenerateOrSave()
  })

  it('자유 아이디어 제안 실패는 고정 문구만 표시한다', async () => {
    const spy = vi.spyOn(apiClient, 'postAiSuggestIdea').mockResolvedValue(fail('AI_SUGGEST_FAILED', 'AI 제안 실패(직접 입력해주세요).'))
    await renderModeB()
    fireEvent.click(screen.getByRole('button', { name: /AI 아이디어 제안/ }))
    expect(await screen.findByText(/AI 제안 실패\(직접 입력해주세요\)/)).toBeInTheDocument()
    expect(spy).toHaveBeenCalledWith(null)
  })

  it('Mode 추천은 표시만 한다(HIGH는 확신 표시, 그 외는 보통/불확실)', async () => {
    vi.spyOn(apiClient, 'postAiSuggestMode')
      .mockResolvedValueOnce(ok({ mode: 'B', reason: '법령 의존', confidence: 'high' }))
      .mockResolvedValueOnce(ok({ mode: 'A', reason: '단순', confidence: 'low' }))
    await renderModeB()
    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '퇴직금 계산기' } })
    fireEvent.click(screen.getByRole('button', { name: /Mode AI 추천/ }))
    expect(await screen.findByText(/AI 추천: Mode B — 📋 Contract 기반 생성 \(확신도: HIGH\)/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Mode AI 추천/ }))
    expect(await screen.findByText(/Mode A — 🏭 자동 생성 🚨 판단 불확실/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Mode B/)).toBeChecked()   // 추천이 모드를 바꾸지 않는다
    expectNoGenerateOrSave()
  })

  it('Mode/Tier 추천은 계산기명이 없으면 호출하지 않는다', async () => {
    const mode = vi.spyOn(apiClient, 'postAiSuggestMode')
    const tier = vi.spyOn(apiClient, 'postAiSuggestTier')
    await renderModeB()
    fireEvent.click(screen.getByRole('button', { name: /Mode AI 추천/ }))
    fireEvent.click(screen.getByRole('button', { name: /Tier AI 추천/ }))
    expect(await screen.findByText(/계산기명을 먼저 입력하세요/)).toBeInTheDocument()
    expect(mode).not.toHaveBeenCalled()
    expect(tier).not.toHaveBeenCalled()
  })

  it('Tier2-B 추천은 신뢰도와 무관하게 Mode B Tier를 Tier2-B로 반영한다', async () => {
    vi.spyOn(apiClient, 'postAiSuggestTier').mockResolvedValue(ok({ tier: 'Tier2-B', reason: '날짜', confidence: 'low', tier_int: 2, tier2b_suggested: true }))
    await renderModeB()
    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '전역일 계산기' } })
    fireEvent.click(screen.getByRole('button', { name: /Tier AI 추천/ }))
    expect(await screen.findByText(/AI 추천: Tier2-B 🚨 분류 불확실/)).toBeInTheDocument()
    expect(screen.getByLabelText('Tier')).toHaveValue('Tier2-B')
    expectNoGenerateOrSave()
  })

  it('Mode A에서 받은 Tier2-B 추천과 기본 정보가 Mode B로 이어진다', async () => {
    vi.spyOn(apiClient, 'postAiSuggestTier').mockResolvedValue(ok({ tier: 'Tier2-B', reason: '날짜', confidence: 'high', tier_int: 2, tier2b_suggested: true }))
    render(<GenerateCalculatorPanel pollIntervalMs={5} pollMaxAttempts={5} />)
    fireEvent.change(await screen.findByLabelText('계산기명 *'), { target: { value: '전역일 계산기' } })
    fireEvent.click(screen.getByRole('button', { name: /Tier AI 추천/ }))
    expect(await screen.findByText(/높은 확신도로 자동 선택되었습니다/)).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText(/Mode B/))
    await waitFor(() => expect(screen.getByLabelText('계산기명 *')).toHaveValue('전역일 계산기'))
    expect(screen.getByLabelText('Tier')).toHaveValue('Tier2-B')
  })

  it('Tier1 추천은 Mode A Tier를 1로 바꾸고 Tier1 안내 문구를 보여준다', async () => {
    vi.spyOn(apiClient, 'postAiSuggestTier').mockResolvedValue(ok({ tier: 'Tier1', reason: '법령', confidence: 'medium', tier_int: 1, tier2b_suggested: false }))
    render(<GenerateCalculatorPanel pollIntervalMs={5} pollMaxAttempts={5} />)
    fireEvent.change(await screen.findByLabelText('계산기명 *'), { target: { value: '퇴직금' } })
    expect(screen.getByText(/Tier2는 생성 후 계산 정확성 검증/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Tier AI 추천/ }))
    await waitFor(() => expect(screen.getByLabelText('Tier')).toHaveValue('1'))
    expect(screen.getByText(/Tier1은 생성 후 계산 로직 \+ legal 근거/)).toBeInTheDocument()
  })

  it('Tier2-B 키워드 경고는 서버 판정 결과로 표시된다', async () => {
    const detect = apiClient.postAiTier2bDetect.mockResolvedValue(ok({ detected: true }))
    await renderModeB()
    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '군인 전역일' } })
    expect(await screen.findByTestId('tier2b-warning', {}, { timeout: 2000 })).toBeInTheDocument()
    expect(detect).toHaveBeenCalledWith({ name: '군인 전역일', description: '' })
  })

  it('viewer는 AI 보조 버튼을 쓸 수 없다', async () => {
    apiClient.getCurrentUser.mockResolvedValue(VIEWER)
    const idea = vi.spyOn(apiClient, 'postAiSuggestIdea')
    await renderModeB()
    expect(screen.getByRole('button', { name: /AI 아이디어 제안/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Mode AI 추천/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Tier AI 추천/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /필드 자동 제안/ })).toBeDisabled()
    expect(idea).not.toHaveBeenCalled()
  })
})

// ── Mode B: slug / 필드 / Formula ──────────────────────────────────────────
describe('Mode B 보조 기능', () => {
  it('확정 slug가 비어 있을 때만 자동 제안한다', async () => {
    await renderModeB()
    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '퇴직금 계산기' } })
    await waitFor(() => expect(screen.getByLabelText('확정 slug *')).toHaveValue('auto-slug'), { timeout: 2000 })
    expect(apiClient.postContractSlugSuggest).toHaveBeenCalledWith('퇴직금 계산기')
    fireEvent.change(screen.getByLabelText('확정 slug *'), { target: { value: 'my-slug' } })
    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '다른 이름' } })
    await new Promise((r) => setTimeout(r, 600))
    expect(screen.getByLabelText('확정 slug *')).toHaveValue('my-slug')
  })

  it('필드 자동 제안: 빈 입력란은 채우고, 값이 있는 입력란은 유지 후 교체 버튼으로만 바꾼다', async () => {
    const spy = vi.spyOn(apiClient, 'postAiSuggestSpec').mockResolvedValue(ok({
      input_fields: ['years', 'wage'], output_fields: ['pay'], formula: 'years*wage', labels: { years: '근속연수' },
    }))
    await renderModeB()
    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '퇴직금' } })
    fireEvent.change(screen.getByLabelText(/Output fields/), { target: { value: 'my_out' } })
    fireEvent.click(screen.getByRole('button', { name: /필드 자동 제안/ }))
    await waitFor(() => expect(screen.getByLabelText(/Input fields/)).toHaveValue('years, wage'))
    expect(screen.getByLabelText(/Output fields/)).toHaveValue('my_out')       // 덮어쓰지 않음
    expect(screen.getByLabelText(/Formula \(문자열/)).toHaveValue('years*wage')
    expect(screen.getByTestId('pending-spec')).toHaveTextContent('제안 output: pay')
    expect(spy).toHaveBeenCalledWith({ name: '퇴직금', category: '', description: '', tier: 'Tier2-A' })
    fireEvent.click(screen.getByRole('button', { name: '제안값으로 교체' }))
    expect(screen.getByLabelText(/Output fields/)).toHaveValue('pay')
    expectNoGenerateOrSave()
  })

  it('필드 자동 제안이 비어 있으면 기존 입력을 유지하고 경고한다', async () => {
    vi.spyOn(apiClient, 'postAiSuggestSpec').mockResolvedValue(ok({ input_fields: [], output_fields: [], formula: '', labels: {} }))
    await renderModeB()
    fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '퇴직금' } })
    fireEvent.change(screen.getByLabelText(/Input fields/), { target: { value: 'keep_me' } })
    fireEvent.click(screen.getByRole('button', { name: /필드 자동 제안/ }))
    expect(await screen.findByText(/AI가 유효한 필드를 제안하지 못했습니다/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Input fields/)).toHaveValue('keep_me')
  })

  it('AI Formula 제안: 입력/출력 필드가 없으면 비활성, 기존 formula는 두 번째 클릭에서만 교체', async () => {
    const spy = vi.spyOn(apiClient, 'postAiSuggestFormula').mockResolvedValue(ok({
      success: true, formula: 'a*b', reason: '곱', assumptions: [], warnings: ['검토 필요'], status: 'ai_suggested',
    }))
    await renderModeB()
    const btn = screen.getByRole('button', { name: /AI Formula 제안/ })
    expect(btn).toBeDisabled()
    fireEvent.change(screen.getByLabelText(/Input fields/), { target: { value: 'a, b' } })
    fireEvent.change(screen.getByLabelText(/Output fields/), { target: { value: 'r' } })
    fireEvent.change(screen.getByLabelText(/Formula \(문자열/), { target: { value: 'a+b' } })
    fireEvent.click(screen.getByRole('button', { name: /AI Formula 제안/ }))
    expect(await screen.findByText(/다시 클릭하면 AI 제안으로 교체됩니다/)).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/Formula \(문자열/)).toHaveValue('a+b')
    fireEvent.click(screen.getByRole('button', { name: /AI Formula 제안/ }))
    await waitFor(() => expect(screen.getByLabelText(/Formula \(문자열/)).toHaveValue('a*b'))
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ input_fields: ['a', 'b'], output_fields: ['r'] }))
    expect(screen.getByText(/반드시 검토 후 \[🔍 Formula 검증\]/)).toBeInTheDocument()
    expect(screen.getByText(/⚠️ 검토 필요/)).toBeInTheDocument()
    expect(screen.getByTestId('formula-input-status')).toHaveTextContent('🔵 AI 제안')
    fireEvent.change(screen.getByLabelText(/Formula \(문자열/), { target: { value: 'a*b+1' } })
    expect(screen.getByTestId('formula-input-status')).toHaveTextContent('🟡 검증 대기')
    expectNoGenerateOrSave()
  })

  it('AI Formula 제안 실패는 사유와 경고를 보여 주고 formula를 바꾸지 않는다', async () => {
    vi.spyOn(apiClient, 'postAiSuggestFormula').mockResolvedValue(ok({
      success: false, formula: '', reason: '이 계산기는 커스텀 계산 로직이 필요', assumptions: [], warnings: ['CUSTOM_COMPUTE_SLUGS 대상 계산기'], status: 'not_generated',
    }))
    await renderModeB()
    fireEvent.change(screen.getByLabelText(/Input fields/), { target: { value: 'a' } })
    fireEvent.change(screen.getByLabelText(/Output fields/), { target: { value: 'r' } })
    fireEvent.click(screen.getByRole('button', { name: /AI Formula 제안/ }))
    expect(await screen.findByText(/AI Formula 제안 실패: 이 계산기는 커스텀/)).toBeInTheDocument()
    expect(screen.getByText(/CUSTOM_COMPUTE_SLUGS 대상 계산기/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Formula \(문자열/)).toHaveValue('')
  })
})

// ── Formula 운영자 확정 ────────────────────────────────────────────────────
function contractJob(status) {
  return ok({
    job_id: 'cj-1', status: 'succeeded', slug_or_name: 'contract:test-calc', error: null,
    result: {
      slug: 'test-calc', name: '테스트', formula_valid: true, formula_msg: '',
      contract: { slug: 'test-calc', formula_status: status, formula: 'a*b', tier: 'Tier2-A' },
      contract_validation: { valid: true }, hold_messages: status === 'operator_confirmed' ? [] : ['HOLD-1: formula가 운영자 확정 상태가 아닙니다.'],
    },
  })
}

async function generateContract() {
  contractGenSpy.mockResolvedValue({ status: 200, body: ok({ job_id: 'cj-1', status: 'queued' }) })
  await renderModeB()
  fireEvent.change(screen.getByLabelText('계산기명 *'), { target: { value: '테스트' } })
  fireEvent.change(screen.getByLabelText('확정 slug *'), { target: { value: 'test-calc' } })
  fireEvent.change(screen.getByLabelText(/Input fields/), { target: { value: 'a, b' } })
  fireEvent.change(screen.getByLabelText(/Output fields/), { target: { value: 'r' } })
  fireEvent.click(screen.getByRole('button', { name: /Contract 기반 생성/ }))
  await screen.findByText(/Formula 상태: pending_validation/)
}

describe('Mode B Formula 운영자 확정', () => {
  it('확정 요청은 job id만 보내고, 서버 확정 후 상태를 다시 읽어 저장을 허용한다', async () => {
    const jobSpy = vi.spyOn(apiClient, 'getContractGenerationJob').mockResolvedValue(contractJob('pending_validation'))
    const confirm = vi.spyOn(apiClient, 'postContractConfirmFormula').mockResolvedValue(ok({
      ok: true, formula_status: 'operator_confirmed', validation: { valid: true, all_samples_pass: true }, message: '✅ Formula 운영자 확정 완료 — operator_confirmed',
    }))
    await generateContract()
    expect(screen.getByRole('button', { name: /app_templates 저장/ })).toBeDisabled()
    expect(screen.getByText(/저장하려면 Formula 검증 통과 후 \[✅ Formula 확정\]이 필요합니다/)).toBeInTheDocument()
    jobSpy.mockResolvedValue(contractJob('operator_confirmed'))
    fireEvent.click(screen.getByRole('button', { name: /✅ Formula 확정/ }))
    expect(await screen.findByText(/Formula 운영자 확정 완료/)).toBeInTheDocument()
    expect(confirm).toHaveBeenCalledWith('cj-1')
    expect(confirm.mock.calls[0]).toHaveLength(1)   // formula 전문/플래그를 보내지 않는다
    await screen.findByText(/Formula 상태: operator_confirmed/)
    expect(screen.getByRole('button', { name: /app_templates 저장/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: /✅ Formula 확정/ })).not.toBeInTheDocument()
    expect(contractSaveSpy).not.toHaveBeenCalled()
  })

  it('서버가 확정을 거부하면 사유를 보여 주고 저장은 계속 차단된다', async () => {
    vi.spyOn(apiClient, 'getContractGenerationJob').mockResolvedValue(contractJob('pending_validation'))
    vi.spyOn(apiClient, 'postContractConfirmFormula').mockResolvedValue(ok({
      ok: false, formula_status: 'pending_validation', validation: { valid: true, all_samples_pass: false }, message: 'Formula 검증을 통과해야 확정할 수 있습니다.',
    }))
    await generateContract()
    fireEvent.click(screen.getByRole('button', { name: /✅ Formula 확정/ }))
    expect(await screen.findByText(/Formula 검증을 통과해야 확정할 수 있습니다/)).toBeInTheDocument()
    expect(screen.getByText(/기대값 불일치\(Level 3\)/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /app_templates 저장/ })).toBeDisabled()
  })
})
