import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import AiAssistant from '../pages/AiAssistant.jsx'
import * as apiClient from '../api/client.js'

// AI-ASSISTANT-02 — AI Assistant 화면. 모든 client 호출은 mock(실제 AI/파일 쓰기 없음).
const ADMIN = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u1' }
const VIEWER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u2' }
const ok = (data) => ({ success: true, data, error: null, request_id: 'r' })
const fail = (code, message) => ({ success: false, data: null, error: { code, message }, request_id: 'r' })
const MODELS = ok({
  models: [
    { label: 'GPT (CEO/전략)', provider: 'openai', model: 'gpt-4o' },
    { label: 'Claude (편집장/코드)', provider: 'claude', model: 'claude-sonnet-4-6' },
    { label: 'Gemini (실무팀/분석)', provider: 'gemini', model: 'gemini-2.5-flash' },
  ],
  default: 'GPT (CEO/전략)',
  quick_questions: ['현재 프로젝트 분석해', 'App Factory 분석해', '문제점 찾아', '개선안 제안해'],
})

beforeEach(() => {
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN)
  vi.spyOn(apiClient, 'getAssistantModels').mockResolvedValue(MODELS)
  vi.spyOn(apiClient, 'getAssistantMemory').mockResolvedValue(ok({ rules: [{ text: '규칙1' }], todo: [], dev_log: [] }))
  vi.spyOn(apiClient, 'getAssistantTasks').mockResolvedValue(ok({ tasks: [{ id: 't1', title: '점검', status: 'Pending' }], statuses: ['Pending', 'Running', 'Completed', 'Failed'] }))
})

afterEach(() => {
  vi.restoreAllMocks()
})

async function renderReady() {
  render(<AiAssistant />)
  await waitFor(() => expect(screen.getByLabelText('모델')).toHaveValue('GPT (CEO/전략)'))
  await waitFor(() => expect(screen.getByRole('button', { name: '문제점 찾아' })).toBeEnabled())
}

