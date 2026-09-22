import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from '../App.jsx'
import * as apiClient from '../api/client.js'

const SUCCESS_HEALTH = { success: true, data: { status: 'ok', service: 'calcmate-api' }, error: null, request_id: 'r1' }
const SUCCESS_SCHEDULER = (name) => ({
  success: true,
  data: { name, enabled: false, running: false, thread_alive: false },
  error: null,
  request_id: 'r2',
})
const SUCCESS_DASHBOARD = { success: true, data: { api: 'ok', dashboard: 'fastapi', workers: {} }, error: null, request_id: 'r3' }
const FAILURE = { success: false, data: null, error: { code: 'NETWORK_ERROR', message: 'boom' }, request_id: null }

const SUCCESS_BLOG_CONFIG = {
  success: true,
  data: { enabled: true, mode: 'draft', publish_slots: [{ start: '06:00', end: '06:30' }], weekday_only: false },
  error: null,
  request_id: 'r4',
}
const SUCCESS_BLOG_TODAY = {
  success: true,
  data: { date: '2026-09-02', schedule: [] },
  error: null,
  request_id: 'r5',
}
const SUCCESS_BLOG_HISTORY = {
  success: true,
  data: { records: [] },
  error: null,
  request_id: 'r6',
}

function mockAllSuccess() {
  vi.spyOn(apiClient, 'getHealth').mockResolvedValue(SUCCESS_HEALTH)
  vi.spyOn(apiClient, 'getDashboardStatus').mockResolvedValue(SUCCESS_DASHBOARD)
  vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(SUCCESS_SCHEDULER('blog'))
  vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue(SUCCESS_SCHEDULER('calculator'))
  vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue(SUCCESS_SCHEDULER('content_sync'))
  vi.spyOn(apiClient, 'getBlogSchedulerConfig').mockResolvedValue(SUCCESS_BLOG_CONFIG)
  vi.spyOn(apiClient, 'getBlogSchedulerToday').mockResolvedValue(SUCCESS_BLOG_TODAY)
  vi.spyOn(apiClient, 'getBlogSchedulerHistory').mockResolvedValue(SUCCESS_BLOG_HISTORY)
}

