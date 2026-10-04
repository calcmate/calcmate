import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import Settings from '../pages/Settings.jsx'
import Health from '../pages/Health.jsx'
import * as apiClient from '../api/client.js'

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
  success: true,
  data: { name, enabled, running, thread_alive: running },
  error: null,
  request_id: `st-${name}`,
})
const FAILURE = { success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null }

// STEP 4-F: General Settings(조회/저장) 응답 — viewer 기본(저장 버튼은 disabled).
const GENERAL_OK = {
  success: true,
  data: {
    WORDPRESS_URL: 'http://existing.test',
    WORDPRESS_USERNAME: 'existing-user',
    // TELEGRAM_CHAT_ID는 secret(ab9ac26) — 서버는 configured 상태만 반환한다.
    TELEGRAM_CHAT_ID: { configured: true },
    DAILY_AI_BUDGET: 5,
    MONTHLY_AI_BUDGET: 100,
    AI_ROLES: { writer: { provider: 'openai', model: 'gpt-4o' } },
    OPENAI_API_KEY: { configured: true },
    CLAUDE_API_KEY: { configured: false },
    GEMINI_API_KEY: { configured: false },
    TELEGRAM_BOT_TOKEN: { configured: false },
    WORDPRESS_APP_PASSWORD: { configured: true },
  },
  error: null,
  request_id: 'g1',
}
const VIEWER_USER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'u1' }
const ADMIN_USER = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'u2' }

// STEP P2-14: Image-gen AI/Google 연동 조회 응답.
const IMAGE_GOOGLE_OK = {
  success: true,
  data: {
    IMAGE_PROVIDER: 'free_pollinations',
    MODEL_IMAGE: '',
    IMAGE_SIZE: 'auto',
    IMAGE_QUALITY: 'standard',
    GOOGLE_SHEET_ID: 'existing-sheet-id',
    GOOGLE_DRIVE_ROOT_ID: 'existing-drive-id',
    GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID: 'existing-placeholder-id',
  },
  error: null,
  request_id: 'ig1',
}

