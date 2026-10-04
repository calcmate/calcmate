import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Calculators from '../pages/Calculators.jsx'
import CalculatorDetail from '../pages/CalculatorDetail.jsx'
import * as apiClient from '../api/client.js'

const LIST_OK = {
  success: true,
  data: {
    calculators: [
      { id: '1', slug: 'severance-pay', name: '퇴직금 계산기', db_status: 'active', is_deployed: true, is_legal_hold: false, registry_status: null, tier: null },
      { id: '2', slug: 'four-insurances', name: '4대보험 계산기', db_status: 'active', is_deployed: false, is_legal_hold: true, registry_status: 'HOLD', tier: 2 },
    ],
  },
  error: null,
  request_id: 'r1',
}

const FAILURE = { success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null }

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Calculators list page', () => {
  it('renders calculators from the API without hardcoding', async () => {
    vi.spyOn(apiClient, 'getCalculators').mockResolvedValue(LIST_OK)
    render(
      <MemoryRouter initialEntries={['/calculators']}>
        <Calculators />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('severance-pay')).toBeInTheDocument())
    expect(screen.getByText('four-insurances')).toBeInTheDocument()
    expect(screen.getByText('퇴직금 계산기')).toBeInTheDocument()
    expect(screen.getByText('LEGAL HOLD')).toBeInTheDocument()
  })

  it('filters the list by the search box (client-side, no extra API call)', async () => {
    const spy = vi.spyOn(apiClient, 'getCalculators').mockResolvedValue(LIST_OK)
    render(
      <MemoryRouter initialEntries={['/calculators']}>
        <Calculators />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('severance-pay')).toBeInTheDocument())

    fireEvent.change(screen.getByLabelText('계산기 검색'), { target: { value: 'four' } })

    expect(screen.queryByText('severance-pay')).not.toBeInTheDocument()
    expect(screen.getByText('four-insurances')).toBeInTheDocument()
    expect(spy).toHaveBeenCalledTimes(1) // 검색은 API를 재호출하지 않는다
  })

  it('shows the generic error UI when the API fails', async () => {
    vi.spyOn(apiClient, 'getCalculators').mockResolvedValue(FAILURE)
    render(
      <MemoryRouter initialEntries={['/calculators']}>
        <Calculators />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })

  it('the 새 계산기 button toggles the generate panel (STEP 4-H-6)', async () => {
    vi.spyOn(apiClient, 'getCalculators').mockResolvedValue(LIST_OK)
    render(
      <MemoryRouter initialEntries={['/calculators']}>
        <Calculators />
      </MemoryRouter>
    )
    const toggleBtn = screen.getByRole('button', { name: /새 계산기/ })
    expect(toggleBtn).toBeEnabled()
    expect(screen.queryByText('🏭 새 계산기 생성 (Mode A)')).not.toBeInTheDocument()

    fireEvent.click(toggleBtn)
    expect(screen.getByRole('button', { name: /닫기/ })).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByText('🏭 새 계산기 생성 (Mode A)')).toBeInTheDocument()
    )

    fireEvent.click(screen.getByRole('button', { name: /닫기/ }))
    expect(screen.queryByText('🏭 새 계산기 생성 (Mode A)')).not.toBeInTheDocument()
  })

  it('opens the generate panel automatically when navigated with ?new=1 (STEP V1-OPS-04)', async () => {
    vi.spyOn(apiClient, 'getCalculators').mockResolvedValue(LIST_OK)
    render(
      <MemoryRouter initialEntries={['/calculators?new=1']}>
        <Calculators />
      </MemoryRouter>
    )
    expect(screen.getByRole('button', { name: /닫기/ })).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByText('🏭 새 계산기 생성 (Mode A)')).toBeInTheDocument()
    )
  })
})

