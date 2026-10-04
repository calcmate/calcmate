import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import BlogOneRunQuickActionPanel from '../components/BlogOneRunQuickActionPanel.jsx'
import { GenerateCalculatorPanel } from '../pages/Calculators.jsx'
import Settings from '../pages/Settings.jsx'
import * as apiClient from '../api/client.js'

// CALCMATE-REMAINING-MIGRATION-SMALL-GAPS-02 UI 검증. 모든 client 호출은 mock —
// 실제 파이프라인/WP 연결/AI 생성/저장은 일어나지 않는다.

const ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }
const ok = (data) => ({ success: true, data, error: null, request_id: 'r' })
const fail = (code, message) => ({ success: false, data: null, error: { code, message }, request_id: 'r' })

afterEach(() => {
  vi.restoreAllMocks()
})

// ── Blog 글 생성(1건) ──────────────────────────────────────────────────────
describe('BlogOneRunQuickActionPanel', () => {
  it('calls the run-one client (not the full pipeline or blog scheduler)', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN)
    const one = vi.spyOn(apiClient, 'postPipelineRunOne').mockResolvedValue(ok({ produced: 1, reason: 'ok' }))
    const full = vi.spyOn(apiClient, 'postPipelineRunOnce')
    const sched = vi.spyOn(apiClient, 'runBlogSchedulerOnce')
    render(<BlogOneRunQuickActionPanel />)
    const btn = await screen.findByRole('button', { name: /글 생성\(1건\)/ })
    await waitFor(() => expect(btn).toBeEnabled())
    fireEvent.click(btn)
    expect(await screen.findByText(/글 생성 요청 완료 · 생산 1건/)).toBeInTheDocument()
    expect(one).toHaveBeenCalledTimes(1)
    expect(full).not.toHaveBeenCalled()
    expect(sched).not.toHaveBeenCalled()
  })

  it('busy and budget results are distinguished', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN)
    vi.spyOn(apiClient, 'postPipelineRunOne')
      .mockResolvedValueOnce(fail('LOCK_CONFLICT', 'lock 보유 중'))
      .mockResolvedValueOnce(ok({ produced: 0, reason: 'budget_daily' }))
    render(<BlogOneRunQuickActionPanel />)
    const btn = await screen.findByRole('button', { name: /글 생성\(1건\)/ })
    await waitFor(() => expect(btn).toBeEnabled())
    fireEvent.click(btn)
    expect(await screen.findByText(/다른 실행이 진행 중입니다: lock 보유 중/)).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: /글 생성\(1건\)/ }))
    expect(await screen.findByText(/일일 AI 예산 초과로 중단됨/)).toBeInTheDocument()
  })
})

// ── WordPress 연결 테스트(Settings) ────────────────────────────────────────
const GENERAL = ok({
  OPENAI_API_KEY: { configured: true }, CLAUDE_API_KEY: { configured: false },
  GEMINI_API_KEY: { configured: false }, TELEGRAM_BOT_TOKEN: { configured: false },
  TELEGRAM_CHAT_ID: { configured: false }, WORDPRESS_APP_PASSWORD: { configured: true },
  WORDPRESS_URL: 'https://saved.example', WORDPRESS_USERNAME: 'saveduser',
  DAILY_AI_BUDGET: 5, MONTHLY_AI_BUDGET: 100, AI_ROLES: {},
})

function mockSettingsPage(user = ADMIN) {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(user)
  vi.spyOn(apiClient, 'getSettings').mockResolvedValue(ok({}))
  vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(ok({}))
  vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue(ok({}))
  vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue(ok({}))
  vi.spyOn(apiClient, 'getGeneralSettings').mockResolvedValue(GENERAL)
  vi.spyOn(apiClient, 'getImageGoogleSettings').mockResolvedValue(ok({}))
  vi.spyOn(apiClient, 'getCalculatorDisplaySettings').mockResolvedValue(ok({}))
  vi.spyOn(apiClient, 'getOperationsSettings').mockResolvedValue(fail('X', 'skip'))
}