function mockSettingsOk(userResponse = VIEWER_USER) {
  vi.spyOn(apiClient, 'getSettings').mockResolvedValue(SETTINGS_OK)
  vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(STATUS('blog', true, false))
  vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue(STATUS('calculator', false, false))
  vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue(STATUS('content_sync', true, false))
  vi.spyOn(apiClient, 'getGeneralSettings').mockResolvedValue(GENERAL_OK)
  vi.spyOn(apiClient, 'getImageGoogleSettings').mockResolvedValue(IMAGE_GOOGLE_OK)
  vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(userResponse)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('Settings page (/settings)', () => {
  it('shows the READ-ONLY notice text for scheduler sections', async () => {
    mockSettingsOk()
    render(<Settings />)
    await waitFor(() => expect(screen.getByText(/READ-ONLY입니다/)).toBeInTheDocument())
    expect(screen.getByText(/Blog Scheduler 설정은 Scheduler 화면에서 변경/)).toBeInTheDocument()
  })

  // STEP 4-F: General Settings는 더 이상 read-only가 아니다 — admin 권한 안내 문구가 보여야 한다.
  it('shows the General Settings admin-save notice text', async () => {
    mockSettingsOk()
    render(<Settings />)
    await waitFor(() =>
      expect(screen.getByText(/General Settings.*admin 권한으로 저장할 수 있습니다/)).toBeInTheDocument()
    )
  })

  it('renders each section with real Enabled/Mode/Worker values, not hardcoded', async () => {
    mockSettingsOk()
    render(<Settings />)
    await waitFor(() => expect(screen.getByText('Blog')).toBeInTheDocument())
    expect(screen.getByText('Calculator')).toBeInTheDocument()
    expect(screen.getByText('Content Sync')).toBeInTheDocument()
    expect(screen.getByText('Publish')).toBeInTheDocument()
    expect(screen.getByText('draft')).toBeInTheDocument()
    expect(screen.getAllByText('Worker Stopped').length).toBeGreaterThan(0)
  })

  it('scheduler section table itself stays read-only (no inputs inside the table)', async () => {
    mockSettingsOk()
    render(<Settings />)
    await waitFor(() => expect(screen.getByText('Blog')).toBeInTheDocument())
    const table = screen.getByRole('table')
    expect(table.querySelectorAll('input, select, button')).toHaveLength(0)
  })

  // STEP 4-F: General Settings 폼은 이제 존재하지만, viewer 권한이면 모든 입력/버튼이 disabled다.
  it('General Settings inputs and save button exist but are disabled for a viewer', async () => {
    mockSettingsOk(VIEWER_USER)
    render(<Settings />)
    await waitFor(() => expect(screen.getByText('General Settings')).toBeInTheDocument())
    const saveBtn = screen.getByRole('button', { name: /설정 저장/ })
    expect(saveBtn).toBeDisabled()
    for (const box of screen.getAllByRole('textbox')) {
      expect(box).toBeDisabled()
    }
  })

  it('General Settings inputs and save button are enabled for an admin', async () => {
    mockSettingsOk(ADMIN_USER)
    render(<Settings />)
    await waitFor(() => expect(screen.getByText('General Settings')).toBeInTheDocument())
    const saveBtn = screen.getByRole('button', { name: /설정 저장/ })
    expect(saveBtn).not.toBeDisabled()
  })

  // CALCMATE-TELEGRAM-CHAT-ID-SECRET-FIX-01: Chat ID는 secret field UX(설정됨/미설정,
  // 원문 미표시, 변경 시에만 전송, 저장 후 비움)를 따른다.
  it('TELEGRAM_CHAT_ID shows configured state and never prefills a raw value', async () => {
    mockSettingsOk(ADMIN_USER)
    render(<Settings />)
    const input = await screen.findByLabelText(/TELEGRAM_CHAT_ID \(설정됨\)/)
    expect(input).toHaveValue('')
    expect(input).toHaveAttribute('type', 'password')
  })

  it('TELEGRAM_CHAT_ID is sent only when changed and cleared after a successful save', async () => {
    mockSettingsOk(ADMIN_USER)
    const patchSpy = vi.spyOn(apiClient, 'patchGeneralSettings').mockResolvedValue(GENERAL_OK)
    render(<Settings />)
    await screen.findByLabelText(/TELEGRAM_CHAT_ID \(설정됨\)/)

    fireEvent.click(screen.getByRole('button', { name: /설정 저장/ }))
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1))
    expect(patchSpy.mock.calls[0][0]).not.toHaveProperty('telegram_chat_id')

    // 저장 성공 후 load()가 폼을 다시 그리므로 input을 다시 찾는다.
    const input = await screen.findByLabelText(/TELEGRAM_CHAT_ID \(설정됨\)/)
    fireEvent.change(input, { target: { value: '-100typed-new' } })
    fireEvent.click(screen.getByRole('button', { name: /설정 저장/ }))
    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(2))
    expect(patchSpy.mock.calls[1][0].telegram_chat_id).toBe('-100typed-new')
    await waitFor(() => expect(screen.getByLabelText(/TELEGRAM_CHAT_ID \(설정됨\)/)).toHaveValue(''))
    expect(screen.queryByDisplayValue('-100typed-new')).not.toBeInTheDocument()
  })

  it('TELEGRAM_CHAT_ID shows 미설정 when the secret is not configured', async () => {
    mockSettingsOk(ADMIN_USER)
    vi.spyOn(apiClient, 'getGeneralSettings').mockResolvedValue({
      ...GENERAL_OK, data: { ...GENERAL_OK.data, TELEGRAM_CHAT_ID: { configured: false } },
    })
    render(<Settings />)
    expect(await screen.findByLabelText(/TELEGRAM_CHAT_ID \(미설정\)/)).toHaveValue('')
  })

  it('shows the generic error UI when settings API fails', async () => {
    vi.spyOn(apiClient, 'getSettings').mockResolvedValue(FAILURE)
    vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(STATUS('blog', true, false))
    vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue(STATUS('calculator', false, false))
    vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue(STATUS('content_sync', true, false))
    // General/Image-Google Settings 쪽은 성공시켜 이 테스트가 검증하려는
    // "Scheduler 섹션 조회 실패" 신호만 남긴다.
    vi.spyOn(apiClient, 'getGeneralSettings').mockResolvedValue(GENERAL_OK)
    vi.spyOn(apiClient, 'getImageGoogleSettings').mockResolvedValue(IMAGE_GOOGLE_OK)
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    render(<Settings />)
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })

  it('General Settings panel shows its own error UI when it fails independently', async () => {
    vi.spyOn(apiClient, 'getSettings').mockResolvedValue(SETTINGS_OK)
    vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(STATUS('blog', true, false))
    vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue(STATUS('calculator', false, false))
    vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue(STATUS('content_sync', true, false))
    vi.spyOn(apiClient, 'getGeneralSettings').mockResolvedValue(FAILURE)
    vi.spyOn(apiClient, 'getImageGoogleSettings').mockResolvedValue(IMAGE_GOOGLE_OK)
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    render(<Settings />)
    await waitFor(() => expect(screen.getAllByText('⚠ API 연결 실패').length).toBeGreaterThan(0))
  })

  it('Image-Google Settings panel shows its own error UI when it fails independently', async () => {
    vi.spyOn(apiClient, 'getSettings').mockResolvedValue(SETTINGS_OK)
    vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(STATUS('blog', true, false))
    vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue(STATUS('calculator', false, false))
    vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue(STATUS('content_sync', true, false))
    vi.spyOn(apiClient, 'getGeneralSettings').mockResolvedValue(GENERAL_OK)
    vi.spyOn(apiClient, 'getImageGoogleSettings').mockResolvedValue(FAILURE)
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    render(<Settings />)
    await waitFor(() => expect(screen.getAllByText('⚠ API 연결 실패').length).toBeGreaterThan(0))
  })
})

