// CALCMATE-STREAMLIT-REMAINING-MIGRATION-GAP-01-03-IMPLEMENT-01 — CalculatorDetail의
// GAP-01 상태토글 / GAP-03 전체 사이트 Build / GAP-02 2단계 삭제. API는 전부 mock.
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import CalculatorDetail from '../pages/CalculatorDetail.jsx'
import * as apiClient from '../api/client.js'

const ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u' }
const VIEWER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u' }
const FAIL = (code, message) => ({ success: false, data: null, error: { code, message }, request_id: null })

const DETAIL = { success: true, data: { id: 'c1', slug: 'af-ready', name: 'AF 준비', db_status: 'active', updated_at: 'x', published_url: '', is_deployed: false, registry_status: 'READY', is_legal_hold: false, tier: 2 }, error: null, request_id: 'r' }
const CONTENT = { success: true, data: { seo_title: '', seo_description: '', faq: null, article_content: '', article_length: 0, article_truncated: false }, error: null, request_id: 'r' }
const status = (over = {}) => ({ success: true, data: { db_status: 'active', registry_status: 'READY', is_legal_hold: false, tier: 2, has_content: false, has_static_site: false, static_files: [], published_url: '', is_deployed: false, ...over }, error: null, request_id: 'r' })

afterEach(() => vi.restoreAllMocks())

function setup({ user = ADMIN, st = status() } = {}) {
  vi.spyOn(apiClient, 'getCalculator').mockResolvedValue(DETAIL)
  vi.spyOn(apiClient, 'getCalculatorContent').mockResolvedValue(CONTENT)
  vi.spyOn(apiClient, 'getCalculatorStatus').mockResolvedValue(st)
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(user)
  for (const fn of ['getCalculatorFormula', 'getCalculatorChecklist', 'getCalculatorReview', 'getCalculatorPreview']) {
    vi.spyOn(apiClient, fn).mockResolvedValue(FAIL('NETWORK_ERROR', 'x'))
  }
  render(
    <MemoryRouter initialEntries={['/calculators/af-ready']}>
      <Routes>
        <Route path="/calculators/:slug" element={<CalculatorDetail />} />
        <Route path="/calculators" element={<p>계산기 목록 화면</p>} />
      </Routes>
    </MemoryRouter>
  )
}

const card = async (title) => {
  const h = await screen.findByRole('heading', { name: title })
  return within(h.closest('.status-card'))
}

function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

describe('GAP-01 상태토글', () => {
  it('shows current status and toggles active → inactive using the server response', async () => {
    const spy = vi.spyOn(apiClient, 'postCalculatorStatus').mockResolvedValue({ success: true, data: { ok: true, slug: 'af-ready', status: 'inactive', previous: 'active' } })
    setup()
    const c = await card('상태 토글')
    expect(c.getByTestId('calc-db-status')).toHaveTextContent('active')
    await waitFor(() => expect(c.getByRole('button', { name: /상태토글 \(→ inactive\)/ })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: /상태토글/ }))
    await waitFor(() => expect(c.getByTestId('calc-db-status')).toHaveTextContent('inactive'))
    expect(spy).toHaveBeenCalledWith('af-ready', 'inactive')
    expect(c.getByRole('button', { name: /상태토글 \(→ active\)/ })).toBeInTheDocument()
  })

  it('inactive → active', async () => {
    const spy = vi.spyOn(apiClient, 'postCalculatorStatus').mockResolvedValue({ success: true, data: { ok: true, slug: 'af-ready', status: 'active' } })
    setup({ st: status({ db_status: 'inactive' }) })
    const c = await card('상태 토글')
    await waitFor(() => expect(c.getByRole('button', { name: /→ active/ })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: /→ active/ }))
    await waitFor(() => expect(c.getByTestId('calc-db-status')).toHaveTextContent(/^active$/))
    expect(spy).toHaveBeenCalledWith('af-ready', 'active')
  })

  it('prevents duplicate requests while saving', async () => {
    const d = deferred()
    const spy = vi.spyOn(apiClient, 'postCalculatorStatus').mockReturnValue(d.promise)
    setup()
    const c = await card('상태 토글')
    await waitFor(() => expect(c.getByRole('button', { name: /상태토글/ })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: /상태토글/ }))
    const busy = await c.findByRole('button', { name: '변경 중...' })
    expect(busy).toBeDisabled()
    fireEvent.click(busy)
    expect(spy).toHaveBeenCalledTimes(1)
    d.resolve({ success: true, data: { ok: true, slug: 'af-ready', status: 'inactive' } })
    await waitFor(() => expect(c.getByTestId('calc-db-status')).toHaveTextContent('inactive'))
  })

  it('viewer sees the toggle disabled', async () => {
    const spy = vi.spyOn(apiClient, 'postCalculatorStatus')
    setup({ user: VIEWER })
    const c = await card('상태 토글')
    await waitFor(() => expect(c.getByText(/상태 변경은 admin 권한/)).toBeInTheDocument())
    expect(c.getByRole('button', { name: /상태토글/ })).toBeDisabled()
    expect(spy).not.toHaveBeenCalled()
  })

  it('keeps the previous status on error', async () => {
    vi.spyOn(apiClient, 'postCalculatorStatus').mockResolvedValue(FAIL('VALIDATION_ERROR', 'status 오류'))
    setup()
    const c = await card('상태 토글')
    await waitFor(() => expect(c.getByRole('button', { name: /상태토글/ })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: /상태토글/ }))
    await waitFor(() => expect(c.getByText('⚠ status 오류')).toBeInTheDocument())
    expect(c.getByTestId('calc-db-status')).toHaveTextContent('active')
  })
})