describe('WordPress 연결 테스트 (Settings)', () => {
  it('sends only typed values (password omitted when empty) and shows success', async () => {
    mockSettingsPage()
    const spy = vi.spyOn(apiClient, 'postPublishConnectionTest')
      .mockResolvedValue(ok({ ok: true, result: 'success', status_code: 200, user_name: '운영자', message: '연결 성공 — 사용자: 운영자' }))
    render(<Settings />)
    const btn = await screen.findByRole('button', { name: /WordPress 연결 테스트/ })
    await waitFor(() => expect(btn).toBeEnabled())
    fireEvent.click(btn)
    expect(await screen.findByText(/연결 성공 — 사용자: 운영자/)).toBeInTheDocument()
    expect(spy.mock.calls[0][0]).toEqual({ wordpress_url: 'https://saved.example', wordpress_username: 'saveduser' })
  })

  it('shows auth failure and server validation errors', async () => {
    mockSettingsPage()
    vi.spyOn(apiClient, 'postPublishConnectionTest')
      .mockResolvedValueOnce(ok({ ok: false, result: 'auth_failed', status_code: 401, user_name: null, message: '인증 실패(401) — 사용자/앱 비밀번호 확인' }))
      .mockResolvedValueOnce(fail('VALIDATION_ERROR', 'URL은 http:// 또는 https:// 로 시작하는 올바른 주소여야 합니다.'))
    render(<Settings />)
    const btn = await screen.findByRole('button', { name: /WordPress 연결 테스트/ })
    await waitFor(() => expect(btn).toBeEnabled())
    fireEvent.click(btn)
    expect(await screen.findByText(/인증 실패\(401\)/)).toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: /WordPress 연결 테스트/ }))
    expect(await screen.findByText(/올바른 주소여야 합니다/)).toBeInTheDocument()
  })

  it('viewer cannot run the test', async () => {
    mockSettingsPage(VIEWER)
    const spy = vi.spyOn(apiClient, 'postPublishConnectionTest')
    render(<Settings />)
    const btn = await screen.findByRole('button', { name: /WordPress 연결 테스트/ })
    expect(btn).toBeDisabled()
    expect(spy).not.toHaveBeenCalled()
  })
})

// ── Mode A 생성 후 검토·저장 ───────────────────────────────────────────────
const PREVIEW_RESULT = {
  mode: 'A_preview', saved: false, name: '퇴직금 계산기', tier: 2, suggested_slug: 'severance-pay',
  formula_valid: true, formula_msg: '', html_complete: true, html_msg: '', tokens: 1234,
  calculator_type: 'simple', formula: 'a*b', seo_title: '퇴직금 계산기 2026',
  input_schema: { a: {} }, output_schema: { r: {} }, faq: [{ q: 'Q', a: 'A' }], blog_draft: 'draft',
  html: '<html><body>calc</body></html>', html_length: 30,
}
const job = (status, result = null) => ok({ job_id: 'pv-1', status, slug_or_name: 'preview:퇴직금 계산기', result, error: null })

async function openPreviewMode(result = PREVIEW_RESULT) {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN)
  const gen = vi.spyOn(apiClient, 'postCalculatorPreviewGenerate')
    .mockResolvedValue({ status: 200, body: job('queued') })
  vi.spyOn(apiClient, 'getCalculatorGenerationJob').mockResolvedValue(job('succeeded', result))
  const slugCheck = vi.spyOn(apiClient, 'postContractSlugCheck')
    .mockResolvedValue(ok({ slug: 'severance-pay', conflict: false, message: 'OK' }))
  const legacy = vi.spyOn(apiClient, 'postCalculatorGenerate')
  render(<GenerateCalculatorPanel pollIntervalMs={5} pollMaxAttempts={5} />)
  fireEvent.click(await screen.findByLabelText(/생성 후 검토·저장/))
  fireEvent.change(await screen.findByLabelText('계산기명 *'), { target: { value: '퇴직금 계산기' } })
  fireEvent.click(screen.getByRole('button', { name: /미리보기 생성/ }))
  await screen.findByTestId('mode-a-preview')
  return { gen, slugCheck, legacy }
}

