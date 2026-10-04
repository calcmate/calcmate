import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import SiteManagementPanel from '../components/SiteManagementPanel.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-07: Site Management Update/Override/Reset UI 검증. 실제
// putUpdateSite/postSaveOverride/postResetOverride는 이 파일의 어떤
// 테스트에서도 호출하지 않는다 — 항상 mock.

const SITE_SUMMARY = {
  site_id: 's1', site_name: '기존사이트', domain: 'old.example.com', site_type: 'calculator',
  status: 'active', platforms: [], wordpress_configured: true,
}

const SITE_DETAIL = {
  ...SITE_SUMMARY,
  research_ai: 'gemini_flash', writing_ai: 'gpt4o', review_ai: 'claude_sonnet',
  wordpress_url: 'https://old.example.com', site_tags: '기존태그',
  seo_keyword_count: '', seo_length: '', daily_override: '',
  image_mode: '', telegram_enabled: '', analytics_enabled: '', calc_active: [],
}

beforeEach(() => {
  vi.spyOn(apiClient, 'getSites').mockResolvedValue({
    success: true, data: { sites: [SITE_SUMMARY] }, error: null, request_id: 'l0',
  })
  vi.spyOn(apiClient, 'getSite').mockResolvedValue({
    success: true, data: SITE_DETAIL, error: null, request_id: 'd0',
  })
  vi.spyOn(apiClient, 'getCalculators').mockResolvedValue({
    success: true, data: { calculators: [{ name: 'calc-a' }, { name: 'calc-b' }] }, error: null, request_id: 'c0',
  })
})

afterEach(() => {
  vi.restoreAllMocks()
})

function mockAdmin() {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
    success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1',
  })
}

function mockViewer() {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
    success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2',
  })
}

async function openEditPanel() {
  render(<SiteManagementPanel />)
  await waitFor(() => expect(screen.getByText('기존사이트')).toBeInTheDocument())
  fireEvent.click(screen.getByRole('button', { name: /✏️ 수정/ }))
  await waitFor(() => expect(screen.getByText('✏️ 기본 정보 수정')).toBeInTheDocument())
}

// "도메인" 라벨은 별도 사이트 추가(Create) 폼에도 존재하므로, 기본 정보 수정
// 폼에 한정해 조회한다(SiteCreateForm 등 화면의 다른 부분과 혼동 방지).
function basicForm() {
  return screen.getByText('✏️ 기본 정보 수정').closest('form')
}

describe('Site edit panel (STEP P2-07)', () => {
  it('loads current values via getSite when expanded', async () => {
    mockAdmin()
    await openEditPanel()
    expect(within(basicForm()).getByLabelText('사이트명')).toHaveValue('기존사이트')
    expect(within(basicForm()).getByLabelText('도메인')).toHaveValue('old.example.com')
    expect(within(basicForm()).getByLabelText('카테고리')).toHaveValue('기존태그')
  })

  it('shows a WordPress-configured status badge, never real credentials', async () => {
    mockAdmin()
    await openEditPanel()
    expect(screen.getByText(/WordPress 설정됨/)).toBeInTheDocument()
    expect(screen.queryByLabelText(/WordPress ID/)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/App Password/)).not.toBeInTheDocument()
  })

  it('disables the basic-info save button for a non-admin viewer', async () => {
    mockViewer()
    await openEditPanel()
    expect(screen.getByRole('button', { name: /💾 수정 저장/ })).toBeDisabled()
  })

  it('submits basic-info changes via putUpdateSite and shows the saved state', async () => {
    mockAdmin()
    const spy = vi.spyOn(apiClient, 'putUpdateSite').mockResolvedValue({
      success: true, data: { ...SITE_DETAIL, site_name: '변경된이름' }, error: null, request_id: 'u1',
    })
    await openEditPanel()
    fireEvent.change(within(basicForm()).getByLabelText('사이트명'), { target: { value: '변경된이름' } })
    fireEvent.click(screen.getByRole('button', { name: /💾 수정 저장/ }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('s1', expect.objectContaining({ site_name: '변경된이름' })))
    await waitFor(() => expect(screen.getByText('✅ 저장되었습니다')).toBeInTheDocument())
  })

  it('shows a failure message when the basic-info save fails', async () => {
    mockAdmin()
    vi.spyOn(apiClient, 'putUpdateSite').mockResolvedValue({
      success: false, data: null, error: { code: 'VALIDATION_ERROR', message: '저장 실패했습니다' }, request_id: null,
    })
    await openEditPanel()
    fireEvent.click(screen.getByRole('button', { name: /💾 수정 저장/ }))
    await waitFor(() => expect(screen.getByText(/저장 실패했습니다/)).toBeInTheDocument())
  })

  it('pre-populates the Override form with current values', async () => {
    mockAdmin()
    await openEditPanel()
    expect(screen.getByText('⚙️ Site Settings (Override)')).toBeInTheDocument()
    expect(screen.getByLabelText('Research AI')).toHaveValue('gemini_flash')
    expect(screen.getByLabelText('WordPress URL')).toHaveValue('https://old.example.com')
    expect(screen.getByLabelText('calc-a')).not.toBeChecked()
  })

  it('submits Override changes via postSaveOverride', async () => {
    mockAdmin()
    const spy = vi.spyOn(apiClient, 'postSaveOverride').mockResolvedValue({
      success: true, data: SITE_DETAIL, error: null, request_id: 'o1',
    })
    await openEditPanel()
    fireEvent.click(screen.getByLabelText('calc-a'))
    fireEvent.click(screen.getByRole('button', { name: /💾 Override 저장/ }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('s1', expect.objectContaining({ calc_active: ['calc-a'] })))
    await waitFor(() => expect(screen.getByText('✅ 저장되었습니다')).toBeInTheDocument())
  })

  it('calls postResetOverride when the reset button is clicked', async () => {
    mockAdmin()
    const spy = vi.spyOn(apiClient, 'postResetOverride').mockResolvedValue({
      success: true, data: { ...SITE_DETAIL, research_ai: '' }, error: null, request_id: 'r1',
    })
    await openEditPanel()
    fireEvent.click(screen.getByRole('button', { name: /Override 초기화/ }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('s1'))
    await waitFor(() => expect(screen.getByText(/초기화되었습니다/)).toBeInTheDocument())
  })

  it('disables Override save/reset buttons for a non-admin viewer', async () => {
    mockViewer()
    await openEditPanel()
    expect(screen.getByRole('button', { name: /💾 Override 저장/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Override 초기화/ })).toBeDisabled()
  })

  it('re-fetches the site list after a successful save', async () => {
    mockAdmin()
    const listSpy = vi.spyOn(apiClient, 'getSites').mockResolvedValue({
      success: true, data: { sites: [SITE_SUMMARY] }, error: null, request_id: 'l1',
    })
    vi.spyOn(apiClient, 'putUpdateSite').mockResolvedValue({
      success: true, data: SITE_DETAIL, error: null, request_id: 'u2',
    })
    await openEditPanel()
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole('button', { name: /💾 수정 저장/ }))
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(2))
  })
})