const REBUILD_OK = {
  success: true,
  data: {
    ok: true, stage: 'done', trigger_slug: 'af-ready', deployed: false, message: '✅ Build 완료 — _site/ 갱신됨',
    qa: [{ step: 1, label: '수식', passed: true, skipped: false, detail: 'ok' }],
    summary: { ok_count: 12, skip_count: 1, error_count: 0, skipped: ['af-hold'], errors: [] },
    validation: { required_missing: [], required_stale: [], calculators_expected: 3, calculators_missing: [], target_index: true, target_in_sitemap: true },
    duration_sec: 4.2,
    manual_deploy_steps: ['Step 1 — git add ...', 'Step 2 — git push origin master'],
  },
}

describe('GAP-03 전체 사이트 Build', () => {
  it('runs the rebuild and shows the result summary + manual deploy steps (no deploy button)', async () => {
    const spy = vi.spyOn(apiClient, 'postSiteRebuild').mockResolvedValue(REBUILD_OK)
    const deploySpy = vi.spyOn(apiClient, 'postSitePagesDeploy')
    setup()
    const c = await card('⚙️ 전체 사이트 Build')
    await waitFor(() => expect(c.getByRole('button', { name: '⚙️ 전체 사이트 Build' })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: '⚙️ 전체 사이트 Build' }))
    await waitFor(() => expect(c.getByText('✅ Build 완료 — _site/ 갱신됨')).toBeInTheDocument())
    expect(spy).toHaveBeenCalledWith('af-ready')
    expect(c.getByText(/생성 12 · 건너뜀 1 · 오류 0/)).toBeInTheDocument()
    expect(c.getByText(/계산기 3종/)).toBeInTheDocument()
    expect(c.getByText('Step 2 — git push origin master')).toBeInTheDocument()
    expect(c.queryByRole('button', { name: /배포|push/i })).not.toBeInTheDocument()
    expect(deploySpy).not.toHaveBeenCalled()
  })

  it('shows loading and blocks duplicate clicks', async () => {
    const d = deferred()
    const spy = vi.spyOn(apiClient, 'postSiteRebuild').mockReturnValue(d.promise)
    setup()
    const c = await card('⚙️ 전체 사이트 Build')
    await waitFor(() => expect(c.getByRole('button', { name: '⚙️ 전체 사이트 Build' })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: '⚙️ 전체 사이트 Build' }))
    const busy = await c.findByRole('button', { name: 'Build 중...' })
    expect(busy).toBeDisabled()
    expect(c.getByText(/재빌드 진행 중/)).toBeInTheDocument()
    fireEvent.click(busy)
    expect(spy).toHaveBeenCalledTimes(1)
    d.resolve(REBUILD_OK)
    await waitFor(() => expect(c.getByText('✅ Build 완료 — _site/ 갱신됨')).toBeInTheDocument())
  })

  it('shows validation failure details', async () => {
    vi.spyOn(apiClient, 'postSiteRebuild').mockResolvedValue({
      success: true,
      data: { ...REBUILD_OK.data, ok: false, stage: 'validation', message: '⚠️ Build 결과 검증 실패 — 아래 항목을 확인하세요.',
        validation: { ...REBUILD_OK.data.validation, required_missing: ['sitemap.xml'], calculators_missing: ['af-other'] } },
    })
    setup()
    const c = await card('⚙️ 전체 사이트 Build')
    await waitFor(() => expect(c.getByRole('button', { name: '⚙️ 전체 사이트 Build' })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: '⚙️ 전체 사이트 Build' }))
    await waitFor(() => expect(c.getByText(/Build 결과 검증 실패/)).toBeInTheDocument())
    expect(c.getByText(/누락: sitemap.xml/)).toBeInTheDocument()
    expect(c.getByText(/누락: af-other/)).toBeInTheDocument()
    expect(c.queryByText(/배포 전 확인 체크리스트/)).not.toBeInTheDocument()
  })

  it('shows the error for LOCK_CONFLICT / TIMEOUT', async () => {
    vi.spyOn(apiClient, 'postSiteRebuild').mockResolvedValue(FAIL('LOCK_CONFLICT', '다른 사이트 작업이 진행 중입니다'))
    setup()
    const c = await card('⚙️ 전체 사이트 Build')
    await waitFor(() => expect(c.getByRole('button', { name: '⚙️ 전체 사이트 Build' })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: '⚙️ 전체 사이트 Build' }))
    await waitFor(() => expect(c.getByText('⚠ 다른 사이트 작업이 진행 중입니다')).toBeInTheDocument())
  })

  it('viewer sees Build disabled; non-READY calculator disabled too', async () => {
    setup({ user: VIEWER })
    let c = await card('⚙️ 전체 사이트 Build')
    await new Promise((r) => setTimeout(r, 0))
    expect(c.getByRole('button', { name: '⚙️ 전체 사이트 Build' })).toBeDisabled()
  })

  it('non-READY calculator: Build disabled with explanation', async () => {
    setup({ st: status({ registry_status: 'HOLD', is_legal_hold: true }) })
    const c = await card('⚙️ 전체 사이트 Build')
    expect(c.getByText(/READY 상태의 App Factory 계산기에서만/)).toBeInTheDocument()
    expect(c.getByRole('button', { name: '⚙️ 전체 사이트 Build' })).toBeDisabled()
  })
})

