import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import Publish from '../pages/Publish.jsx'
import Trash from '../pages/Trash.jsx'
import * as apiClient from '../api/client.js'

const OVERVIEW_OK = {
  success: true,
  data: {
    total: 57,
    by_status: { 발행완료: 7, 재처리완료: 18, 품질보류: 32 },
    articles: [],
  },
  error: null,
  request_id: 'p1',
}
const PUBLISH_LIST_OK = {
  success: true,
  data: {
    total: 2,
    articles: [
      { id: 'a1', title: '2026 퇴직금 계산법 완벽해석', status: '발행완료', published_at: '2026-08-05 18:18:44', url: 'http://salarymate.test/post-1/', wp_post_id: '179' },
      { id: 'a2', title: '<script>alert(1)</script> 위험한 제목', status: '발행완료', published_at: '2026-08-06 09:00:00', url: '', wp_post_id: '' },
    ],
  },
  error: null,
  request_id: 'p2',
}
const TRASH_EMPTY = { success: true, data: { total: 0, articles: [] }, error: null, request_id: 't1' }
const TRASH_WITH_DATA = {
  success: true,
  data: {
    total: 1,
    articles: [{ id: 'x1', title: '휴지통 글', status: '휴지통', published_at: '2026-08-01 00:00:00' }],
  },
  error: null,
  request_id: 't2',
}
const FAILURE = { success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null }
const AUTH_401 = { success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'Unauthorized' }, request_id: null }
const AUTH_VIEWER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u1' }
const AUTH_ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u2' }

function mockPublish({ user = AUTH_401 } = {}) {
  vi.spyOn(apiClient, 'getPublishOverview').mockResolvedValue(OVERVIEW_OK)
  vi.spyOn(apiClient, 'getPublishArticles').mockResolvedValue(PUBLISH_LIST_OK)
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(user)
}

function mockTrash({ data = TRASH_WITH_DATA, user = AUTH_401 } = {}) {
  vi.spyOn(apiClient, 'getTrashArticles').mockResolvedValue(data)
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(user)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Publish page (/publish)', () => {
  it('shows a read-only notice when not admin (401/anonymous)', async () => {
    mockPublish({ user: AUTH_401 })
    render(<Publish />)
    await waitFor(() => expect(screen.getByText(/현재 조회 전용입니다/)).toBeInTheDocument())
    expect(screen.getByText(/admin 권한이 필요합니다/)).toBeInTheDocument()
  })

  it('shows an admin notice when authenticated as admin', async () => {
    mockPublish({ user: AUTH_ADMIN })
    render(<Publish />)
    await waitFor(() => expect(screen.getByText(/admin 권한으로 로그인되어 있습니다/)).toBeInTheDocument())
  })

  it('renders real total and per-status counts, not hardcoded', async () => {
    mockPublish()
    render(<Publish />)
    await waitFor(() => expect(screen.getByText('57')).toBeInTheDocument())
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByText('18')).toBeInTheDocument()
    expect(screen.getByText('32')).toBeInTheDocument()
  })

  it('renders article titles as escaped text, never as real markup (XSS 방지)', async () => {
    mockPublish()
    render(<Publish />)
    await waitFor(() => expect(screen.getByText(/2026 퇴직금 계산법 완벽해석/)).toBeInTheDocument())
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument()
    expect(document.querySelector('script[data-injected]')).not.toBeInTheDocument()
  })

  it('shows "-" for missing URL instead of a broken link', async () => {
    mockPublish()
    render(<Publish />)
    await waitFor(() => expect(screen.getAllByText('링크').length).toBe(1))
  })

  it('viewer (non-admin): Edit/Trash buttons are rendered but disabled', async () => {
    mockPublish({ user: AUTH_VIEWER })
    render(<Publish />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: '수정' }).length).toBe(2))
    for (const btn of screen.getAllByRole('button', { name: '수정' })) expect(btn).toBeDisabled()
    for (const btn of screen.getAllByRole('button', { name: '휴지통 이동' })) expect(btn).toBeDisabled()
  })

  it('admin: Edit/Trash buttons are enabled', async () => {
    mockPublish({ user: AUTH_ADMIN })
    render(<Publish />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: '수정' }).length).toBe(2))
    for (const btn of screen.getAllByRole('button', { name: '수정' })) expect(btn).toBeEnabled()
    for (const btn of screen.getAllByRole('button', { name: '휴지통 이동' })) expect(btn).toBeEnabled()
  })

  it('admin: Trash confirmation mismatch keeps the run button disabled and sends 0 requests', async () => {
    mockPublish({ user: AUTH_ADMIN })
    const postTrashSpy = vi.spyOn(apiClient, 'postTrash').mockResolvedValue({ success: true, data: {}, error: null, request_id: 'x' })
    render(<Publish />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: '휴지통 이동' }).length).toBe(2))
    fireEvent.click(screen.getAllByRole('button', { name: '휴지통 이동' })[0])
    const input = await screen.findByLabelText('trash-confirm-a1')
    fireEvent.change(input, { target: { value: 'not-trash' } })
    const runButtons = screen.getAllByRole('button', { name: '실행' })
    expect(runButtons[0]).toBeDisabled()
    fireEvent.click(runButtons[0])
    expect(postTrashSpy).not.toHaveBeenCalled()
  })

  it('admin: correct Trash confirmation enables the run button and calls the API once', async () => {
    mockPublish({ user: AUTH_ADMIN })
    const postTrashSpy = vi.spyOn(apiClient, 'postTrash').mockResolvedValue({ success: true, data: {}, error: null, request_id: 'x' })
    render(<Publish />)
    await waitFor(() => expect(screen.getAllByRole('button', { name: '휴지통 이동' }).length).toBe(2))
    fireEvent.click(screen.getAllByRole('button', { name: '휴지통 이동' })[0])
    const input = await screen.findByLabelText('trash-confirm-a1')
    fireEvent.change(input, { target: { value: 'TRASH' } })
    const runButton = screen.getAllByRole('button', { name: '실행' })[0]
    expect(runButton).toBeEnabled()
    fireEvent.click(runButton)
    await waitFor(() => expect(postTrashSpy).toHaveBeenCalledTimes(1))
    expect(postTrashSpy).toHaveBeenCalledWith('a1', 'TRASH')
  })

  it('shows the generic error UI when the publish API fails', async () => {
    vi.spyOn(apiClient, 'getPublishOverview').mockResolvedValue(FAILURE)
    vi.spyOn(apiClient, 'getPublishArticles').mockResolvedValue(PUBLISH_LIST_OK)
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_401)
    render(<Publish />)
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })

  it('handles getCurrentUser 401 gracefully (no crash, treated as non-admin)', async () => {
    mockPublish({ user: AUTH_401 })
    render(<Publish />)
    await waitFor(() => expect(screen.getByText('57')).toBeInTheDocument())
    expect(screen.getByText(/admin 권한이 필요합니다/)).toBeInTheDocument()
  })
})