describe('CalculatorDetail page', () => {
  const DETAIL_OK = {
    success: true,
    data: { id: '1', slug: 'severance-pay', name: '퇴직금 계산기', db_status: 'active', updated_at: '2026-08-01T00:00:00', published_url: 'https://example.com/severance-pay/', is_deployed: true, registry_status: null, is_legal_hold: false, tier: null },
    error: null, request_id: 'r2',
  }
  const CONTENT_OK = {
    success: true,
    data: {
      seo_title: '퇴직금 계산기 제목',
      seo_description: '설명',
      faq: [{ question: 'Q1', answer: 'A1' }],
      article_content: '<h2>지급 대상</h2><p>본문</p>',
      article_length: 24,
      article_truncated: false,
    },
    error: null, request_id: 'r3',
  }
  const STATUS_OK = {
    success: true,
    data: {
      db_status: 'active', registry_status: null, is_legal_hold: false, tier: null,
      has_content: true, has_static_site: true, static_files: ['index.html', 'style.css', 'script.js'],
      published_url: 'https://example.com/severance-pay/', is_deployed: true,
    },
    error: null, request_id: 'r4',
  }

  function mockOk() {
    vi.spyOn(apiClient, 'getCalculator').mockResolvedValue(DETAIL_OK)
    vi.spyOn(apiClient, 'getCalculatorContent').mockResolvedValue(CONTENT_OK)
    vi.spyOn(apiClient, 'getCalculatorStatus').mockResolvedValue(STATUS_OK)
  }

  function renderDetail(slug = 'severance-pay') {
    return render(
      <MemoryRouter initialEntries={[`/calculators/${slug}`]}>
        <Routes>
          <Route path="/calculators/:slug" element={<CalculatorDetail />} />
        </Routes>
      </MemoryRouter>
    )
  }

  it('renders calculator name, status and content from the API', async () => {
    mockOk()
    renderDetail()
    await waitFor(() => expect(screen.getByRole('heading', { name: '퇴직금 계산기' })).toBeInTheDocument())
    expect(screen.getByText(/slug: severance-pay/)).toBeInTheDocument()
    expect(screen.getByText('퇴직금 계산기 제목')).toBeInTheDocument()
  })

  it('renders raw article HTML as escaped text, never as real markup (XSS 방지)', async () => {
    mockOk()
    const { container } = renderDetail()
    await waitFor(() => expect(screen.getByText(/지급 대상/)).toBeInTheDocument())
    // <h2>가 실제 heading 엘리먼트로 렌더링되면 안 된다 — 텍스트 그대로 노출되어야 한다.
    expect(container.querySelector('h2')).toBeNull()
    expect(screen.getByText('<h2>지급 대상</h2><p>본문</p>')).toBeInTheDocument()
  })

  // C-TEST-CONTRACT-FIX-02: STEP 18-F 당시의 "쓰기 미구현" 기대값을 현재 계약으로 갱신.
  // 삭제(GAP-02)·Deploy(P0-2)는 구현돼 있고 admin 전용이다 — viewer에게는 둘 다 비활성.
  // admin 삭제 흐름은 CalculatorGap0103.test.jsx가 검증한다.
  it('삭제/Deploy buttons are disabled for a viewer (admin-only writes)', async () => {
    mockOk()
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({ success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u0' })
    renderDetail()
    await waitFor(() => expect(screen.getByRole('button', { name: '🗑 삭제' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '🗑 삭제' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '🚀 Deploy' })).toBeDisabled()
  })

  describe('PromoteCard (STEP 4-H-1)', () => {
    const AUTH_VIEWER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u1' }
    const AUTH_ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u2' }

    const HOLD_STATUS = {
      ...STATUS_OK,
      data: { ...STATUS_OK.data, registry_status: 'HOLD', is_legal_hold: true },
    }
    const READY_STATUS = {
      ...STATUS_OK,
      data: { ...STATUS_OK.data, registry_status: 'READY', is_legal_hold: false },
    }

    function mockOkWithStatus(statusResponse, user) {
      vi.spyOn(apiClient, 'getCalculator').mockResolvedValue(DETAIL_OK)
      vi.spyOn(apiClient, 'getCalculatorContent').mockResolvedValue(CONTENT_OK)
      vi.spyOn(apiClient, 'getCalculatorStatus').mockResolvedValue(statusResponse)
      vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(user)
    }

    it('viewer sees the READY 전환 button disabled', async () => {
      mockOkWithStatus(HOLD_STATUS, AUTH_VIEWER)
      renderDetail()
      await waitFor(() => expect(screen.getByRole('button', { name: /READY 전환/ })).toBeInTheDocument())
      expect(screen.getByRole('button', { name: /READY 전환/ })).toBeDisabled()
    })

    it('admin sees the READY 전환 button enabled when status is HOLD', async () => {
      mockOkWithStatus(HOLD_STATUS, AUTH_ADMIN)
      renderDetail()
      await waitFor(() => expect(screen.getByRole('button', { name: /READY 전환/ })).toBeInTheDocument())
      expect(screen.getByRole('button', { name: /READY 전환/ })).toBeEnabled()
    })

    it('admin sees the button disabled and READY badge when already READY', async () => {
      mockOkWithStatus(READY_STATUS, AUTH_ADMIN)
      renderDetail()
      await waitFor(() => expect(screen.getByRole('button', { name: /READY 전환/ })).toBeInTheDocument())
      expect(screen.getByRole('button', { name: /READY 전환/ })).toBeDisabled()
      expect(screen.getAllByText('READY').length).toBeGreaterThan(0)
    })

    it('clicking promote succeeds and updates the status to READY', async () => {
      mockOkWithStatus(HOLD_STATUS, AUTH_ADMIN)
      const promoteSpy = vi.spyOn(apiClient, 'postCalculatorPromote').mockResolvedValue({
        success: true, data: { slug: 'severance-pay', status: 'READY', message: 'READY로 전환되었습니다' }, error: null, request_id: 'p1',
      })
      renderDetail()
      await waitFor(() => expect(screen.getByRole('button', { name: /READY 전환/ })).toBeEnabled())
      fireEvent.click(screen.getByRole('button', { name: /READY 전환/ }))
      await waitFor(() => expect(promoteSpy).toHaveBeenCalledTimes(1))
      expect(promoteSpy).toHaveBeenCalledWith('severance-pay')
      await waitFor(() => expect(screen.getByText('READY로 전환되었습니다')).toBeInTheDocument())
      expect(screen.getByRole('button', { name: /READY 전환/ })).toBeDisabled()
    })

    it('shows the actual error message on failure (e.g. checklist incomplete)', async () => {
      mockOkWithStatus(HOLD_STATUS, AUTH_ADMIN)
      vi.spyOn(apiClient, 'postCalculatorPromote').mockResolvedValue({
        success: false, data: null, error: { code: 'VALIDATION_ERROR', message: '체크리스트가 완료되지 않았습니다' }, request_id: null,
      })
      renderDetail()
      await waitFor(() => expect(screen.getByRole('button', { name: /READY 전환/ })).toBeEnabled())
      fireEvent.click(screen.getByRole('button', { name: /READY 전환/ }))
      await waitFor(() => expect(screen.getByText(/체크리스트가 완료되지 않았습니다/)).toBeInTheDocument())
      // 실패했으므로 여전히 HOLD 상태 — 버튼은 다시 활성화되어 재시도할 수 있어야 한다.
      expect(screen.getByRole('button', { name: /READY 전환/ })).toBeEnabled()
    })

    it('prevents duplicate submissions while a request is in flight', async () => {
      mockOkWithStatus(HOLD_STATUS, AUTH_ADMIN)
      let resolvePromote
      const promoteSpy = vi.spyOn(apiClient, 'postCalculatorPromote').mockReturnValue(
        new Promise((resolve) => { resolvePromote = resolve })
      )
      renderDetail()
      await waitFor(() => expect(screen.getByRole('button', { name: /READY 전환/ })).toBeEnabled())
      const button = screen.getByRole('button', { name: /전환/ })
      fireEvent.click(button)
      await waitFor(() => expect(button).toBeDisabled())
      fireEvent.click(button) // disabled 상태에서의 재클릭은 무시되어야 한다
      resolvePromote({ success: true, data: { slug: 'severance-pay', status: 'READY', message: 'ok' }, error: null, request_id: 'p2' })
      await waitFor(() => expect(promoteSpy).toHaveBeenCalledTimes(1))
    })
  })

  describe('ChecklistCard (STEP 4-H-2)', () => {
    const AUTH_VIEWER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u1' }
    const AUTH_ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u2' }

    const CHECKLIST_OK = {
      success: true,
      data: {
        slug: 'severance-pay',
        items: [
          { id: 'c1', severity: 'critical', label: '계산 공식 정확성', display_value: 'x', checked: false, checked_by: null, checked_at: null },
          { id: 'c2', severity: 'advisory', label: '참고 문구 확인', display_value: '', checked: true, checked_by: 'operator', checked_at: '2026-01-01T00:00:00Z' },
        ],
      },
      error: null, request_id: 'chk1',
    }

    function mockOkWithChecklist(checklistResponse, user) {
      vi.spyOn(apiClient, 'getCalculator').mockResolvedValue(DETAIL_OK)
      vi.spyOn(apiClient, 'getCalculatorContent').mockResolvedValue(CONTENT_OK)
      vi.spyOn(apiClient, 'getCalculatorStatus').mockResolvedValue(STATUS_OK)
      vi.spyOn(apiClient, 'getCalculatorChecklist').mockResolvedValue(checklistResponse)
      vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(user)
    }

    it('viewer sees checkboxes and save button disabled (read-only)', async () => {
      mockOkWithChecklist(CHECKLIST_OK, AUTH_VIEWER)
      renderDetail()
      await waitFor(() => expect(screen.getByText('계산 공식 정확성')).toBeInTheDocument())
      expect(screen.getByLabelText('계산 공식 정확성')).toBeDisabled()
      expect(screen.getByLabelText('참고 문구 확인')).toBeDisabled()
      expect(screen.getByRole('button', { name: /체크리스트 저장/ })).toBeDisabled()
    })

    it('admin sees checkboxes and save button enabled', async () => {
      mockOkWithChecklist(CHECKLIST_OK, AUTH_ADMIN)
      renderDetail()
      await waitFor(() => expect(screen.getByText('계산 공식 정확성')).toBeInTheDocument())
      expect(screen.getByLabelText('계산 공식 정확성')).toBeEnabled()
      expect(screen.getByRole('button', { name: /체크리스트 저장/ })).toBeEnabled()
    })

    it('toggling a checkbox updates its visual checked state', async () => {
      mockOkWithChecklist(CHECKLIST_OK, AUTH_ADMIN)
      renderDetail()
      await waitFor(() => expect(screen.getByLabelText('계산 공식 정확성')).toBeInTheDocument())
      const checkbox = screen.getByLabelText('계산 공식 정확성')
      expect(checkbox).not.toBeChecked()
      fireEvent.click(checkbox)
      expect(checkbox).toBeChecked()
    })

    it('saving succeeds and sends only the changed item', async () => {
      mockOkWithChecklist(CHECKLIST_OK, AUTH_ADMIN)
      const patchSpy = vi.spyOn(apiClient, 'patchCalculatorChecklist').mockResolvedValue({
        success: true,
        data: { slug: 'severance-pay', items: [
          { id: 'c1', severity: 'critical', label: '계산 공식 정확성', display_value: 'x', checked: true, checked_by: 'dev-admin', checked_at: '2026-09-04T00:00:00Z' },
          { id: 'c2', severity: 'advisory', label: '참고 문구 확인', display_value: '', checked: true, checked_by: 'operator', checked_at: '2026-01-01T00:00:00Z' },
        ] },
        error: null, request_id: 'chk2',
      })
      renderDetail()
      await waitFor(() => expect(screen.getByLabelText('계산 공식 정확성')).toBeInTheDocument())
      fireEvent.click(screen.getByLabelText('계산 공식 정확성'))
      fireEvent.click(screen.getByRole('button', { name: /체크리스트 저장/ }))
      await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1))
      expect(patchSpy).toHaveBeenCalledWith('severance-pay', [{ id: 'c1', checked: true }])
      await waitFor(() => expect(screen.getByText('체크리스트 저장 완료')).toBeInTheDocument())
    })

    it('shows the actual API error message on save failure and allows retry', async () => {
      mockOkWithChecklist(CHECKLIST_OK, AUTH_ADMIN)
      vi.spyOn(apiClient, 'patchCalculatorChecklist').mockResolvedValue({
        success: false, data: null, error: { code: 'VALIDATION_ERROR', message: '알 수 없는 체크리스트 항목 id' }, request_id: null,
      })
      renderDetail()
      await waitFor(() => expect(screen.getByLabelText('계산 공식 정확성')).toBeInTheDocument())
      fireEvent.click(screen.getByLabelText('계산 공식 정확성'))
      fireEvent.click(screen.getByRole('button', { name: /체크리스트 저장/ }))
      await waitFor(() => expect(screen.getByText(/알 수 없는 체크리스트 항목 id/)).toBeInTheDocument())
      expect(screen.getByRole('button', { name: /체크리스트 저장/ })).toBeEnabled()
    })

    it('prevents duplicate submissions while a save request is in flight', async () => {
      mockOkWithChecklist(CHECKLIST_OK, AUTH_ADMIN)
      let resolvePatch
      const patchSpy = vi.spyOn(apiClient, 'patchCalculatorChecklist').mockReturnValue(
        new Promise((resolve) => { resolvePatch = resolve })
      )
      renderDetail()
      await waitFor(() => expect(screen.getByLabelText('계산 공식 정확성')).toBeInTheDocument())
      fireEvent.click(screen.getByLabelText('계산 공식 정확성'))
      const saveBtn = screen.getByRole('button', { name: /체크리스트 저장/ })
      fireEvent.click(saveBtn)
      await waitFor(() => expect(saveBtn).toBeDisabled())
      fireEvent.click(saveBtn) // 저장 중 재클릭은 무시되어야 한다
      resolvePatch({
        success: true,
        data: { slug: 'severance-pay', items: CHECKLIST_OK.data.items },
        error: null, request_id: 'chk3',
      })
      await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1))
    })
  })

  it('shows a not-found message for an unknown slug', async () => {
    vi.spyOn(apiClient, 'getCalculator').mockResolvedValue({
      success: false, data: null, error: { code: 'NOT_FOUND', message: 'calculator not found: nope' }, request_id: null,
    })
    vi.spyOn(apiClient, 'getCalculatorContent').mockResolvedValue({
      success: false, data: null, error: { code: 'NOT_FOUND', message: 'calculator not found: nope' }, request_id: null,
    })
    vi.spyOn(apiClient, 'getCalculatorStatus').mockResolvedValue({
      success: false, data: null, error: { code: 'NOT_FOUND', message: 'calculator not found: nope' }, request_id: null,
    })
    renderDetail('nope')
    await waitFor(() => expect(screen.getByText(/존재하지 않는 계산기/)).toBeInTheDocument())
  })
})