describe('Mode A 생성 후 검토·저장', () => {
  it('existing Mode A form remains the default', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN)
    render(<GenerateCalculatorPanel pollIntervalMs={5} pollMaxAttempts={5} />)
    expect(await screen.findByText('🏭 새 계산기 생성 (Mode A)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /생성 시작/ })).toBeInTheDocument()
  })

  it('preview shows review fields, prefills slug and checks conflict without saving', async () => {
    const save = vi.spyOn(apiClient, 'postCalculatorPreviewSave')
    const { gen, slugCheck, legacy } = await openPreviewMode()
    expect(gen).toHaveBeenCalledWith({ name: '퇴직금 계산기', category: '', description: '', tier: 2 })
    expect(screen.getByText('퇴직금 계산기 2026')).toBeInTheDocument()
    expect(screen.getByText('a*b')).toBeInTheDocument()
    expect(screen.getByTitle('계산기 렌더 미리보기')).toBeInTheDocument()
    expect(screen.getByLabelText(/영문 slug/)).toHaveValue('severance-pay')
    await waitFor(() => expect(slugCheck).toHaveBeenCalledWith('severance-pay'))
    expect(await screen.findByText(/슬러그 사용 가능/)).toBeInTheDocument()
    expect(save).not.toHaveBeenCalled()
    expect(legacy).not.toHaveBeenCalled()
  })

  it('slug conflict disables save', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN)
    await openPreviewMode()
    apiClient.postContractSlugCheck.mockResolvedValue(ok({ slug: 'taken', conflict: true, message: '이미 존재' }))
    fireEvent.change(screen.getByLabelText(/영문 slug/), { target: { value: 'taken' } })
    fireEvent.click(screen.getByRole('button', { name: /slug 중복 확인/ }))
    expect(await screen.findByText(/슬러그 중복/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /app_templates 저장/ })).toBeDisabled()
  })

  it('formula failure is shown and save is disabled (FastAPI hard gate)', async () => {
    await openPreviewMode({ ...PREVIEW_RESULT, formula_valid: false, formula_msg: '변수 불일치' })
    expect(screen.getByText(/수식 검증 실패: 변수 불일치/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /app_templates 저장/ })).toBeDisabled()
  })

  it('save calls the preview save endpoint with the slug', async () => {
    const save = vi.spyOn(apiClient, 'postCalculatorPreviewSave')
      .mockResolvedValue(ok({ ok: true, slug: 'severance-pay', message: '저장 완료 | 🧮 Build 완료', blocked_reason: null }))
    await openPreviewMode()
    await screen.findByText(/슬러그 사용 가능/)
    fireEvent.click(screen.getByRole('button', { name: /app_templates 저장/ }))
    expect(await screen.findByText(/저장 완료 \| 🧮 Build 완료/)).toBeInTheDocument()
    expect(save).toHaveBeenCalledWith('pv-1', 'severance-pay')
    expect(screen.queryByTestId('mode-a-preview')).not.toBeInTheDocument()
  })

  it('blocked save shows the server reason', async () => {
    vi.spyOn(apiClient, 'postCalculatorPreviewSave')
      .mockResolvedValue(ok({ ok: false, slug: 'severance-pay', message: null, blocked_reason: '슬러그 중복: 이미 존재' }))
    await openPreviewMode()
    await screen.findByText(/슬러그 사용 가능/)
    fireEvent.click(screen.getByRole('button', { name: /app_templates 저장/ }))
    expect(await screen.findByText(/슬러그 중복: 이미 존재/)).toBeInTheDocument()
    expect(screen.getByTestId('mode-a-preview')).toBeInTheDocument()
  })

  it('discard asks for confirmation, then calls discard without saving', async () => {
    const save = vi.spyOn(apiClient, 'postCalculatorPreviewSave')
    const discard = vi.spyOn(apiClient, 'postCalculatorPreviewDiscard')
      .mockResolvedValue(ok({ discarded: true, job_id: 'pv-1' }))
    await openPreviewMode()
    fireEvent.click(screen.getByRole('button', { name: /생성 결과 폐기/ }))
    expect(discard).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /^취소$/ }))
    expect(discard).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: /생성 결과 폐기/ }))
    fireEvent.click(screen.getByRole('button', { name: /폐기하고 초기화/ }))
    await waitFor(() => expect(screen.queryByTestId('mode-a-preview')).not.toBeInTheDocument())
    expect(discard).toHaveBeenCalledWith('pv-1')
    expect(save).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /미리보기 생성/ })).toBeInTheDocument()
  })

  it('busy (409) on preview generation shows the busy message', async () => {
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN)
    vi.spyOn(apiClient, 'postCalculatorPreviewGenerate')
      .mockResolvedValue({ status: 409, body: { detail: '이미 생성 작업이 실행 중입니다.' } })
    render(<GenerateCalculatorPanel pollIntervalMs={5} pollMaxAttempts={5} />)
    fireEvent.click(await screen.findByLabelText(/생성 후 검토·저장/))
    fireEvent.change(await screen.findByLabelText('계산기명 *'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: /미리보기 생성/ }))
    expect(await screen.findByText(/다른 계산기 생성 작업이 진행 중/)).toBeInTheDocument()
  })
})