function mockAllFailure() {
  vi.spyOn(apiClient, 'getHealth').mockResolvedValue(FAILURE)
  vi.spyOn(apiClient, 'getDashboardStatus').mockResolvedValue(FAILURE)
  vi.spyOn(apiClient, 'getBlogSchedulerStatus').mockResolvedValue(FAILURE)
  vi.spyOn(apiClient, 'getCalculatorSchedulerStatus').mockResolvedValue(FAILURE)
  vi.spyOn(apiClient, 'getContentSyncStatus').mockResolvedValue(FAILURE)
  vi.spyOn(apiClient, 'getBlogSchedulerConfig').mockResolvedValue(FAILURE)
  vi.spyOn(apiClient, 'getBlogSchedulerToday').mockResolvedValue(FAILURE)
  vi.spyOn(apiClient, 'getBlogSchedulerHistory').mockResolvedValue(FAILURE)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('API client', () => {
  it('exposes the 5 STEP 18-D GET functions', () => {
    expect(typeof apiClient.getHealth).toBe('function')
    expect(typeof apiClient.getDashboardStatus).toBe('function')
    expect(typeof apiClient.getBlogSchedulerStatus).toBe('function')
    expect(typeof apiClient.getCalculatorSchedulerStatus).toBe('function')
    expect(typeof apiClient.getContentSyncStatus).toBe('function')
  })

  it('exposes exactly the Blog Scheduler management functions added in STEP 18-E', () => {
    expect(typeof apiClient.getBlogSchedulerConfig).toBe('function')
    expect(typeof apiClient.getBlogSchedulerToday).toBe('function')
    expect(typeof apiClient.getBlogSchedulerHistory).toBe('function')
    expect(typeof apiClient.patchBlogSchedulerConfig).toBe('function')
    expect(typeof apiClient.runBlogSchedulerOnce).toBe('function')
  })

  it('exposes exactly the Calculator read functions added in STEP 18-F (no write functions)', () => {
    expect(typeof apiClient.getCalculators).toBe('function')
    expect(typeof apiClient.getCalculator).toBe('function')
    expect(typeof apiClient.getCalculatorContent).toBe('function')
    expect(typeof apiClient.getCalculatorStatus).toBe('function')
  })

  it('does not export any write function outside the known require_admin-protected domains', () => {
    // STEP 4-F: patchGeneralSettings, STEP 4-G: patchCalculatorFormula,
    // STEP 4-H-2: patchCalculatorChecklist가 각각 require_admin 뒤에서 정당하게 추가됨.
    // P0-5: postContractSave가 require_admin 뒤에서 정당하게 추가됨(Mode B 저장).
    // STEP S3: runExternalHealthCheck가 require_admin 뒤에서 정당하게 추가됨(실질
    // 헬스체크 재실행 — 외부 서비스를 실제로 호출하는 비용성 작업).
    // STEP S8: postStrategyRoomRun이 require_admin 뒤에서 정당하게 추가됨(전략회의실
    // 실행 — AI 호출 비용이 발생하는 작업).
    // STEP S10: postContentSyncRunOnce가 require_admin 뒤에서 정당하게 추가됨
    // (Content Sync 수동 실행 — WordPress 조회 + Sheet/DB write가 발생하는 작업).
    // STEP S11: postCalculatorRunOnce가 require_admin 뒤에서 정당하게 추가됨
    // (Dashboard Quick Action 「계산기 생성」 수동 실행 — AI 호출 + DB write가 발생하는 작업).
    // STEP S12: postPipelineRunOnce가 require_admin 뒤에서 정당하게 추가됨
    // (Dashboard Quick Action 「파이프라인 실행(전량)」 수동 실행 — AI 호출 +
    // 이미지 생성 + DB/비용 write + WordPress 발행 시도가 발생하는 작업).
    // STEP S13: postIntegratedRunOnce가 require_admin 뒤에서 정당하게 추가됨
    // (Dashboard Quick Action 「▶ 실행」(통합 실행) — S11/S12 서비스를 site
    // platform에 따라 재사용하는 dispatcher).
    // STEP P2-06: postCreateSite가 require_admin 뒤에서 정당하게 추가됨(Site
    // Management 사이트 생성 — DB write + secrets.yaml write가 발생하는 작업).
    // postImportSites는 정규식(create/update/delete/patch/save/write/enable/
    // disable/run/start/stop)에 매치하지 않아 allowlist에 추가할 필요가 없다.
    // STEP P2-07: putUpdateSite("update" 포함)/postSaveOverride("save" 포함)가
    // require_admin 뒤에서 정당하게 추가됨(기본 정보 수정 / Override 저장).
    // getSite/postResetOverride는 정규식에 매치하지 않아 allowlist에 추가할
    // 필요가 없다(reset은 위 정규식 키워드 목록에 포함되지 않는다).
    // STEP P2-08: postActivateSite/postDeactivateSite/postArchiveSite/
    // postRestoreSite 전부 정규식에 매치하지 않아(activate/deactivate/
    // archive/restore 어느 것도 위 키워드 목록과 겹치지 않음) allowlist에
    // 추가할 필요가 없다 — require_admin 뒤에서 정당하게 추가된 write
    // 함수들이다.
    // STEP P2-09: deleteSite("delete" 포함)가 require_admin 뒤에서 정당하게
    // 추가됨(Hard Delete). postCloneSite는 정규식에 매치하지 않아
    // allowlist에 추가할 필요가 없다.
    // STEP P2-14: patchImageGoogleSettings("patch" 포함)가 require_admin
    // 뒤에서 정당하게 추가됨(Image-gen AI/Google 연동 설정 저장).
    // getImageGoogleSettings는 정규식에 매치하지 않아 allowlist에 추가할
    // 필요가 없다.
    // CALCMATE-BLOG-PUBLISHING-POLICY-FASTAPI-REACT-CONNECTION-IMPLEMENT-01:
    // patchPublishingPolicy/patchAutoPublishing("patch" 포함)이 require_admin
    // 뒤에서 정당하게 추가됨(Publishing Policy/Auto Publishing 저장).
    // getPublishingPolicy/getAutoPublishing/getPublishingPolicyPreview는
    // 정규식에 매치하지 않아 allowlist에 추가할 필요가 없다.
    const allowedWriteNames = new Set([
      'patchBlogSchedulerConfig',
      'runBlogSchedulerOnce',
      'patchGeneralSettings',
      'patchCalculatorFormula',
      'patchCalculatorChecklist',
      'postContractSave',
      'runExternalHealthCheck',
      'postStrategyRoomRun',
      'postContentSyncRunOnce',
      'postCalculatorRunOnce',
      'postPipelineRunOnce',
      'postIntegratedRunOnce',
      'postCreateSite',
      'putUpdateSite',
      'postSaveOverride',
      'deleteSite',
      'patchImageGoogleSettings',
      'patchPublishingPolicy',
      'patchAutoPublishing',
    ])
    const exportedNames = Object.keys(apiClient)
    const forbidden = exportedNames.filter(
      (n) => !allowedWriteNames.has(n) && /create|update|delete|patch|save|write|enable|disable|run|start|stop/i.test(n)
    )
    expect(forbidden).toEqual([])
  })
})

describe('Dashboard route (/)', () => {
  beforeEach(() => mockAllSuccess())

  it('renders 운영센터 heading and scheduler cards on success', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('heading', { name: 'CalcMate Dashboard' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Blog Scheduler')).toBeInTheDocument())
    expect(screen.getByText('Calculator Scheduler')).toBeInTheDocument()
    expect(screen.getByText('Content Sync')).toBeInTheDocument()
    // enabled/running/thread_alive 전부 false → OFF 배지만 존재해야 한다
    await waitFor(() => {
      expect(screen.getAllByText('OFF').length).toBeGreaterThan(0)
    })
    expect(screen.queryByText(/ON/)).not.toBeInTheDocument()
  })
})

describe('Dashboard route API failure handling', () => {
  beforeEach(() => mockAllFailure())

  it('shows the generic error UI when API calls fail', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>
    )
    await waitFor(() => {
      expect(screen.getAllByText('⚠ API 연결 실패').length).toBeGreaterThan(0)
    })
  })
})

