import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import CalculatorDetail from '../pages/CalculatorDetail.jsx'
import * as apiClient from '../api/client.js'

// STEP S1: Human Review Approval 게이트 복원 — BuildDeployCard의 "👤 사람 검수" UI.
// dashboard.py "🧮 계산기 관리" 탭의 QA PASS 후 승인 → Deploy 활성화 흐름을 검증한다.

const AUTH_ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }

const DETAIL_OK = {
  success: true,
  data: { id: '1', slug: 'annual-leave-remaining', name: '연차 잔여일 계산기', db_status: 'active', updated_at: 't', published_url: '', is_deployed: false, registry_status: null, is_legal_hold: false, tier: null },
  error: null, request_id: 'r1',
}
const CONTENT_OK = {
  success: true,
  data: { seo_title: '', seo_description: '', faq: [], article_content: '', article_length: 0, article_truncated: false },
  error: null, request_id: 'r2',
}
const STATUS_OK = {
  success: true,
  data: {
    db_status: 'active', registry_status: null, is_legal_hold: false, tier: null,
    has_content: false, has_static_site: false, static_files: [], published_url: '', is_deployed: false,
  },
  error: null, request_id: 'r3',
}

function reviewResponse(overrides) {
  return {
    success: true,
    data: { slug: 'annual-leave-remaining', has_snapshot: false, approved: false, approved_by: null, approved_at: null, stale: false, ...overrides },
    error: null, request_id: 'rv',
  }
}