describe('AiAssistant page', () => {
  it('renders title, 3 models, 4 quick questions and sections', async () => {
    await renderReady()
    expect(screen.getByText('🤖 AI Assistant — 운영비서')).toBeInTheDocument()
    expect(Array.from(screen.getByLabelText('모델').querySelectorAll('option')).map((o) => o.value)).toHaveLength(3)
    for (const q of ['현재 프로젝트 분석해', 'App Factory 분석해', '문제점 찾아', '개선안 제안해']) {
      expect(screen.getByRole('button', { name: q })).toBeInTheDocument()
    }
    expect(screen.getByText(/📝 파일 수정\/생성/)).toBeInTheDocument()
    expect(screen.getByText(/📂 워크스페이스 탐색\/읽기/)).toBeInTheDocument()
  })

  it('model selection is sent with the chat', async () => {
    const spy = vi.spyOn(apiClient, 'postAssistantChat').mockResolvedValue(ok({ reply: '네', model: 'claude-sonnet-4-6', tokens: 5 }))
    await renderReady()
    fireEvent.change(screen.getByLabelText('모델'), { target: { value: 'Claude (편집장/코드)' } })
    fireEvent.change(screen.getByLabelText('명령/질문'), { target: { value: '안녕' } })
    fireEvent.click(screen.getByRole('button', { name: '전송' }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('Claude (편집장/코드)', [{ role: 'user', content: '안녕' }]))
  })

  it('quick question sends immediately and shows the reply with model/tokens', async () => {
    const spy = vi.spyOn(apiClient, 'postAssistantChat').mockResolvedValue(ok({ reply: '문제 3건', model: 'gpt-4o', tokens: 42 }))
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: '문제점 찾아' }))
    expect(await screen.findByText('문제 3건')).toBeInTheDocument()
    expect(screen.getByText('gpt-4o · 42 tokens')).toBeInTheDocument()
    expect(spy).toHaveBeenCalledWith('GPT (CEO/전략)', [{ role: 'user', content: '문제점 찾아' }])
  })

  it('shows loading, blocks duplicate send, and sends full history on the next turn', async () => {
    let resolve
    const spy = vi.spyOn(apiClient, 'postAssistantChat')
      .mockReturnValueOnce(new Promise((r) => { resolve = r }))
      .mockResolvedValueOnce(ok({ reply: '두번째', model: 'gpt-4o', tokens: 1 }))
    await renderReady()
    fireEvent.change(screen.getByLabelText('명령/질문'), { target: { value: '첫 질문' } })
    fireEvent.click(screen.getByRole('button', { name: '전송' }))
    expect(await screen.findByText('분석 중...')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '전송 중...' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '문제점 찾아' }))
    expect(spy).toHaveBeenCalledTimes(1)
    resolve(ok({ reply: '첫 답변', model: 'gpt-4o', tokens: 1 }))
    expect(await screen.findByText('첫 답변')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('명령/질문'), { target: { value: '둘째 질문' } })
    fireEvent.click(screen.getByRole('button', { name: '전송' }))
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2))
    expect(spy.mock.calls[1][1]).toEqual([
      { role: 'user', content: '첫 질문' }, { role: 'assistant', content: '첫 답변' }, { role: 'user', content: '둘째 질문' },
    ])
  })

  it('error is shown as the fixed server message in the conversation (no raw exception)', async () => {
    vi.spyOn(apiClient, 'postAssistantChat').mockResolvedValue(fail('AI_REQUEST_FAILED', 'AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'))
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: '개선안 제안해' }))
    expect(await screen.findByText('AI 요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.')).toBeInTheDocument()
  })

  it('reset clears the conversation', async () => {
    vi.spyOn(apiClient, 'postAssistantChat').mockResolvedValue(ok({ reply: '답', model: 'gpt-4o', tokens: 1 }))
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: '문제점 찾아' }))
    await screen.findByText('답')
    fireEvent.click(screen.getByRole('button', { name: '🗑 대화 초기화' }))
    expect(within(screen.getByTestId('assistant-chat')).queryByText('답')).not.toBeInTheDocument()
  })

  it('file preview → approval writes with the preview sha (existing file)', async () => {
    vi.spyOn(apiClient, 'postAssistantFilePreview').mockResolvedValue(ok({ path: 'data/workspace/example.txt', exists: true, old: 'hello', old_len: 5, new_len: 3, old_sha256: 'a'.repeat(64) }))
    const write = vi.spyOn(apiClient, 'postAssistantFileWrite').mockResolvedValue(ok({ path: 'data/workspace/example.txt', written: true, backed_up: true }))
    const create = vi.spyOn(apiClient, 'postAssistantFileCreate')
    await renderReady()
    fireEvent.change(screen.getByLabelText('새 내용 (AI 답변에서 복사 가능)'), { target: { value: 'new' } })
    fireEvent.click(screen.getByRole('button', { name: '🔍 변경 미리보기' }))
    expect(await screen.findByText('✏️ 덮어쓰기 — 기존 5자 → 새 3자')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '✅ 승인 후 저장' }))
    expect(await screen.findByText('저장 완료: data/workspace/example.txt')).toBeInTheDocument()
    expect(write).toHaveBeenCalledWith('data/workspace/example.txt', 'new', 'a'.repeat(64))
    expect(create).not.toHaveBeenCalled()
  })

  it('new file preview → approval uses create; editing content after preview invalidates approval', async () => {
    vi.spyOn(apiClient, 'postAssistantFilePreview').mockResolvedValue(ok({ path: 'data/workspace/n.txt', exists: false, old: '', old_len: 0, new_len: 1, old_sha256: null }))
    const create = vi.spyOn(apiClient, 'postAssistantFileCreate').mockResolvedValue(ok({ path: 'data/workspace/n.txt', created: true }))
    await renderReady()
    fireEvent.change(screen.getByLabelText('대상 경로'), { target: { value: 'data/workspace/n.txt' } })
    fireEvent.change(screen.getByLabelText('새 내용 (AI 답변에서 복사 가능)'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: '🔍 변경 미리보기' }))
    expect(await screen.findByText('🆕 신규 생성 — 기존 0자 → 새 1자')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('새 내용 (AI 답변에서 복사 가능)'), { target: { value: 'xy' } })
    expect(screen.queryByRole('button', { name: '✅ 승인 후 저장' })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('새 내용 (AI 답변에서 복사 가능)'), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: '✅ 승인 후 저장' }))
    await waitFor(() => expect(create).toHaveBeenCalledWith('data/workspace/n.txt', 'x'))
  })

  it('server rejection of a blocked path or stale preview is shown and nothing is reported as saved', async () => {
    vi.spyOn(apiClient, 'postAssistantFilePreview')
      .mockResolvedValueOnce(fail('PATH_NOT_ALLOWED', '접근이 제한된 경로입니다.'))
      .mockResolvedValueOnce(ok({ path: 'data/workspace/example.txt', exists: true, old: 'h', old_len: 1, new_len: 1, old_sha256: 'b'.repeat(64) }))
    vi.spyOn(apiClient, 'postAssistantFileWrite').mockResolvedValue(fail('VALIDATION_ERROR', '미리보기 이후 파일이 변경되었습니다. 다시 미리보기 하세요.'))
    await renderReady()
    fireEvent.change(screen.getByLabelText('대상 경로'), { target: { value: 'config/secrets.yaml' } })
    fireEvent.click(screen.getByRole('button', { name: '🔍 변경 미리보기' }))
    expect(await screen.findByText('접근이 제한된 경로입니다.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('대상 경로'), { target: { value: 'data/workspace/example.txt' } })
    fireEvent.click(screen.getByRole('button', { name: '🔍 변경 미리보기' }))
    fireEvent.click(await screen.findByRole('button', { name: '✅ 승인 후 저장' }))
    expect(await screen.findByText(/저장 실패: 미리보기 이후 파일이 변경되었습니다/)).toBeInTheDocument()
    expect(screen.queryByText(/저장 완료/)).not.toBeInTheDocument()
  })

  it('cancel discards the preview', async () => {
    vi.spyOn(apiClient, 'postAssistantFilePreview').mockResolvedValue(ok({ path: 'data/workspace/example.txt', exists: true, old: 'h', old_len: 1, new_len: 0, old_sha256: 'c'.repeat(64) }))
    const write = vi.spyOn(apiClient, 'postAssistantFileWrite')
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: '🔍 변경 미리보기' }))
    fireEvent.click(await screen.findByRole('button', { name: '취소' }))
    expect(screen.queryByTestId('assistant-diff')).not.toBeInTheDocument()
    expect(write).not.toHaveBeenCalled()
  })

  it('directory list and file read', async () => {
    vi.spyOn(apiClient, 'postAssistantFilesList').mockResolvedValue(ok({ path: '.', items: [{ name: 'modules', type: 'dir', path: 'modules' }, { name: 'README.md', type: 'file', path: 'README.md' }] }))
    vi.spyOn(apiClient, 'postAssistantFileRead').mockResolvedValue(ok({ path: 'modules/app_factory.py', content: 'print(1)', truncated: false }))
    await renderReady()
    fireEvent.click(screen.getByRole('button', { name: '목록' }))
    expect(await screen.findByText('📁 modules')).toBeInTheDocument()
    expect(screen.getByText('📄 README.md')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '읽기' }))
    expect(await screen.findByTestId('assistant-read')).toHaveTextContent('print(1)')
  })

  it('memory shows existing items and adds a new one of the selected kind', async () => {
    const spy = vi.spyOn(apiClient, 'postAssistantMemory').mockResolvedValue(ok({ rules: [{ text: '규칙1' }], todo: [{ text: '할일' }], dev_log: [] }))
    await renderReady()
    expect(await screen.findByTestId('memory-rules')).toHaveTextContent('규칙1')
    fireEvent.change(screen.getByLabelText('종류'), { target: { value: 'todo' } })
    fireEvent.change(screen.getByLabelText('추가 내용'), { target: { value: '할일' } })
    fireEvent.click(screen.getByRole('button', { name: '메모리 추가' }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('todo', '할일'))
    expect(await screen.findByTestId('memory-todo')).toHaveTextContent('할일')
  })

  it('task add and status change', async () => {
    const add = vi.spyOn(apiClient, 'postAssistantTask').mockResolvedValue(ok({ task: { id: 't2', title: '배포 확인', status: 'Pending' }, tasks: [{ id: 't1', title: '점검', status: 'Pending' }, { id: 't2', title: '배포 확인', status: 'Pending' }], statuses: [] }))
    const patch = vi.spyOn(apiClient, 'patchAssistantTask').mockResolvedValue(ok({ tasks: [{ id: 't1', title: '점검', status: 'Completed' }], statuses: [] }))
    await renderReady()
    fireEvent.change(screen.getByLabelText('새 태스크'), { target: { value: '배포 확인' } })
    fireEvent.click(screen.getByRole('button', { name: '태스크 추가' }))
    await waitFor(() => expect(add).toHaveBeenCalledWith('배포 확인'))
    expect(await screen.findByText('배포 확인')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('상태 점검'), { target: { value: 'Completed' } })
    await waitFor(() => expect(patch).toHaveBeenCalledWith('t1', 'Completed'))
  })

  it('viewer cannot chat or use file actions', async () => {
    apiClient.getCurrentUser.mockResolvedValue(VIEWER)
    const chat = vi.spyOn(apiClient, 'postAssistantChat')
    render(<AiAssistant />)
    await waitFor(() => expect(screen.getByLabelText('모델')).toHaveValue('GPT (CEO/전략)'))
    expect(screen.getByRole('button', { name: '문제점 찾아' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '🔍 변경 미리보기' })).toBeDisabled()
    expect(chat).not.toHaveBeenCalled()
  })
})
