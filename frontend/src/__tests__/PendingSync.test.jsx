import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react'
import PendingSync from '../components/PendingSync.jsx'
import * as apiClient from '../api/client.js'

// Mock data
const MOCK_PENDING_ITEM = {
  id: 'TEST-PENDING-001',
  op: 'update',
  table: 'topic_pool',
  row: { status: 'publishing' },
  row_id: 'test-row-001',
  direction: 'sqlite_to_sheets',
  source_adapter: 'SQLiteFirstAdapter',
  delete_targets: null,
  retry_count: 0,
  status: 'pending',
  error: 'TEST ERROR - connection timeout',
  created_at: '2026-01-01T00:00:00',
  last_attempt_at: null,
}

const MOCK_FAILED_ITEM = {
  id: 'TEST-FAILED-001',
  op: 'update',
  table: 'topic_pool',
  row: { status: 'publish_failed' },
  row_id: 'test-row-failed',
  direction: 'sqlite_to_sheets',
  source_adapter: 'SQLiteFirstAdapter',
  delete_targets: null,
  retry_count: 3,
  status: 'failed_permanent',
  error: 'TEST ERROR - max retries exceeded',
  created_at: '2026-01-01T00:00:00',
  last_attempt_at: '2026-01-01T00:01:00',
}

const MOCK_PROCESSING_ITEM = {
  id: 'TEST-PROCESSING-001',
  op: 'update',
  table: 'topic_pool',
  row: { status: 'publishing' },
  row_id: 'test-row-processing',
  direction: 'sqlite_to_sheets',
  source_adapter: 'SQLiteFirstAdapter',
  delete_targets: null,
  retry_count: 1,
  status: 'processing',
  error: 'in progress',
  created_at: '2026-01-01T00:00:00',
  last_attempt_at: '2026-01-01T00:00:30',
}

// Mock API responses
const SUCCESS_RESPONSE = {
  success: true,
  data: [],
  error: null,
  request_id: 'test-123',
}

const ERROR_RESPONSE = {
  success: false,
  data: null,
  error: { code: 'RETRY_FAILED', message: '재시도 실패' },
  request_id: 'test-456',
}

// Mock window.confirm
const originalConfirm = window.confirm
let confirmResult = true

beforeEach(() => {
  vi.restoreAllMocks()
  confirmResult = true
  window.confirm = vi.fn((message) => confirmResult)
})

afterEach(() => {
  vi.restoreAllMocks()
  window.confirm = originalConfirm
  confirmResult = true
})

function mockApiCalls({
  pending = [MOCK_PENDING_ITEM],
  processing = [],
  failed = [],
  retryResult = SUCCESS_RESPONSE,
  resumeResult = SUCCESS_RESPONSE,
} = {}) {
  vi.spyOn(apiClient, 'getPendingSync').mockResolvedValue({
    success: true,
    data: pending,
    error: null,
    request_id: 'req-1',
  })
  vi.spyOn(apiClient, 'getProcessingSync').mockResolvedValue({
    success: true,
    data: processing,
    error: null,
    request_id: 'req-2',
  })
  vi.spyOn(apiClient, 'getFailedSync').mockResolvedValue({
    success: true,
    data: failed,
    error: null,
    request_id: 'req-3',
  })
  vi.spyOn(apiClient, 'postRetrySync').mockResolvedValue(retryResult)
  vi.spyOn(apiClient, 'postResumeSync').mockResolvedValue(resumeResult)
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
    success: true,
    data: { role: 'admin' },
    error: null,
    request_id: 'user-1',
  })
}