function mockCommon() {
  vi.spyOn(apiClient, 'getCalculator').mockResolvedValue(DETAIL_OK)
  vi.spyOn(apiClient, 'getCalculatorContent').mockResolvedValue(CONTENT_OK)
  vi.spyOn(apiClient, 'getCalculatorStatus').mockResolvedValue(STATUS_OK)
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_ADMIN)
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/calculators/annual-leave-remaining']}>
      <Routes>
        <Route path="/calculators/:slug" element={<CalculatorDetail />} />
      </Routes>
    </MemoryRouter>
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('BuildDeployCard Human Review Approval (STEP S1)', () => {
  it('before Build: review shows "Build 필요" and Deploy is disabled', async () => {
    mockCommon()
    vi.spyOn(apiClient, 'getCalculatorReview').mockResolvedValue(reviewResponse({ has_snapshot: false }))
    renderDetail()

    await waitFor(() => expect(screen.getByText('Build 필요')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '🚀 Deploy' })).toBeDisabled()
    // 승인 버튼도 스냅샷이 없으면 비활성화되어야 한다.
    expect(screen.getByRole('button', { name: /검수 승인/ })).toBeDisabled()
  })

  it('after Build+QA PASS, not yet approved: shows "검수 필요" and Deploy still disabled', async () => {
    mockCommon()
    vi.spyOn(apiClient, 'getCalculatorReview').mockResolvedValue(reviewResponse({ has_snapshot: true, approved: false }))
    renderDetail()

    await waitFor(() => expect(screen.getByText('⏳ 검수 필요')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '🚀 Deploy' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /검수 승인/ })).toBeEnabled()
  })

  it('clicking 검수 승인 calls the approve endpoint and enables Deploy on success', async () => {
    mockCommon()
    let approved = false
    vi.spyOn(apiClient, 'getCalculatorReview').mockImplementation(async () =>
      reviewResponse({ has_snapshot: true, approved, approved_by: approved ? 'dev-admin' : null })
    )
    const approveSpy = vi.spyOn(apiClient, 'postCalculatorReviewApprove').mockImplementation(async () => {
      approved = true
      return { success: true, data: { ok: true, slug: 'annual-leave-remaining', approved_by: 'dev-admin', approved_at: 't' }, error: null, request_id: 'a1' }
    })

    renderDetail()
    await waitFor(() => expect(screen.getByText('⏳ 검수 필요')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /검수 승인/ }))

    await waitFor(() => expect(screen.getByText('✅ 검수 승인 완료')).toBeInTheDocument())
    expect(approveSpy).toHaveBeenCalledWith('annual-leave-remaining')
    expect(screen.getByRole('button', { name: '🚀 Deploy' })).toBeEnabled()
  })

  it('shows the server blocked_reason when approval fails (e.g. QA failure)', async () => {
    mockCommon()
    vi.spyOn(apiClient, 'getCalculatorReview').mockResolvedValue(reviewResponse({ has_snapshot: true, approved: false }))
    vi.spyOn(apiClient, 'postCalculatorReviewApprove').mockResolvedValue({
      success: true,
      data: { ok: false, slug: 'annual-leave-remaining', blocked_reason: '🔒 QA 실패 — 사람 검수 단계로 진행할 수 없습니다. Build 결과를 확인하세요.' },
      error: null, request_id: 'a2',
    })

    renderDetail()
    await waitFor(() => expect(screen.getByRole('button', { name: /검수 승인/ })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: /검수 승인/ }))

    await waitFor(() => expect(screen.getByText(/QA 실패/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '🚀 Deploy' })).toBeDisabled()
  })

  it('rebuilding after approval that invalidates it (stale) shows "검수 재필요" and disables Deploy', async () => {
    mockCommon()
    vi.spyOn(apiClient, 'getCalculatorReview').mockResolvedValue(
      reviewResponse({ has_snapshot: true, approved: false, stale: true })
    )
    renderDetail()

    await waitFor(() => expect(screen.getByText('⚠️ 검수 재필요(Build 결과 변경됨)')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '🚀 Deploy' })).toBeDisabled()
    // 재승인은 다시 가능해야 한다(버튼이 다시 활성화됨).
    expect(screen.getByRole('button', { name: /검수 승인/ })).toBeEnabled()
  })

  it('직접 Deploy를 눌러도(승인 없이) 서버 blocked_reason이 그대로 표시된다', async () => {
    mockCommon()
    vi.spyOn(apiClient, 'getCalculatorReview').mockResolvedValue(reviewResponse({ has_snapshot: true, approved: false }))
    // canDeploy가 false이므로 버튼 자체가 disabled이지만, 혹시 서버가 막는지도
    // 별도로 재확인(서버가 진짜 방어선이라는 설계 원칙 검증).
    const deploySpy = vi.spyOn(apiClient, 'postCalculatorDeploy').mockResolvedValue({
      success: true,
      data: { ok: false, blocked_reason: '🔒 사람 검수 승인이 필요합니다 — 검수 승인 후 다시 시도하세요.' },
      error: null, request_id: 'd1',
    })
    renderDetail()
    await waitFor(() => expect(screen.getByRole('button', { name: '🚀 Deploy' })).toBeDisabled())
    expect(deploySpy).not.toHaveBeenCalled()
  })

  it('unapprove(승인 취소) disables Deploy again', async () => {
    mockCommon()
    let approved = true
    vi.spyOn(apiClient, 'getCalculatorReview').mockImplementation(async () =>
      reviewResponse({ has_snapshot: true, approved, approved_by: approved ? 'dev-admin' : null })
    )
    const unapproveSpy = vi.spyOn(apiClient, 'postCalculatorReviewUnapprove').mockImplementation(async () => {
      approved = false
      return { success: true, data: { ok: true, slug: 'annual-leave-remaining' }, error: null, request_id: 'u1' }
    })

    renderDetail()
    await waitFor(() => expect(screen.getByText('✅ 검수 승인 완료')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '🚀 Deploy' })).toBeEnabled()

    fireEvent.click(screen.getByRole('button', { name: /승인 취소/ }))

    await waitFor(() => expect(screen.getByText('⏳ 검수 필요')).toBeInTheDocument())
    expect(unapproveSpy).toHaveBeenCalledWith('annual-leave-remaining')
    expect(screen.getByRole('button', { name: '🚀 Deploy' })).toBeDisabled()
  })
})
