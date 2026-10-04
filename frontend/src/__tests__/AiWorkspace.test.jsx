import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AiWorkspace from '../pages/AiWorkspace.jsx'
import App from '../App.jsx'
import * as apiClient from '../api/client.js'

// AI-WORKSPACE-02 — AI Workspace 화면. 모든 client 호출은 mock(실제 AI/파일 쓰기 없음).
const ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }
const ok = (data) => ({ success: true, data, error: null, request_id: 'r' })
const fail = (code, message) => ({ success: false, data: null, error: { code, message }, request_id: 'r' })
const MODELS = ok({
  roles: [
    { id: 'orchestrator', label: '총괄 (GPT)', provider: 'openai', model: 'gpt-4o' },
    { id: 'code', label: '코드 (Claude)', provider: 'claude', model: 'claude-sonnet-4-6' },
    { id: 'research', label: '리서치 (Gemini)', provider: 'gemini', model: 'gemini-2.5-flash' },
  ],
  default: 'orchestrator', repos: ['sites', 'calculators', 'articles', 'templates'],
})

beforeEach(() => {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN)
  vi.spyOn(apiClient, 'getWorkspaceModels').mockResolvedValue(MODELS)
  vi.spyOn(apiClient, 'getWorkspaceContextFiles').mockResolvedValue(ok({ files: ['main.py', 'docs/readme.md'] }))
})

afterEach(() => {
  vi.restoreAllMocks()
})

async function renderReady() {
  render(<AiWorkspace />)
  await waitFor(() => expect(screen.getByLabelText('역할 / 모델')).toHaveValue('orchestrator'))
  await waitFor(() => expect(screen.getByLabelText('메시지 입력')).toBeEnabled())
}

function typeAndSend(text) {
  fireEvent.change(screen.getByLabelText('메시지 입력'), { target: { value: text } })
  fireEvent.click(screen.getByRole('button', { name: '전송' }))
}

