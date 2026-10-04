import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import Settings from '../pages/Settings.jsx'
import * as apiClient from '../api/client.js'

// STEP P2-14: Settings Image-gen AI/Google 연동 React/FastAPI 이관 검증. 실제
// getImageGoogleSettings/patchImageGoogleSettings는 이 파일의 어떤
// 테스트에서도 실호출하지 않는다 — 항상 mock.

const SETTINGS_OK = {
  success: true,
  data: {
    BLOG_SCHEDULE: { enabled: true, mode: 'draft', publish_slots: [{ start: '06:00', end: '06:30' }], weekday_only: false },
    CALC_WEBAPP_SCHEDULE: { enabled: false, mode: 'qa_only', targets: [] },
    CONTENT_SYNC: { enabled: true, run_at: '03:00', full_scan_weekday: 0, recent_days: 30, poll_seconds: 60 },
    PUBLISH_SCHEDULE: { enabled: false, failure_mode: 'retry_in_slot', weekday: [], weekend: [] },
  },
  error: null,
  request_id: 's1',
}
const STATUS = (name, enabled, running) => ({
  success: true, data: { name, enabled, running, thread_alive: running }, error: null, request_id: `st-${name}`,
})
const GENERAL_OK = {
  success: true,
  data: {
    WORDPRESS_URL: '', WORDPRESS_USERNAME: '', TELEGRAM_CHAT_ID: { configured: false }, DAILY_AI_BUDGET: 5, MONTHLY_AI_BUDGET: 100,
    AI_ROLES: {}, OPENAI_API_KEY: { configured: false }, CLAUDE_API_KEY: { configured: false },
    GEMINI_API_KEY: { configured: false }, TELEGRAM_BOT_TOKEN: { configured: false },
    WORDPRESS_APP_PASSWORD: { configured: false },
  },
  error: null, request_id: 'g1',
}
const IMAGE_GOOGLE_OK = {
  success: true,
  data: {
    IMAGE_PROVIDER: 'gemini',
    MODEL_IMAGE: 'imagen-3.0-generate-002',
    IMAGE_SIZE: '1024x1024',
    IMAGE_QUALITY: 'hd',
    GOOGLE_SHEET_ID: 'existing-sheet-id',
    GOOGLE_DRIVE_ROOT_ID: 'existing-drive-id',
    GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID: 'existing-placeholder-id',
  },
  error: null,
  request_id: 'ig1',
}
const VIEWER_USER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u1' }
const ADMIN_USER = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u2' }