const PREP = { success: true, data: { slug: 'af-ready', name: 'AF 준비', calc_id: 'c1', source: 'app_factory', token: 'tok-1', expires_in: 120, scope: ['calculators DB 행', 'Registry v3(_af.yaml) 엔트리'], not_touched: ['data/workspace/_site', 'WordPress'] } }

describe('GAP-02 계산기 삭제 (2단계 확인)', () => {
  it('prepare shows the target, requires typing the slug, then deletes and returns to the list', async () => {
    const prep = vi.spyOn(apiClient, 'postCalculatorDeletePrepare').mockResolvedValue(PREP)
    const conf = vi.spyOn(apiClient, 'postCalculatorDeleteConfirm').mockResolvedValue({ success: true, data: { ok: true, slug: 'af-ready', deleted: true } })
    setup()
    const c = await card('관리')
    await waitFor(() => expect(c.getByRole('button', { name: '🗑 삭제' })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: '🗑 삭제' }))
    const box = within(await screen.findByTestId('calc-delete-confirm'))
    expect(prep).toHaveBeenCalledWith('af-ready')
    expect(conf).not.toHaveBeenCalled()                            // 1차 클릭만으로 삭제되지 않음
    expect(box.getByText('AF 준비')).toBeInTheDocument()
    expect(box.getByText(/삭제하지 않음: data\/workspace\/_site/)).toBeInTheDocument()
    const go = box.getByRole('button', { name: '정말 삭제' })
    expect(go).toBeDisabled()
    fireEvent.change(box.getByLabelText(/slug를 입력/), { target: { value: 'af-read' } })
    expect(go).toBeDisabled()
    fireEvent.change(box.getByLabelText(/slug를 입력/), { target: { value: 'af-ready' } })
    expect(go).toBeEnabled()
    fireEvent.click(go)
    await waitFor(() => expect(screen.getByText('계산기 목록 화면')).toBeInTheDocument())
    expect(conf).toHaveBeenCalledWith('af-ready', 'tok-1', 'af-ready')
  })

  it('blocks duplicate confirm clicks while deleting', async () => {
    const d = deferred()
    vi.spyOn(apiClient, 'postCalculatorDeletePrepare').mockResolvedValue(PREP)
    const conf = vi.spyOn(apiClient, 'postCalculatorDeleteConfirm').mockReturnValue(d.promise)
    setup()
    const c = await card('관리')
    await waitFor(() => expect(c.getByRole('button', { name: '🗑 삭제' })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: '🗑 삭제' }))
    const box = within(await screen.findByTestId('calc-delete-confirm'))
    fireEvent.change(box.getByLabelText(/slug를 입력/), { target: { value: 'af-ready' } })
    fireEvent.click(box.getByRole('button', { name: '정말 삭제' }))
    const busy = await box.findByRole('button', { name: '삭제 중...' })
    expect(busy).toBeDisabled()
    fireEvent.click(busy)
    expect(conf).toHaveBeenCalledTimes(1)
    d.resolve({ success: true, data: { ok: true } })
    await waitFor(() => expect(screen.getByText('계산기 목록 화면')).toBeInTheDocument())
  })

  it('on failure keeps the detail screen and shows the error', async () => {
    vi.spyOn(apiClient, 'postCalculatorDeletePrepare').mockResolvedValue(PREP)
    vi.spyOn(apiClient, 'postCalculatorDeleteConfirm').mockResolvedValue(FAIL('CONFIRMATION_INVALID', '삭제 확인이 유효하지 않습니다.'))
    setup()
    const c = await card('관리')
    await waitFor(() => expect(c.getByRole('button', { name: '🗑 삭제' })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: '🗑 삭제' }))
    const box = within(await screen.findByTestId('calc-delete-confirm'))
    fireEvent.change(box.getByLabelText(/slug를 입력/), { target: { value: 'af-ready' } })
    fireEvent.click(box.getByRole('button', { name: '정말 삭제' }))
    await waitFor(() => expect(c.getByText('⚠ 삭제 확인이 유효하지 않습니다.')).toBeInTheDocument())
    expect(screen.queryByText('계산기 목록 화면')).not.toBeInTheDocument()
    expect(c.getByRole('button', { name: '🗑 삭제' })).toBeInTheDocument()
  })

  it('prepare refusal (non App Factory) shows the error and never confirms', async () => {
    vi.spyOn(apiClient, 'postCalculatorDeletePrepare').mockResolvedValue(FAIL('DELETE_FORBIDDEN', 'App Factory 계산기만 삭제할 수 있습니다.'))
    const conf = vi.spyOn(apiClient, 'postCalculatorDeleteConfirm')
    setup()
    const c = await card('관리')
    await waitFor(() => expect(c.getByRole('button', { name: '🗑 삭제' })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: '🗑 삭제' }))
    await waitFor(() => expect(c.getByText('⚠ App Factory 계산기만 삭제할 수 있습니다.')).toBeInTheDocument())
    expect(conf).not.toHaveBeenCalled()
  })

  it('cancel closes the confirmation without deleting', async () => {
    vi.spyOn(apiClient, 'postCalculatorDeletePrepare').mockResolvedValue(PREP)
    const conf = vi.spyOn(apiClient, 'postCalculatorDeleteConfirm')
    setup()
    const c = await card('관리')
    await waitFor(() => expect(c.getByRole('button', { name: '🗑 삭제' })).toBeEnabled())
    fireEvent.click(c.getByRole('button', { name: '🗑 삭제' }))
    const box = within(await screen.findByTestId('calc-delete-confirm'))
    fireEvent.click(box.getByRole('button', { name: '취소' }))
    expect(screen.queryByTestId('calc-delete-confirm')).not.toBeInTheDocument()
    expect(conf).not.toHaveBeenCalled()
  })

  it('viewer sees the delete button disabled', async () => {
    const prep = vi.spyOn(apiClient, 'postCalculatorDeletePrepare')
    setup({ user: VIEWER })
    const c = await card('관리')
    await new Promise((r) => setTimeout(r, 0))
    expect(c.getByRole('button', { name: '🗑 삭제' })).toBeDisabled()
    fireEvent.click(c.getByRole('button', { name: '🗑 삭제' }))
    expect(prep).not.toHaveBeenCalled()
  })
})