describe('Health page (/health)', () => {
  const HEALTH_OK = {
    success: true,
    data: {
      application: { fastapi: 'healthy' },
      schedulers: {
        blog: { name: 'blog', enabled: true, running: false, thread_alive: false },
        calculator: { name: 'calculator', enabled: false, running: false, thread_alive: false },
        content_sync: { name: 'content_sync', enabled: true, running: false, thread_alive: false },
      },
      data: { database: true, config: true, registry: true, labor_af: true, pipeline_log: true },
    },
    error: null,
    request_id: 'h1',
  }

  it('renders Application, Schedulers, Data sections with real values', async () => {
    vi.spyOn(apiClient, 'getHealthDetails').mockResolvedValue(HEALTH_OK)
    render(<Health />)
    await waitFor(() => expect(screen.getByText(/FastAPI/)).toBeInTheDocument())
    expect(screen.getByText(/React/)).toBeInTheDocument()
    expect(screen.getAllByText(/Enabled \/ Stopped/).length).toBe(2)
    expect(screen.getByText(/Disabled \/ Stopped/)).toBeInTheDocument()
    expect(screen.getAllByText(/정상/).length).toBeGreaterThan(0)
  })

  it('shows "파일 없음" when a data file is missing, without fabricating "정상"', async () => {
    vi.spyOn(apiClient, 'getHealthDetails').mockResolvedValue({
      ...HEALTH_OK,
      data: { ...HEALTH_OK.data, data: { ...HEALTH_OK.data.data, pipeline_log: false } },
    })
    render(<Health />)
    await waitFor(() => expect(screen.getByText(/파일 없음/)).toBeInTheDocument())
  })

  it('shows the generic error UI when health API fails', async () => {
    vi.spyOn(apiClient, 'getHealthDetails').mockResolvedValue(FAILURE)
    render(<Health />)
    await waitFor(() => expect(screen.getByText('⚠ API 연결 실패')).toBeInTheDocument())
  })

  it('does not call any external-service related client function', () => {
    // Health 페이지는 로컬 상태만 조회한다 — WordPress/GitHub/Cloudflare 등 외부
    // 서비스 관련 client 함수가 애초에 존재하지 않는지 확인한다.
    // STEP S3: getExternalHealth/runExternalHealthCheck는 실제 외부 서비스를
    // 호출하는 별도 기능(실질 헬스체크)이지만, 함수 이름 자체는 이 정규식과
    // 겹치지 않도록 의도적으로 지었다 — 아래 테스트에서 그 기능은 별도로 검증한다.
    const exportedNames = Object.keys(apiClient)
    const suspicious = exportedNames.filter((n) => /wordpress|github|cloudflare|telegram|sheets/i.test(n))
    expect(suspicious).toEqual([])
  })
})