describe('AiWorkspace page', () => {
  it('is reachable via /ai-workspace route and the sidebar link', async () => {
    render(<MemoryRouter initialEntries={['/ai-workspace']}><App /></MemoryRouter>)
    expect(await screen.findByRole('heading', { name: '💬 AI Workspace' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '💬 AI Workspace' })).toHaveAttribute('href', '/ai-workspace')
    expect(screen.getByRole('link', { name: '🤖 AI Assistant' })).toHaveAttribute('href', '/assistant')
  })

  it('role selection is sent with the chat', async () => {
    const spy = vi.spyOn(apiClient, 'postWorkspaceChat').mockResolvedValue(ok({ reply: 'ok', model: 'claude-sonnet-4-6', tokens: 3 }))
    await renderReady()
    expect(Array.from(screen.getByLabelText('역할 / 모델').querySelectorAll('option')).map((o) => o.textContent))
      .toEqual(['총괄 (GPT)', '코드 (Claude)', '리서치 (Gemini)'])
    fireEvent.change(screen.getByLabelText('역할 / 모델'), { target: { value: 'code' } })
    typeAndSend('코드 줘')
    await waitFor(() => expect(spy).toHaveBeenCalledWith('code', [{ role: 'user', content: '코드 줘' }], { structure: false }))
  })

  it('context selections are sent as selections only (server builds context)', async () => {
    const spy = vi.spyOn(apiClient, 'postWorkspaceChat').mockResolvedValue(ok({ reply: '분석', model: 'gpt-4o', tokens: 9 }))
    await renderReady()
    fireEvent.change(screen.getByLabelText('프로젝트 파일(읽기)'), { target: { value: 'main.py' } })
    fireEvent.change(screen.getByLabelText('Repository/시트 데이터'), { target: { value: 'sites' } })
    fireEvent.click(screen.getByLabelText(/프로젝트 구조 요약/))
    typeAndSend('구조 분석해줘')
    await waitFor(() => expect(spy).toHaveBeenCalledWith('orchestrator', [{ role: 'user', content: '구조 분석해줘' }],
      { structure: true, file: 'main.py', repo: 'sites' }))
    expect(await screen.findByText('분석')).toBeInTheDocument()
    expect(screen.getByText('gpt-4o · 9 tokens')).toBeInTheDocument()
  })

  it('shows loading, blocks duplicate submit, keeps history for the next turn', async () => {
    let resolve
    const spy = vi.spyOn(apiClient, 'postWorkspaceChat')
      .mockReturnValueOnce(new Promise((r) => { resolve = r }))
      .mockResolvedValueOnce(ok({ reply: '두번째', model: 'gpt-4o', tokens: 1 }))
    await renderReady()
    typeAndSend('첫 질문')
    expect(await screen.findByText('생각 중...')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '전송 중...' })).toBeDisabled()
    fireEvent.submit(screen.getByLabelText('메시지 입력').closest('form'))
    expect(spy).toHaveBeenCalledTimes(1)
    resolve(ok({ reply: '첫 답', model: 'gpt-4o', tokens: 1 }))
    expect(await screen.findByText('첫 답')).toBeInTheDocument()
    typeAndSend('둘째')
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    expect(spy.mock.calls[1][1]).toEqual([{ role: 'user', content: '첫 질문' }, { role: 'assistant', content: '첫 답' }, { role: 'user', content: '둘째' }])
  })

  it('error is the fixed server message (no raw exception) and blocked attachment is reported', async () => {
    vi.spyOn(apiClient, 'postWorkspaceChat')
      .mockResolvedValueOnce(fail('AI_REQUEST_FAILED', 'AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'))
      .mockResolvedValueOnce(fail('FILE_NOT_ALLOWED', '접근이 허용되지 않는 경로입니다.'))
    await renderReady()
    typeAndSend('a')
    expect(await screen.findByText('AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.')).toBeInTheDocument()
    typeAndSend('b')
    expect(await screen.findByText('접근이 허용되지 않는 경로입니다.')).toBeInTheDocument()
  })

  it('reset clears the conversation', async () => {
    vi.spyOn(apiClient, 'postWorkspaceChat').mockResolvedValue(ok({ reply: '답변', model: 'gpt-4o', tokens: 1 }))
    await renderReady()
    typeAndSend('q')
    await screen.findByText('답변')
    fireEvent.click(screen.getByRole('button', { name: '🗑 대화 초기화' }))
    expect(within(screen.getByTestId('workspace-chat')).queryByText('답변')).not.toBeInTheDocument()
  })

  it('sandbox save; existing name asks for overwrite confirmation, then saves with backup', async () => {
    const spy = vi.spyOn(apiClient, 'postWorkspaceSandbox')
      .mockResolvedValueOnce(fail('FILE_CONFLICT', '같은 이름의 파일이 있습니다. 덮어쓰기를 확인하세요.'))
      .mockResolvedValueOnce(ok({ path: 'data/workspace/generated.html', saved: true, overwritten: true, backup: 'data/workspace/backups/generated.html.1.bak' }))
    await renderReady()
    fireEvent.change(screen.getByLabelText('내용'), { target: { value: '<p>x</p>' } })
    fireEvent.click(screen.getByRole('button', { name: '샌드박스 저장' }))
    expect(await screen.findByText('같은 이름의 파일이 있습니다. 덮어쓰기를 확인하세요.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '덮어쓰기 확인 후 저장' }))
    expect(await screen.findByText(/저장: data\/workspace\/generated.html \(기존 파일 백업/)).toBeInTheDocument()
    expect(spy.mock.calls).toEqual([['generated.html', '<p>x</p>', false], ['generated.html', '<p>x</p>', true]])
  })

  it('sandbox save with empty content is rejected locally', async () => {
    const spy = vi.spyOn(apiClient, 'postWorkspaceSandbox')
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: '샌드박스 저장' }))
    expect(await screen.findByText('내용이 비어 있습니다.')).toBeInTheDocument()
    expect(spy).not.toHaveBeenCalled()
  })

  it('project file: preview → approval → write with preview sha', async () => {
    vi.spyOn(apiClient, 'postWorkspaceFilePreview').mockResolvedValue(ok({ path: 'docs/readme.md', exists: true, old: 'readme', old_len: 6, new_len: 3, old_sha256: 'd'.repeat(64) }))
    const write = vi.spyOn(apiClient, 'postWorkspaceFileWrite').mockResolvedValue(ok({ path: 'docs/readme.md', written: true, backed_up: true }))
    await renderReady()
    fireEvent.change(screen.getByLabelText('내용'), { target: { value: 'new' } })
    fireEvent.change(screen.getByLabelText('대상 경로 (예: data/workspace/x.py)'), { target: { value: 'docs/readme.md' } })
    fireEvent.click(screen.getByRole('button', { name: '🔍 변경 미리보기' }))
    expect(await screen.findByText('✏️ 덮어쓰기 — 기존 6자 → 새 3자')).toBeInTheDocument()
    expect(write).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: '✅ 승인 후 저장' }))
    expect(await screen.findByText('저장(백업됨): docs/readme.md')).toBeInTheDocument()
    expect(write).toHaveBeenCalledWith('docs/readme.md', 'new', 'd'.repeat(64))
  })

  it('new project file uses create; editing after preview hides approval', async () => {
    vi.spyOn(apiClient, 'postWorkspaceFilePreview').mockResolvedValue(ok({ path: 'docs/new.md', exists: false, old: '', old_len: 0, new_len: 1, old_sha256: null }))
    const create = vi.spyOn(apiClient, 'postWorkspaceFileCreate').mockResolvedValue(ok({ path: 'docs/new.md', created: true }))
    await renderReady()
    fireEvent.change(screen.getByLabelText('내용'), { target: { value: 'x' } })
    fireEvent.change(screen.getByLabelText('대상 경로 (예: data/workspace/x.py)'), { target: { value: 'docs/new.md' } })
    fireEvent.click(screen.getByRole('button', { name: '🔍 변경 미리보기' }))
    expect(await screen.findByText('🆕 신규 생성 — 기존 0자 → 새 1자')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('내용'), { target: { value: 'xy' } })
    expect(screen.queryByRole('button', { name: '✅ 승인 후 저장' })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('내용'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: '✅ 승인 후 저장' }))
    await waitFor(() => expect(create).toHaveBeenCalledWith('docs/new.md', 'x'))
  })

  it('conflict and not-allowed responses are shown and nothing is reported as saved', async () => {
    vi.spyOn(apiClient, 'postWorkspaceFilePreview')
      .mockResolvedValueOnce(fail('FILE_NOT_ALLOWED', '접근이 허용되지 않는 경로입니다.'))
      .mockResolvedValueOnce(ok({ path: 'docs/readme.md', exists: true, old: 'r', old_len: 1, new_len: 1, old_sha256: 'e'.repeat(64) }))
    vi.spyOn(apiClient, 'postWorkspaceFileWrite').mockResolvedValue(fail('FILE_CONFLICT', '미리보기 이후 파일이 변경되었습니다. 다시 미리보기 하세요.'))
    await renderReady()
    fireEvent.change(screen.getByLabelText('내용'), { target: { value: 'v' } })
    fireEvent.change(screen.getByLabelText('대상 경로 (예: data/workspace/x.py)'), { target: { value: 'data/workspace/_site/index.html' } })
    fireEvent.click(screen.getByRole('button', { name: '🔍 변경 미리보기' }))
    expect(await screen.findByText('접근이 허용되지 않는 경로입니다.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('대상 경로 (예: data/workspace/x.py)'), { target: { value: 'docs/readme.md' } })
    fireEvent.click(screen.getByRole('button', { name: '🔍 변경 미리보기' }))
    fireEvent.click(await screen.findByRole('button', { name: '✅ 승인 후 저장' }))
    expect(await screen.findByText(/실패: 미리보기 이후 파일이 변경되었습니다/)).toBeInTheDocument()
    expect(screen.queryByText(/저장\(/)).not.toBeInTheDocument()
  })

  it('viewer cannot chat or save', async () => {
    apiClient.getCurrentUser.mockResolvedValue(VIEWER)
    const chat = vi.spyOn(apiClient, 'postWorkspaceChat')
    render(<AiWorkspace />)
    await waitFor(() => expect(screen.getByLabelText('역할 / 모델')).toHaveValue('orchestrator'))
    expect(screen.getByLabelText('메시지 입력')).toBeDisabled()
    expect(screen.getByRole('button', { name: '샌드박스 저장' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '🔍 변경 미리보기' })).toBeDisabled()
    expect(chat).not.toHaveBeenCalled()
  })
})