function mockAll(userResponse = VIEWER_USER, imageGoogle = IMAGE_GOOGLE_OK) {
  vi.spyOn(apiClient, 'getSettings').mockResolvedValue(SETTINGS_OK)
  vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(STATUS('blog', true, false))
  vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue(STATUS('calculator', false, false))
  vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue(STATUS('content_sync', true, false))
  vi.spyOn(apiClient, 'getGeneralSettings').mockResolvedValue(GENERAL_OK)
  vi.spyOn(apiClient, 'getImageGoogleSettings').mockResolvedValue(imageGoogle)
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(userResponse)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Image-Google Settings panel (STEP P2-14)', () => {
  it('renders the current values for all 7 fields', async () => {
    mockAll()
    render(<Settings />)
    await waitFor(() => expect(screen.getByText('🎨 Image-gen AI / 📊 Google 연동')).toBeInTheDocument())
    expect(screen.getByLabelText('Image Provider')).toHaveValue('gemini')
    expect(screen.getByLabelText('Image Model')).toHaveValue('imagen-3.0-generate-002')
    expect(screen.getByLabelText('Image Size')).toHaveValue('1024x1024')
    expect(screen.getByLabelText('Image Quality')).toHaveValue('hd')
    expect(screen.getByLabelText('Google Sheet ID')).toHaveValue('existing-sheet-id')
    expect(screen.getByLabelText('Google Drive Root ID')).toHaveValue('existing-drive-id')
    expect(screen.getByLabelText('Google Drive Placeholder Folder ID')).toHaveValue('existing-placeholder-id')
  })

  it('disables all inputs and the save button for a non-admin viewer', async () => {
    mockAll(VIEWER_USER)
    render(<Settings />)
    await waitFor(() => expect(screen.getByText('🎨 Image-gen AI / 📊 Google 연동')).toBeInTheDocument())
    expect(screen.getByLabelText('Image Provider')).toBeDisabled()
    expect(screen.getByLabelText('Google Sheet ID')).toBeDisabled()
    const saveButtons = screen.getAllByRole('button', { name: /저장/ })
    const imgSaveBtn = saveButtons.find((b) => b.textContent.includes('💾 저장'))
    expect(imgSaveBtn).toBeDisabled()
  })

  it('enables inputs and the save button for an admin', async () => {
    mockAll(ADMIN_USER)
    render(<Settings />)
    await waitFor(() => expect(screen.getByText('🎨 Image-gen AI / 📊 Google 연동')).toBeInTheDocument())
    expect(screen.getByLabelText('Image Provider')).toBeEnabled()
    const saveButtons = screen.getAllByRole('button', { name: /저장/ })
    const imgSaveBtn = saveButtons.find((b) => b.textContent.includes('💾 저장'))
    expect(imgSaveBtn).toBeEnabled()
  })

  it('submits the form and calls patchImageGoogleSettings with the current field values', async () => {
    mockAll(ADMIN_USER)
    const spy = vi.spyOn(apiClient, 'patchImageGoogleSettings').mockResolvedValue({
      success: true, data: { ...IMAGE_GOOGLE_OK.data, IMAGE_PROVIDER: 'openai' }, error: null, request_id: 'p1',
    })
    render(<Settings />)
    await waitFor(() => expect(screen.getByLabelText('Image Provider')).toHaveValue('gemini'))
    fireEvent.change(screen.getByLabelText('Image Provider'), { target: { value: 'openai' } })
    const saveButtons = screen.getAllByRole('button', { name: /저장/ })
    fireEvent.click(saveButtons.find((b) => b.textContent.includes('💾 저장')))
    await waitFor(() => expect(spy).toHaveBeenCalledWith(expect.objectContaining({
      image_provider: 'openai',
      google_sheet_id: 'existing-sheet-id',
    })))
  })

  it('shows a success message after a successful save', async () => {
    mockAll(ADMIN_USER)
    vi.spyOn(apiClient, 'patchImageGoogleSettings').mockResolvedValue({
      success: true, data: IMAGE_GOOGLE_OK.data, error: null, request_id: 'p2',
    })
    render(<Settings />)
    await waitFor(() => expect(screen.getByLabelText('Image Provider')).toBeInTheDocument())
    const saveButtons = screen.getAllByRole('button', { name: /저장/ })
    fireEvent.click(saveButtons.find((b) => b.textContent.includes('💾 저장')))
    await waitFor(() => expect(screen.getByText('저장되었습니다.')).toBeInTheDocument())
  })

  it('shows an error message when the save fails', async () => {
    mockAll(ADMIN_USER)
    vi.spyOn(apiClient, 'patchImageGoogleSettings').mockResolvedValue({
      success: false, data: null, error: { code: 'VALIDATION_ERROR', message: '저장 실패했습니다' }, request_id: null,
    })
    render(<Settings />)
    await waitFor(() => expect(screen.getByLabelText('Image Provider')).toBeInTheDocument())
    const saveButtons = screen.getAllByRole('button', { name: /저장/ })
    fireEvent.click(saveButtons.find((b) => b.textContent.includes('💾 저장')))
    await waitFor(() => expect(screen.getByText(/저장 실패했습니다/)).toBeInTheDocument())
  })

  it('shows an error state when the API fails to load', async () => {
    mockAll(VIEWER_USER, { success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null })
    render(<Settings />)
    await waitFor(() => expect(screen.getAllByText('⚠ API 연결 실패').length).toBeGreaterThan(0))
  })

  it('offers the exact provider/size/quality options from the original Streamlit selectboxes', async () => {
    mockAll(ADMIN_USER)
    render(<Settings />)
    await waitFor(() => expect(screen.getByLabelText('Image Provider')).toBeInTheDocument())
    const providerOptions = Array.from(screen.getByLabelText('Image Provider').querySelectorAll('option')).map((o) => o.value)
    expect(providerOptions).toEqual(['free_pollinations', 'gemini', 'openai'])
    const sizeOptions = Array.from(screen.getByLabelText('Image Size').querySelectorAll('option')).map((o) => o.value)
    expect(sizeOptions).toEqual(['auto', '1024x1024', '1792x1024'])
    const qualityOptions = Array.from(screen.getByLabelText('Image Quality').querySelectorAll('option')).map((o) => o.value)
    expect(qualityOptions).toEqual(['standard', 'hd'])
  })
})