describe('Trash page (/trash)', () => {
  it('shows a read-only notice when not admin', async () => {
    mockTrash({ data: TRASH_EMPTY, user: AUTH_401 })
    render(<Trash />)
    await waitFor(() => expect(screen.getByText(/현재 조회 전용입니다/)).toBeInTheDocument())
    expect(screen.getByText('휴지통이 비어 있습니다.')).toBeInTheDocument()
  })

  it('renders real trash article data when present', async () => {
    mockTrash()
    render(<Trash />)
    await waitFor(() => expect(screen.getByText('휴지통 글')).toBeInTheDocument())
    expect(screen.getByText('휴지통 Article: 1')).toBeInTheDocument()
  })

  it('viewer: Restore button is rendered but disabled', async () => {
    mockTrash({ user: AUTH_VIEWER })
    render(<Trash />)
    await waitFor(() => expect(screen.getByRole('button', { name: '복원' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '복원' })).toBeDisabled()
  })

  it('admin: Restore button is enabled, and confirmation mismatch sends 0 requests', async () => {
    mockTrash({ user: AUTH_ADMIN })
    const restoreSpy = vi.spyOn(apiClient, 'postTrashRestore').mockResolvedValue({ success: true, data: {}, error: null, request_id: 'x' })
    render(<Trash />)
    await waitFor(() => expect(screen.getByRole('button', { name: '복원' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '복원' }))
    const input = await screen.findByLabelText('restore-confirm-x1')
    fireEvent.change(input, { target: { value: 'nope' } })
    fireEvent.click(screen.getByRole('button', { name: '실행' }))
    expect(restoreSpy).not.toHaveBeenCalled()
  })

  it('admin: correct RESTORE confirmation calls the API exactly once', async () => {
    mockTrash({ user: AUTH_ADMIN })
    const restoreSpy = vi.spyOn(apiClient, 'postTrashRestore').mockResolvedValue({ success: true, data: {}, error: null, request_id: 'x' })
    render(<Trash />)
    await waitFor(() => expect(screen.getByRole('button', { name: '복원' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '복원' }))
    const input = await screen.findByLabelText('restore-confirm-x1')
    fireEvent.change(input, { target: { value: 'RESTORE' } })
    fireEvent.click(screen.getByRole('button', { name: '실행' }))
    await waitFor(() => expect(restoreSpy).toHaveBeenCalledTimes(1))
    expect(restoreSpy).toHaveBeenCalledWith('x1', 'RESTORE')
  })

  it('does not render a Permanent Delete button anywhere', async () => {
    mockTrash({ user: AUTH_ADMIN })
    render(<Trash />)
    await waitFor(() => expect(screen.getByText('휴지통 글')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /영구삭제/ })).not.toBeInTheDocument()
  })

  it('shows the generic error UI when the trash API fails', async () => {
    vi.spyOn(apiClient, 'getTrashArticles').mockResolvedValue(FAILURE)
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(AUTH_401)
    render(<Trash />)
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })
})

describe('API client — STEP 18-P/18-R', () => {
  it('exposes exactly the expected GET + admin-write functions, nothing unexpected', () => {
    expect(typeof apiClient.getPublishOverview).toBe('function')
    expect(typeof apiClient.getPublishArticles).toBe('function')
    expect(typeof apiClient.getTrashArticles).toBe('function')
    expect(typeof apiClient.postPublishEdit).toBe('function')
    expect(typeof apiClient.postTrash).toBe('function')
    expect(typeof apiClient.postTrashRestore).toBe('function')

    // CALCMATE-BLOG-PUBLISHING-POLICY-FASTAPI-REACT-CONNECTION-IMPLEMENT-01:
    // patchPublishingPolicy/patchAutoPublishing이 이름에 "Publishing"을 포함해
    // 위 /publish|trash/i에 걸리지만, require_admin 뒤에서 정당하게 추가된
    // admin-write다(Publishing Policy/Auto Publishing 저장).
    const allowedWrites = new Set([
      'postPublishEdit', 'postTrash', 'postTrashRestore',
      'patchPublishingPolicy', 'patchAutoPublishing',
    ])
    const exportedNames = Object.keys(apiClient)
    const suspicious = exportedNames.filter(
      (n) => /publish|trash/i.test(n) && /create|update|delete|patch|save|write|restore|edit/i.test(n) && !allowedWrites.has(n)
    )
    expect(suspicious).toEqual([])
  })
})