describe('Scheduler route (/scheduler)', () => {
  beforeEach(() => mockAllSuccess())

  it('renders Scheduler heading and the 3 scheduler sections', async () => {
    render(
      <MemoryRouter initialEntries={['/scheduler']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('heading', { name: 'Scheduler' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('Blog Scheduler')).toBeInTheDocument())
    expect(screen.getByText('Calculator Scheduler')).toBeInTheDocument()
    expect(screen.getByText('Content Sync')).toBeInTheDocument()
  })

  it('Calculator Scheduler / Content Sync cards stay read-only (no toggle/실행 button)', async () => {
    render(
      <MemoryRouter initialEntries={['/scheduler']}>
        <App />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByText('Calculator Scheduler')).toBeInTheDocument())
    // 체크박스 2개(Enabled, weekday_only)는 전부 Blog Scheduler 패널 소속이어야 한다 —
    // Calculator Scheduler / Content Sync 섹션에는 입력 요소가 전혀 없다.
    expect(screen.queryAllByRole('checkbox')).toHaveLength(2)
    expect(screen.queryByRole('switch')).not.toBeInTheDocument()
    expect(screen.queryAllByRole('button', { name: /실행/ })).toHaveLength(1)
  })

  it('Blog Scheduler panel provides Save and Run Once controls (STEP 18-E)', async () => {
    render(
      <MemoryRouter initialEntries={['/scheduler']}>
        <App />
      </MemoryRouter>
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /Blog 1회 실행/ })).toBeInTheDocument()
    expect(screen.getByLabelText('Enabled')).toBeInTheDocument()
  })
})

describe('Sidebar navigation', () => {
  beforeEach(() => mockAllSuccess())

  it('has the top-level menu items (STEP 18-D/E/F/M, restructured in STEP V1-OPS-04)', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('link', { name: '🏠 운영센터' })).toBeInTheDocument()
    expect(screen.getByText('🧮 계산기')).toBeInTheDocument()
    expect(screen.getByText('📝 블로그')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '📋 Publish' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '🗑️ Trash' })).toBeInTheDocument()
  })

  it('has the Settings and Health menu items (STEP 18-M)', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('link', { name: '⚙️ Settings' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '❤️ Health' })).toBeInTheDocument()
  })

  it('groups Calculator sub-tabs under 🧮 계산기 (STEP V1-OPS-04)', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('link', { name: '목록' })).toHaveAttribute('href', '/calculators')
    expect(screen.getByRole('link', { name: '생성/관리' })).toHaveAttribute('href', '/calculators?new=1')
    const schedulerLinks = screen.getAllByRole('link', { name: 'Scheduler' })
    expect(schedulerLinks.some((a) => a.getAttribute('href') === '/calculator-scheduler')).toBe(true)
  })

  it('marks only 목록 active on /calculators (STEP V1-OPS-06)', () => {
    render(
      <MemoryRouter initialEntries={['/calculators']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('link', { name: '목록' })).toHaveClass('sidebar__link--active')
    expect(screen.getByRole('link', { name: '생성/관리' })).not.toHaveClass('sidebar__link--active')
  })

  it('marks only 생성/관리 active on /calculators?new=1 (STEP V1-OPS-06)', () => {
    render(
      <MemoryRouter initialEntries={['/calculators?new=1']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('link', { name: '목록' })).not.toHaveClass('sidebar__link--active')
    expect(screen.getByRole('link', { name: '생성/관리' })).toHaveClass('sidebar__link--active')
  })

  it('groups Blog sub-tabs under 📝 블로그, both 생성/Scheduler point to the same page (STEP V1-OPS-04)', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.getByRole('link', { name: '목록/관리' })).toHaveAttribute('href', '/blog')
    const generateLink = screen.getByRole('link', { name: '생성' })
    const schedulerLinks = screen.getAllByRole('link', { name: 'Scheduler' })
    const blogSchedulerLink = schedulerLinks.find((a) => a.getAttribute('href') === '/blog-scheduler')
    expect(generateLink).toHaveAttribute('href', '/blog-scheduler')
    expect(blogSchedulerLink).toBeTruthy()
  })

  it('no longer shows the old flat ⏱ Scheduler / 🧮 Calculators links', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <App />
      </MemoryRouter>
    )
    expect(screen.queryByRole('link', { name: '⏱ Scheduler' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '🧮 Calculators' })).not.toBeInTheDocument()
  })
})