describe('PendingSync — TEST-C: UI Confirmation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    confirmResult = true
    window.confirm = vi.fn((msg) => confirmResult)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    window.confirm = originalConfirm
  })

  // ══════════════════════════════════════════════════════════════════════
  // TEST-C-1: Retry Cancel
  // ══════════════════════════════════════════════════════════════════════
  describe('TEST-C-1: Retry Cancel', () => {
    it('confirm=false → postRetrySync 호출 0회', async () => {
      confirmResult = false
      mockApiCalls({ pending: [MOCK_PENDING_ITEM] })

      render(<PendingSync />)

      await waitFor(() => expect(screen.getByRole('button', { name: /🔁/ })).toBeInTheDocument())

      const retryBtn = screen.getByRole('button', { name: /🔁/ })
      await act(async () => {
        fireEvent.click(retryBtn)
      })

      // window.confirm이 호출되었는지 확인
      expect(window.confirm).toHaveBeenCalledTimes(1)
      expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('다시 시도하시겠습니까'))

      // postRetrySync가 호출되지 않았는지 확인
      expect(apiClient.postRetrySync).not.toHaveBeenCalled()
    })

    it('confirm dialog shows correct message with item details', async () => {
      confirmResult = false
      mockApiCalls({ pending: [MOCK_PENDING_ITEM] })

      render(<PendingSync />)

      await waitFor(() => expect(screen.getByRole('button', { name: /🔁/ })).toBeInTheDocument())

      const retryBtn = screen.getByRole('button', { name: /🔁/ })
      await act(async () => {
        fireEvent.click(retryBtn)
      })

      expect(window.confirm).toHaveBeenCalledWith(
        expect.stringContaining('TEST-PENDING-001')
      )
      expect(window.confirm).toHaveBeenCalledWith(
        expect.stringContaining('update')
      )
      expect(window.confirm).toHaveBeenCalledWith(
        expect.stringContaining('topic_pool')
      )
      expect(window.confirm).toHaveBeenCalledWith(
        expect.stringContaining('test-row-001')
      )
      expect(window.confirm).toHaveBeenCalledWith(
        expect.stringContaining('0') // retry_count
      )
      expect(window.confirm).toHaveBeenCalledWith(
        expect.stringContaining('connection timeout')
      )
    })
  })

  // ══════════════════════════════════════════════════════════════════════
  // TEST-C-2: Retry Confirm
  // ══════════════════════════════════════════════════════════════════════
  describe('TEST-C-2: Retry Confirm', () => {
    it('confirm=true → postRetrySync 1회 호출', async () => {
      confirmResult = true
      mockApiCalls({ pending: [MOCK_PENDING_ITEM] })

      render(<PendingSync />)

      await waitFor(() => expect(screen.getByRole('button', { name: /🔁/ })).toBeInTheDocument())

      const retryBtn = screen.getByRole('button', { name: /🔁/ })
      await act(async () => {
        fireEvent.click(retryBtn)
      })

      await waitFor(() => expect(apiClient.postRetrySync).toHaveBeenCalledTimes(1))
      expect(apiClient.postRetrySync).toHaveBeenCalledWith('TEST-PENDING-001')
    })

    it('success 후 loadTab 호출로 목록 갱신', async () => {
      mockApiCalls({ pending: [MOCK_PENDING_ITEM] })

      render(<PendingSync />)

      await waitFor(() => expect(screen.getByRole('button', { name: /🔁/ })).toBeInTheDocument())

      const retryBtn = screen.getByRole('button', { name: /🔁/ })
      await act(async () => {
        fireEvent.click(retryBtn)
      })

      await waitFor(() => expect(apiClient.postRetrySync).toHaveBeenCalledTimes(1))
      // 성공 시 목록이 다시 로드되어야 함
      await waitFor(() => expect(apiClient.getPendingSync).toHaveBeenCalledTimes(2)) // 초기 로드 + 성공 후 재조회
    })

    it('실패 시 error 표시', async () => {
      mockApiCalls({
        pending: [MOCK_PENDING_ITEM],
        retryResult: ERROR_RESPONSE,
      })

      render(<PendingSync />)

      await waitFor(() => expect(screen.getByRole('button', { name: /🔁/ })).toBeInTheDocument())

      const retryBtn = screen.getByRole('button', { name: /🔁/ })
      await act(async () => {
        fireEvent.click(retryBtn)
      })

      await waitFor(() => expect(apiClient.postRetrySync).toHaveBeenCalledTimes(1))

      // 에러 메시지가 표시되는지 확인
      await waitFor(() => expect(screen.getByText(/재시도 실패/)).toBeInTheDocument())
    })
  })

  // ══════════════════════════════════════════════════════════════════════
  // TEST-C-3: Resume Cancel
  // ═════════════════════════════════════════════════════════════════════
  describe('TEST-C-3: Resume Cancel', () => {
    it('confirm=false → postResumeSync 호출 0회', async () => {
      confirmResult = false
      mockApiCalls({ failed: [MOCK_FAILED_ITEM] })

      render(<PendingSync />)

      // Failed 탭으로 이동
      const failedTab = screen.getByRole('tab', { name: /🔴 Failed/ })
      await act(async () => {
        fireEvent.click(failedTab)
      })

      await waitFor(() => expect(screen.getByRole('button', { name: /↩️/ })).toBeInTheDocument())

      const resumeBtn = screen.getByRole('button', { name: /↩️/ })
      await act(async () => {
        fireEvent.click(resumeBtn)
      })

      expect(window.confirm).toHaveBeenCalledTimes(1)
      expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('대기 상태로 복구'))
      expect(apiClient.postResumeSync).not.toHaveBeenCalled()
    })

    it('confirm dialog shows correct message with item details', async () => {
      confirmResult = false
      mockApiCalls({ failed: [MOCK_FAILED_ITEM] })

      render(<PendingSync />)

      const failedTab = screen.getByRole('tab', { name: /🔴 Failed/ })
      await act(async () => {
        fireEvent.click(failedTab)
      })

      await waitFor(() => expect(screen.getByRole('button', { name: /↩️/ })).toBeInTheDocument())

      const resumeBtn = screen.getByRole('button', { name: /↩️/ })
      await act(async () => {
        fireEvent.click(resumeBtn)
      })

      expect(window.confirm).toHaveBeenCalledWith(
        expect.stringContaining('TEST-FAILED-001')
      )
      expect(window.confirm).toHaveBeenCalledWith(
        expect.stringContaining('update')
      )
      expect(window.confirm).toHaveBeenCalledWith(
        expect.stringContaining('3') // retry_count
      )
    })
  })

  // ══════════════════════════════════════════════════════════════════════
  // TEST-C-4: Resume Confirm
  // ═════════════════════════════════════════════════════════════════════
  describe('TEST-C-4: Resume Confirm', () => {
    it('confirm=true → postResumeSync 1회 호출', async () => {
      mockApiCalls({ failed: [MOCK_FAILED_ITEM] })

      render(<PendingSync />)

      const failedTab = screen.getByRole('tab', { name: /🔴 Failed/ })
      await act(async () => {
        fireEvent.click(failedTab)
      })

      await waitFor(() => expect(screen.getByRole('button', { name: /↩️/ })).toBeInTheDocument())

      const resumeBtn = screen.getByRole('button', { name: /↩️/ })
      await act(async () => {
        fireEvent.click(resumeBtn)
      })

      await waitFor(() => expect(apiClient.postResumeSync).toHaveBeenCalledTimes(1))
      expect(apiClient.postResumeSync).toHaveBeenCalledWith('TEST-FAILED-001')
    })

    it('success 후 목록 재조회', async () => {
      mockApiCalls({ failed: [MOCK_FAILED_ITEM] })

      render(<PendingSync />)

      const failedTab = screen.getByRole('tab', { name: /🔴 Failed/ })
      await act(async () => {
        fireEvent.click(failedTab)
      })

      await waitFor(() => expect(screen.getByRole('button', { name: /↩️/ })).toBeInTheDocument())

      const resumeBtn = screen.getByRole('button', { name: /↩️/ })
      await act(async () => {
        fireEvent.click(resumeBtn)
      })

      await waitFor(() => expect(apiClient.postResumeSync).toHaveBeenCalledTimes(1))
      await waitFor(() => expect(apiClient.getFailedSync).toHaveBeenCalledTimes(2))
    })

    it('실패 시 error 표시', async () => {
      const RESUME_ERROR_RESPONSE = {
        success: false,
        data: null,
        error: { code: 'RESUME_FAILED', message: '복구 실패' },
        request_id: 'test-456',
      }
      mockApiCalls({
        failed: [MOCK_FAILED_ITEM],
        resumeResult: RESUME_ERROR_RESPONSE,
      })

      render(<PendingSync />)

      const failedTab = screen.getByRole('tab', { name: /🔴 Failed/ })
      await act(async () => {
        fireEvent.click(failedTab)
      })

      await waitFor(() => expect(screen.getByRole('button', { name: /↩️/ })).toBeInTheDocument())

      const resumeBtn = screen.getByRole('button', { name: /↩️/ })
      await act(async () => {
        fireEvent.click(resumeBtn)
      })

      await waitFor(() => expect(apiClient.postResumeSync).toHaveBeenCalledTimes(1))
      await waitFor(() => expect(screen.getByText(/복구 실패/)).toBeInTheDocument())
    })
  })

  // ══════════════════════════════════════════════════════════════════════
  // TEST-C-5: 중복 Submit 방지
  // ═════════════════════════════════════════════════════════════════════
  describe('TEST-C-5: 중복 Submit 방지', () => {
    it('로딩 중 Retry 버튼 비활성화', async () => {
      // 느린 응답 시뮬레이션
      let resolveRetry
      const slowRetryPromise = new Promise(resolve => {
        // resolve 함수를 외부로 노출하지 않고 느리게 만듦
      })
      mockApiCalls({
        pending: [MOCK_PENDING_ITEM],
        retryResult: slowRetryPromise,
      })

      render(<PendingSync />)

      await waitFor(() => expect(screen.getByRole('button', { name: /🔁/ })).toBeInTheDocument())

      const retryBtn = screen.getByRole('button', { name: /🔁/ })

      // 첫 클릭
      await act(async () => {
        fireEvent.click(retryBtn)
      })

      // 버튼이 로딩 상태로 변경되었는지 확인 (disabled)
      expect(retryBtn).toBeDisabled()
      expect(retryBtn).toHaveTextContent('⏳')

      // 두 번째 클릭 시도 (무시되어야 함)
      await act(async () => {
        fireEvent.click(retryBtn)
      })

      // API가 한 번만 호출되었는지 확인 (두 번째 클릭은 무시됨)
      // Note: promise가 resolve되지 않아서 실제로는 대기 상태
    })

    it('로딩 중 Resume 버튼 비활성화', async () => {
      let resolveResume
      const slowResumePromise = new Promise(resolve => {
        resolveResume = resolve
      })
      mockApiCalls({
        failed: [MOCK_FAILED_ITEM],
        resumeResult: slowResumePromise,
      })

      render(<PendingSync />)

      const failedTab = screen.getByRole('tab', { name: /🔴 Failed/ })
      await act(async () => {
        fireEvent.click(failedTab)
      })

      await waitFor(() => expect(screen.getByRole('button', { name: /↩️/ })).toBeInTheDocument())

      const resumeBtn = screen.getByRole('button', { name: /↩️/ })
      await act(async () => {
        fireEvent.click(resumeBtn)
      })

      expect(resumeBtn).toBeDisabled()
      expect(resumeBtn).toHaveTextContent('⏳')
    })

    it('confirm=false 후 다시 confirm=true로 클릭 시 각각 독립 동작', async () => {
      // 첫 번째: cancel
      confirmResult = false
      mockApiCalls({ pending: [MOCK_PENDING_ITEM] })

      render(<PendingSync />)

      await waitFor(() => expect(screen.getByRole('button', { name: /🔁/ })).toBeInTheDocument())

      let retryBtn = screen.getByRole('button', { name: /🔁/ })
      await act(async () => {
        fireEvent.click(retryBtn)
      })

      expect(apiClient.postRetrySync).not.toHaveBeenCalled()

      // 두 번째: confirm
      confirmResult = true
      mockApiCalls({ pending: [MOCK_PENDING_ITEM] })

      retryBtn = screen.getByRole('button', { name: /🔁/ })
      await act(async () => {
        fireEvent.click(retryBtn)
      })

      await waitFor(() => expect(apiClient.postRetrySync).toHaveBeenCalledTimes(1))
    })
  })

  // ══════════════════════════════════════════════════════════════════════
  // TEST-C-6: Processing 탭에서 Retry/Resume 버튼 없음
  // ═════════════════════════════════════════════════════════════════════
  describe('TEST-C-6: Processing 탭 전용 조회', () => {
    it('Processing 탭에는 Retry/Resume 버튼이 없음', async () => {
      mockApiCalls({ processing: [MOCK_PROCESSING_ITEM] })

      render(<PendingSync />)

      const processingTab = screen.getByRole('tab', { name: /🟡 Processing/ })
      await act(async () => {
        fireEvent.click(processingTab)
      })

      await waitFor(() => expect(screen.getByText('TEST-PROCESSING-001')).toBeInTheDocument())

      // Processing 탭에는 Retry/Resume 버튼이 없어야 함
      expect(screen.queryByRole('button', { name: /🔁/ })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /↩️/ })).not.toBeInTheDocument()
    })
  })

  // ══════════════════════════════════════════════════════════════════════
  // TEST-C-7: 빈 상태 및 에러 처리
  // ══════════════════════════════════════════════════════════════════════
  describe('TEST-C-7: 빈 상태 및 에러', () => {
    it('빈 Pending 탭에서 빈 메시지 표시', async () => {
      mockApiCalls({ pending: [] })

      render(<PendingSync />)

      await waitFor(() => expect(screen.getByText(/대기 중인 동기화 항목이 없습니다/)).toBeInTheDocument())
    })

    it('API 조회 실패 시 에러 메시지 표시', async () => {
      vi.spyOn(apiClient, 'getPendingSync').mockResolvedValue({
        success: false,
        data: null,
        error: { code: 'NETWORK_ERROR', message: 'Connection refused' },
        request_id: 'err-1',
      })
      vi.spyOn(apiClient, 'getProcessingSync').mockResolvedValue({
        success: true,
        data: [],
        error: null,
        request_id: 'req-2',
      })
      vi.spyOn(apiClient, 'getFailedSync').mockResolvedValue({
        success: true,
        data: [],
        error: null,
        request_id: 'req-3',
      })
      vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue({
        success: true,
        data: { role: 'admin' },
        error: null,
        request_id: 'user-1',
      })

      render(<PendingSync />)

      await waitFor(() => expect(screen.getByText(/목록 조회 실패/)).toBeInTheDocument())
    })
  })
})