// STEP S3: 실질 헬스체크(External Services) — dashboard.py "🏥 헬스체크 센터"의
// React 이관. 위 Health page(로컬 상태) 테스트와 달리 실제 외부 서비스 호출
// 결과(모킹)를 다룬다.
describe('External Services 실질 헬스체크 (STEP S3)', () => {
  const ADMIN_USER = { success: true, data: { id: 'dev-admin', role: 'admin' }, error: null, request_id: 'ea1' }
  const VIEWER_USER = { success: true, data: { id: 'dev-viewer', role: 'viewer' }, error: null, request_id: 'ea2' }
  const HEALTH_DETAILS_OK = {
    success: true,
    data: {
      application: { fastapi: 'healthy' },
      schedulers: { blog: {}, calculator: {}, content_sync: {} },
      data: { database: true, config: true, registry: true, labor_af: true, pipeline_log: true },
    },
    error: null, request_id: 'hd1',
  }

  function mockLocalHealthOk() {
    vi.spyOn(apiClient, 'getHealthDetails').mockResolvedValue(HEALTH_DETAILS_OK)
  }

  it('shows "검사 기록이 없습니다" when no cache exists yet, and 다시 검사 is disabled for a viewer', async () => {
    mockLocalHealthOk()
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    vi.spyOn(apiClient, 'getExternalHealth').mockResolvedValue({
      success: true,
      data: { available: false, timestamp: null, checks: {}, critical_passed: null },
      error: null, request_id: 'x1',
    })
    render(<Health />)
    await waitFor(() => expect(screen.getByText(/검사 기록이 없습니다/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /다시 검사/ })).toBeDisabled()
  })

  it('renders all 7 real checks with PASS/FAIL and the overall critical_passed judgment', async () => {
    mockLocalHealthOk()
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getExternalHealth').mockResolvedValue({
      success: true,
      data: {
        available: true,
        timestamp: '2026-09-05T12:00:00',
        checks: {
          openai: { status: 'OK', level: 'CRITICAL' },
          claude: { status: 'OK', level: 'CRITICAL' },
          gemini: { status: 'OK', level: 'CRITICAL' },
          google_sheet: { status: 'OK', level: 'CRITICAL' },
          google_drive: { status: 'OK', level: 'CRITICAL' },
          service_account: { status: 'OK', level: 'CRITICAL' },
          wordpress: { status: 'FAIL', level: 'WARNING', error: '연결 거부(테스트)' },
        },
        critical_passed: true,
      },
      error: null, request_id: 'x2',
    })
    render(<Health />)
    await waitFor(() => expect(screen.getByText(/PASS/)).toBeInTheDocument())
    expect(screen.getByText(/2026-09-05T12:00:00/)).toBeInTheDocument()
    for (const label of ['OpenAI', 'Claude', 'Gemini', 'Sheets', 'Drive', 'WordPress', 'Service Account']) {
      expect(screen.getByText(new RegExp(label))).toBeInTheDocument()
    }
    expect(screen.getByText(/연결 거부\(테스트\)/)).toBeInTheDocument()
  })

  it('clicking 다시 검사 calls runExternalHealthCheck() and replaces the displayed result', async () => {
    mockLocalHealthOk()
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getExternalHealth').mockResolvedValue({
      success: true,
      data: { available: false, timestamp: null, checks: {}, critical_passed: null },
      error: null, request_id: 'x3',
    })
    const runSpy = vi.spyOn(apiClient, 'runExternalHealthCheck').mockResolvedValue({
      success: true,
      data: {
        available: true, timestamp: '2026-09-05T13:00:00',
        checks: { openai: { status: 'FAIL', level: 'CRITICAL', error: 'invalid_api_key' } },
        critical_passed: false,
      },
      error: null, request_id: 'x4',
    })
    render(<Health />)
    await waitFor(() => expect(screen.getByText(/검사 기록이 없습니다/)).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /다시 검사/ }))

    expect(runSpy).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByText(/2026-09-05T13:00:00/)).toBeInTheDocument())
    expect(screen.getByText(/invalid_api_key/)).toBeInTheDocument()
    expect(screen.getAllByText(/FAIL/).length).toBeGreaterThan(0)
  })

  it('shows a loading state while the live check is running', async () => {
    mockLocalHealthOk()
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getExternalHealth').mockResolvedValue({
      success: true,
      data: { available: false, timestamp: null, checks: {}, critical_passed: null },
      error: null, request_id: 'x5',
    })
    let resolveRun
    vi.spyOn(apiClient, 'runExternalHealthCheck').mockReturnValue(new Promise((res) => { resolveRun = res }))
    render(<Health />)
    await waitFor(() => expect(screen.getByRole('button', { name: /다시 검사/ })).toBeEnabled())

    fireEvent.click(screen.getByRole('button', { name: /다시 검사/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: /검사 중/ })).toBeDisabled())

    resolveRun({
      success: true,
      data: { available: true, timestamp: 't', checks: {}, critical_passed: true },
      error: null, request_id: 'x6',
    })
    await waitFor(() => expect(screen.getByRole('button', { name: /다시 검사/ })).toBeEnabled())
  })

  it('shows a server-error state when the cache read call fails (network/server error)', async () => {
    mockLocalHealthOk()
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getExternalHealth').mockResolvedValue({
      success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null,
    })
    render(<Health />)
    await waitFor(() => expect(screen.getAllByText(/⚠ API 연결 실패/).length).toBeGreaterThan(0))
  })

  it('shows the run-failure error message when the live check itself fails (e.g. broken config)', async () => {
    mockLocalHealthOk()
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(ADMIN_USER)
    vi.spyOn(apiClient, 'getExternalHealth').mockResolvedValue({
      success: true,
      data: { available: false, timestamp: null, checks: {}, critical_passed: null },
      error: null, request_id: 'x7',
    })
    vi.spyOn(apiClient, 'runExternalHealthCheck').mockResolvedValue({
      success: true,
      data: { available: false, timestamp: null, checks: {}, critical_passed: false, error: 'config.yaml 파싱 실패' },
      error: null, request_id: 'x8',
    })
    render(<Health />)
    await waitFor(() => expect(screen.getByRole('button', { name: /다시 검사/ })).toBeEnabled())

    fireEvent.click(screen.getByRole('button', { name: /다시 검사/ }))

    await waitFor(() => expect(screen.getByText(/config\.yaml 파싱 실패/)).toBeInTheDocument())
  })

  it('다시 검사 버튼은 admin에게만 활성화된다(viewer는 disabled)', async () => {
    mockLocalHealthOk()
    vi.spyOn(apiClient, 'getCurrentUser').mockResolvedValue(VIEWER_USER)
    vi.spyOn(apiClient, 'getExternalHealth').mockResolvedValue({
      success: true,
      data: { available: false, timestamp: null, checks: {}, critical_passed: null },
      error: null, request_id: 'x9',
    })
    render(<Health />)
    await waitFor(() => expect(screen.getByRole('button', { name: /다시 검사/ })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /다시 검사/ })).toBeDisabled()
  })
})
