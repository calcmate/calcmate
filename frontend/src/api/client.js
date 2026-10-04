// src/api/client.js — FastAPI 공통 API client.
// STEP 18-D: GET만 정의. STEP 18-E: Blog Scheduler PATCH/POST 2개 추가
// (config 저장, 수동 1회 실행 — 둘 다 명시적 사용자 조작에 의해서만 호출된다).
//
// 기본값은 상대경로(같은 origin)다 — 운영 배포 시 React 정적 자산과 FastAPI가
// 동일 origin(리버스 프록시)에 있는 것을 기본 가정으로 하고, 개발 중에는
// vite.config.js의 server.proxy가 /api를 FastAPI(127.0.0.1:8000)로 중계해
// CORS 없이 동작한다. 크로스오리진 배포 시에만 VITE_API_BASE_URL로 override.

import { authHeaders } from './auth.js'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

function networkErrorEnvelope(err) {
  // 네트워크 오류 등도 표준 응답 봉투와 동일한 형태로 반환해 화면단 처리를 단순화한다.
  return {
    success: false,
    data: null,
    error: { code: 'NETWORK_ERROR', message: err instanceof Error ? err.message : String(err) },
    request_id: null,
  }
}

async function getJson(path) {
  try {
    const res = await fetch(`${BASE_URL}${path}`)
    return await res.json()
  } catch (err) {
    return networkErrorEnvelope(err)
  }
}

// STEP S2: getJson()은 인증 헤더를 보내지 않는다(기존 GET 조회 endpoint가 전부
// 인증 없이 공개였기 때문). Contract Prefill/Instance 조회는 require_admin으로
// 보호되므로(다른 Contract endpoint와 동일한 정책), 이 헬퍼로 Authorization
// 헤더를 함께 보낸다 — LOCAL_MODE에서는 서버가 인증 자체를 우회하므로 평소엔
// 차이가 없지만, 실제 토큰이 설정된 환경에서 401 없이 동작하려면 필요하다.
async function getJsonAuth(path) {
  try {
    const res = await fetch(`${BASE_URL}${path}`, { headers: { ...authHeaders() } })
    return await res.json()
  } catch (err) {
    return networkErrorEnvelope(err)
  }
}

async function sendJson(path, method, payload) {
  // STEP 18-Q: 토큰이 설정돼 있으면 Authorization 헤더를 함께 보낸다(없으면
  // authHeaders()가 빈 객체를 반환하므로 기존 동작과 완전히 동일하다). 현재
  // 이 함수를 쓰는 두 endpoint(Blog Scheduler config PATCH / run-once POST)는
  // 아직 서버 쪽에서 인증을 강제하지 않는다 — 향후 연결을 위한 선제 배선이다.
  try {
    const res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: payload !== undefined ? JSON.stringify(payload) : undefined,
    })
    return await res.json()
  } catch (err) {
    return networkErrorEnvelope(err)
  }
}

export function getHealth() {
  return getJson('/api/health')
}

export function getDashboardStatus() {
  return getJson('/api/dashboard/status')
}

// STEP P2-01: Dashboard Home/KPI 조회(require_admin — 비용 데이터 포함, /api/costs와
// 동일한 정책).
export function getDashboardKpi() {
  return getJsonAuth('/api/dashboard/kpi')
}

// STEP P2-02: Dashboard 순수 상태/진행 표시 조회(require_admin, P2-01과 동일 정책).
export function getDashboardPipelineStatus() {
  return getJsonAuth('/api/dashboard/pipeline-status')
}

export function getDashboardProgress() {
  return getJsonAuth('/api/dashboard/progress')
}

// STEP P2-10: "📊 현황" 탭(상태별 개수/오늘 발행/목표/진행률) 조회(require_admin,
// P2-01/P2-02와 동일 정책). getDashboardProgress()(scheduler 기반)와는 다른
// 데이터 source(articles 테이블)를 쓰는 별개 endpoint다.
export function getDashboardStatusSummary() {
  return getJsonAuth('/api/dashboard/status-summary')
}

// STEP P2-11: "📊 AI Pipeline Monitor" 조회(require_admin). 기존 공개 GET
// /api/pipeline/status와 동일한 데이터이지만, cost/token 데이터를 포함하므로
// P2-01의 KPI(비용 포함)와 동일한 정책으로 admin 전용 경로를 새로 쓴다.
export function getDashboardAiPipeline() {
  return getJsonAuth('/api/dashboard/ai-pipeline')
}

export function getBlogSchedulerStatus() {
  return getJson('/api/scheduler/blog/status')
}

export function getCalculatorSchedulerStatus() {
  return getJson('/api/scheduler/calculator/status')
}

export function getContentSyncStatus() {
  return getJson('/api/scheduler/content-sync/status')
}

// ── STEP 18-E: Blog Scheduler 관리 ──────────────────────────────────────

export function getBlogSchedulerConfig() {
  return getJson('/api/scheduler/blog/config')
}

export function patchBlogSchedulerConfig(payload) {
  return sendJson('/api/scheduler/blog/config', 'PATCH', payload)
}

export function getBlogSchedulerToday() {
  return getJson('/api/scheduler/blog/today')
}

export function getBlogSchedulerHistory() {
  return getJson('/api/scheduler/blog/history')
}

// CALCMATE-DASHBOARD-ONEOFF-SCHEDULER-VIEW-IMPLEMENT-01: 1회성(one-off) 예약
// 목록 조회. 다른 조회 endpoint(status/config/today/history)와 동일하게
// 인증 없는 getJson()을 사용한다(기존 GET 조회 endpoint 정책과 동일).
export function getBlogSchedulerOneoff() {
  return getJson('/api/scheduler/blog/oneoff')
}

export function runBlogSchedulerOnce() {
  return sendJson('/api/scheduler/blog/run-once', 'POST')
}

export function runBlogSchedulerOnceOneoff(mode = 'draft') {
  return sendJson('/api/scheduler/blog/run-once/oneoff', 'POST', { mode })
}

// CALCMATE-STREAMLIT-RESERVATION-API-IMPLEMENT-01: 수동 1회성 예약 생성(Topic
// 지정 가능). POST /blog/oneoff는 require_admin이므로 인증 헤더가 필요하다.
export function createOneoffReservation({ scheduledAt, mode = 'draft', topicId = null }) {
  return sendJson('/api/scheduler/blog/oneoff', 'POST', {
    scheduled_at: scheduledAt, mode, topic_id: topicId,
  })
}

// Topic Pool 조회(다른 조회 endpoint와 동일하게 인증 없이 공개). status를
// 지정하지 않으면 전체를 반환한다.
export function getTopicPool(status = null) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return getJson(`/api/scheduler/topics${qs}`)
}

// Publishing Planner 수동 1회 실행(require_admin, body 없음).
export function runPlannerOnce() {
  return sendJson('/api/scheduler/planner/run-once', 'POST')
}

// ── Publishing Policy ──────────────────────────────────────────────────────
// Publishing Policy는 Blog Scheduler와 별도의 정책(PUBLISHING_POLICY section)을
// 관리한다. Topic Pool 기반 자동 발행 전용 설정이다.

export function getPublishingPolicy() {
  return getJsonAuth('/api/scheduler/publishing-policy')
}

export function patchPublishingPolicy(payload) {
  return sendJson('/api/scheduler/publishing-policy', 'PATCH', payload)
}

export function getPublishingPolicyPreview(days = 7) {
  return getJsonAuth(`/api/scheduler/publishing-policy/preview?days=${encodeURIComponent(days)}`)
}

export function getAutoPublishing() {
  return getJsonAuth('/api/scheduler/auto-publishing')
}

export function patchAutoPublishing(enabled) {
  return sendJson('/api/scheduler/auto-publishing', 'PATCH', { enabled })
}

// ── STEP 18-F: Calculator 조회(GET만 — 생성/삭제/배포 함수는 추가하지 않는다) ──

export function getCalculators() {
  return getJson('/api/calculators')
}

export function getCalculator(slug) {
  return getJson(`/api/calculators/${encodeURIComponent(slug)}`)
}

export function getCalculatorContent(slug) {
  return getJson(`/api/calculators/${encodeURIComponent(slug)}/content`)
}

export function getCalculatorStatus(slug) {
  return getJson(`/api/calculators/${encodeURIComponent(slug)}/status`)
}

// ── STEP 4-G: Calculator Formula 조회/저장 ──────────────────────────────
// PATCH는 admin 전용(서버가 401/403으로 차단, Publish/Trash/Settings와 동일한 패턴).

export function getCalculatorFormula(slug) {
  return getJson(`/api/calculators/${encodeURIComponent(slug)}/formula`)
}

export function patchCalculatorFormula(slug, formula) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/formula`, 'PATCH', { formula })
}

// ── STEP 4-H-1: Calculator READY 승인(promote) ──────────────────────────
// admin 전용(서버가 401/403으로 차단, Formula PATCH와 동일한 패턴).

export function postCalculatorPromote(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/promote`, 'POST')
}

// ── P0-2: Build/Deploy — admin 전용(서버가 401/403으로 차단, Promote와 동일 패턴) ──

export function postCalculatorBuild(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/build`, 'POST')
}

export function postCalculatorDeploy(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/deploy`, 'POST')
}

// ── STEP S1: Human Review Approval — GET은 다른 조회 endpoint와 동일하게 인증
// 없이 공개, approve/unapprove는 admin 전용(Build/Deploy와 동일 패턴) ──────────

export function getCalculatorReview(slug) {
  return getJson(`/api/calculators/${encodeURIComponent(slug)}/review`)
}

export function postCalculatorReviewApprove(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/review/approve`, 'POST')
}

export function postCalculatorReviewUnapprove(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/review/unapprove`, 'POST')
}

// ── P0-3: Preview — 다른 GET 조회 endpoint와 동일하게 인증 없이 공개 ──────

export function getCalculatorPreview(slug) {
  return getJson(`/api/calculators/${encodeURIComponent(slug)}/preview`)
}

// ── P0-4: 콘텐츠 생성(SEO/FAQ/본문/이미지/전체) — admin 전용(Build/Deploy와 동일 패턴) ──

export function postCalculatorContentSeo(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/content/seo`, 'POST')
}

export function postCalculatorContentFaq(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/content/faq`, 'POST')
}

export function postCalculatorContentBody(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/content/body`, 'POST')
}

export function postCalculatorContentImage(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/content/image`, 'POST')
}

export function postCalculatorContentGenerateAll(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/content/generate`, 'POST')
}

// ── P0-5: Mode B(Contract 기반 생성) — admin 전용(서버가 401/403으로 차단) ──────

export function postContractSlugCheck(slug) {
  return sendJson('/api/calculators/generate/contract/slug-check', 'POST', { slug })
}

export function postContractFormulaValidate(formula, inputFields, testCases) {
  return sendJson('/api/calculators/generate/contract/validate', 'POST', {
    formula, input_fields: inputFields, test_cases: testCases,
  })
}

// STEP S2: Registry prefill / 저장된 Contract instance 복원 — 둘 다 읽기 전용(GET)
// 이지만 다른 Contract endpoint와 동일하게 require_admin으로 보호된다.
export function getContractPrefill(slug) {
  return getJsonAuth(`/api/calculators/generate/contract/prefill/${encodeURIComponent(slug)}`)
}

export function getContractInstance(slug) {
  return getJsonAuth(`/api/calculators/generate/contract/instance/${encodeURIComponent(slug)}`)
}

// postCalculatorGenerate(Mode A)와 동일한 이유로 raw fetch를 쓴다 — 409(busy)를
// 표준 success/error 봉투가 아니라 HTTP status로 직접 구분해야 하기 때문
// (sendJson()은 status를 노출하지 않는다).
export async function postContractGenerate(payload) {
  try {
    const res = await fetch(`${BASE_URL}/api/calculators/generate/contract`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(payload),
    })
    const body = await res.json()
    return { status: res.status, body }
  } catch (err) {
    return { status: 0, body: networkErrorEnvelope(err) }
  }
}

export function getContractGenerationJob(jobId) {
  return getJson(`/api/calculators/generate/contract/${encodeURIComponent(jobId)}`)
}

export function postContractSave(jobId, slug) {
  return sendJson(`/api/calculators/generate/contract/${encodeURIComponent(jobId)}/save`, 'POST', { slug })
}

// ── STEP 4-H-2: Legal Hold 체크리스트 조회/수정 ─────────────────────────
// PATCH는 admin 전용(서버가 401/403으로 차단, Formula/Promote와 동일한 패턴).

export function getCalculatorChecklist(slug) {
  return getJson(`/api/calculators/${encodeURIComponent(slug)}/checklist`)
}

export function patchCalculatorChecklist(slug, items) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/checklist`, 'PATCH', { items })
}

// ── STEP 4-H-6: Calculator 생성(Mode A) + Job 폴링 ──────────────────────
// admin 전용(서버가 401/403으로 차단). generate POST는 성공 시에도 이미 실행
// 중이면 409를 반환하는데, sendJson()은 HTTP status를 노출하지 않고 promote/
// checklist와 마찬가지로 4xx 응답은 표준 success/error 봉투가 아니라
// FastAPI HTTPException의 {detail: "..."} 형태로 온다 — 이를 구분하기 위해
// 이 함수만 별도로 fetch해 status를 함께 반환한다(sendJson 자체는 다른
// 호출자에 영향을 주지 않도록 변경하지 않는다).
export async function postCalculatorGenerate(payload) {
  try {
    const res = await fetch(`${BASE_URL}/api/calculators/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(payload),
    })
    const body = await res.json()
    return { status: res.status, body }
  } catch (err) {
    return { status: 0, body: networkErrorEnvelope(err) }
  }
}

export function getCalculatorGenerationJob(jobId) {
  return getJson(`/api/calculators/generate/${encodeURIComponent(jobId)}`)
}

// ── STEP 18-G: 로그/상태/비용 조회(GET만) ──────────────────────────────

export function getErrorLogs() {
  return getJson('/api/logs/errors')
}

export function getRecentLogs() {
  return getJson('/api/logs/recent')
}

export function getLiveLogs(level = 'all') {
  return getJson(`/api/logs/live?level=${encodeURIComponent(level)}`)
}

export function getPipelineStatus() {
  return getJson('/api/pipeline/status')
}

// STEP S4: /api/costs가 require_admin으로 보호되므로 인증 헤더가 필요하다.
export function getCosts() {
  return getJsonAuth('/api/costs')
}

// STEP S5: Cost Manager 수동 재개 / Retry Queue 수동 재시도(둘 다 require_admin).
export function postCostResume() {
  return sendJson('/api/costs/resume', 'POST')
}

export function postCostRetry(id) {
  return sendJson('/api/costs/retry', 'POST', { id })
}

// STEP S6: Retry Queue 수동 제거(require_admin).
export function postCostRemove(id) {
  return sendJson('/api/costs/remove', 'POST', { id })
}

// STEP S8: Strategy Room 실행(require_admin, body 없음).
export function postStrategyRoomRun() {
  return sendJson('/api/strategy-room/run', 'POST')
}

// STEP S9: 작업 현황 보드(Kanban) 조회(require_admin이므로 인증 헤더 필요).
export function getWorkboard() {
  return getJsonAuth('/api/workboard')
}

// STEP P2-04: Site Management 목록 조회(require_admin).
export function getSites() {
  return getJsonAuth('/api/sites')
}

// STEP P2-06: Site Management 생성/Import(require_admin). Update/Delete/Archive/
// Restore/Clone/Override는 이번 STEP 범위 밖 — 아직 없다.
export function postCreateSite(payload) {
  return sendJson('/api/sites', 'POST', payload)
}

export function postImportSites(rows) {
  return sendJson('/api/sites/import', 'POST', { rows })
}

// STEP P2-07: Site Management 개별 조회/기본 정보 수정/Override 저장·초기화
// (전부 require_admin). Delete/Archive/Restore/Clone은 이번 STEP 범위 밖 — 아직 없다.
export function getSite(siteId) {
  return getJsonAuth(`/api/sites/${encodeURIComponent(siteId)}`)
}

export function putUpdateSite(siteId, payload) {
  return sendJson(`/api/sites/${encodeURIComponent(siteId)}`, 'PUT', payload)
}

export function postSaveOverride(siteId, payload) {
  return sendJson(`/api/sites/${encodeURIComponent(siteId)}/override`, 'POST', payload)
}

export function postResetOverride(siteId) {
  return sendJson(`/api/sites/${encodeURIComponent(siteId)}/override/reset`, 'POST')
}

// STEP P2-08: Activate/Deactivate/Archive/Restore(전부 require_admin). Hard
// Delete/Clone은 이번 STEP 범위 밖 — 아직 없다.
export function postActivateSite(siteId) {
  return sendJson(`/api/sites/${encodeURIComponent(siteId)}/activate`, 'POST')
}

export function postDeactivateSite(siteId) {
  return sendJson(`/api/sites/${encodeURIComponent(siteId)}/deactivate`, 'POST')
}

export function postArchiveSite(siteId) {
  return sendJson(`/api/sites/${encodeURIComponent(siteId)}/archive`, 'POST')
}

export function postRestoreSite(siteId) {
  return sendJson(`/api/sites/${encodeURIComponent(siteId)}/restore`, 'POST')
}

// STEP P2-09: Hard Delete/Clone(전부 require_admin). Hard Delete는 STEP 18-R
// Trash/Restore와 동일한 confirmation 문자열 패턴("DELETE" 정확히 일치)을
// 요구한다.
export function deleteSite(siteId, confirmation) {
  return sendJson(`/api/sites/${encodeURIComponent(siteId)}`, 'DELETE', { confirmation })
}

export function postCloneSite(siteId, payload) {
  return sendJson(`/api/sites/${encodeURIComponent(siteId)}/clone`, 'POST', payload)
}

// STEP S10: Content Sync 수동 실행(require_admin).
export function postContentSyncRunOnce(mode) {
  return sendJson('/api/scheduler/content-sync/run-once', 'POST', { mode })
}

// STEP S11: Dashboard Quick Action 「🧮 계산기 생성」 수동 실행(require_admin,
// body 없음). /api/scheduler/calculator/status(Calculator Scheduler=
// CALC_WEBAPP_SCHEDULE 조회)와는 별개의 endpoint다.
export function postCalculatorRunOnce() {
  return sendJson('/api/scheduler/calculator/run-once', 'POST')
}

// STEP S12: Dashboard Quick Action 「▶ 파이프라인 실행(전량)」 수동 실행
// (require_admin, body 없음). /api/scheduler/blog/run-once(Blog Scheduler)와는
// 다른 함수(main.py의 run_once)를 호출하는 별개의 endpoint다.
export function postPipelineRunOnce() {
  return sendJson('/api/scheduler/pipeline/run-once', 'POST')
}

// STEP S13: Dashboard Quick Action 「▶ 실행」(통합 실행) 수동 실행(require_admin).
// site의 활성 platforms에 따라 Calculator/Blog Pipeline 중 하나(또는 순차)를
// 서버가 고른다 — order는 둘 다 활성일 때만 의미가 있다(기본값 "순차").
// CURRENT-SITE-02: siteId(현재 Site 선택)를 함께 보낸다. 서버가 site를 다시 조회해
// 그 site의 platforms로 분기한다(생략하면 서버 기본값 = 전체 site 목록의 첫 번째).
export function postIntegratedRunOnce(order, siteId) {
  const body = { order }
  if (siteId) body.site_id = siteId
  return sendJson('/api/scheduler/integrated/run-once', 'POST', body)
}

// ── STEP 18-M: Settings/Health 조회(GET만 — 새 쓰기 함수는 추가하지 않는다) ──

export function getSettings() {
  return getJson('/api/settings')
}

export function getSettingsSection(section) {
  return getJson(`/api/settings/${encodeURIComponent(section)}`)
}

// ── STEP 4-F: General Settings(API 키/WordPress/Telegram/Budget/AI Roles) ──
// PATCH는 admin 전용(서버가 401/403으로 차단, Publish/Trash와 동일한 패턴).

export function getGeneralSettings() {
  return getJson('/api/settings/general')
}

export function patchGeneralSettings(payload) {
  return sendJson('/api/settings/general', 'PATCH', payload)
}

// STEP P2-14: Image-gen AI(IMAGE_PROVIDER/MODEL_IMAGE/IMAGE_SIZE/IMAGE_QUALITY)
// + Google 연동(GOOGLE_SHEET_ID/GOOGLE_DRIVE_ROOT_ID/
// GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID) — 둘 다 require_admin(GET도 admin 전용,
// getGeneralSettings()와 달리 GET에도 인증 필요 — STEP 4가 명시한 "새 admin
// 전용 endpoint" 지시를 그대로 따름).
export function getImageGoogleSettings() {
  return getJsonAuth('/api/settings/image-google')
}

export function patchImageGoogleSettings(payload) {
  return sendJson('/api/settings/image-google', 'PATCH', payload)
}

export function getHealthDetails() {
  return getJson('/api/health/details')
}

// STEP S3: 실질 헬스체크(OpenAI/Claude/Gemini/Sheets/Drive/WordPress/Service
// Account) — require_admin이므로 인증 헤더가 필요하다. getHealthDetails()와
// 달리 실제 외부 서비스를 호출하므로 별도 함수로 분리한다.
export function getExternalHealth() {
  return getJsonAuth('/api/health/external')
}

export function runExternalHealthCheck() {
  return sendJson('/api/health/external/run', 'POST')
}

// ── STEP 18-P: Publish/Trash 조회(GET만 — Publish/Trash/Restore/Edit 쓰기 함수는
// 인증 체계 구축 전까지 추가하지 않는다) ─────────────────────────────────

export function getPublishOverview() {
  return getJson('/api/publish')
}

export function getPublishArticles() {
  return getJson('/api/publish/articles')
}

export function getTrashArticles() {
  return getJson('/api/trash')
}

// ── STEP 18-Q: 인증 상태 조회(GET, require_authenticated) ────────────────

export function getCurrentUser() {
  return getJson('/api/auth/me')
}

// ── STEP 18-R: Publish/Trash 쓰기(전부 admin 전용, 서버가 401/403으로 차단) ──

export function postPublishEdit(id, payload) {
  return sendJson(`/api/publish/${encodeURIComponent(id)}/edit`, 'POST', payload)
}

export function postTrash(id, confirmation) {
  return sendJson(`/api/trash/${encodeURIComponent(id)}`, 'POST', { confirmation })
}

export function postTrashRestore(id, confirmation) {
  return sendJson(`/api/trash/${encodeURIComponent(id)}/restore`, 'POST', { confirmation })
}

// ── STEP 18-X: 실제 운영 Blog(calcmate.kr, _site/blog/*) 조회(GET만) ──────
// articles DB와 무관한 별도 데이터 소스다.

export function getBlogPosts() {
  return getJson('/api/blog')
}

// ── STEP 65: Content Sync Pending 큐 조회 / 수동 Retry / Resume ─────────────
// api/routers/scheduler.py의 5개 endpoint와 연결.
// Streamlit dashboard.py "🔁 동기화 복구" 탭 이관.

export function getPendingSync() {
  return getJsonAuth('/api/scheduler/content-sync/pending')
}

export function getProcessingSync() {
  return getJsonAuth('/api/scheduler/content-sync/processing')
}

export function getFailedSync() {
  return getJsonAuth('/api/scheduler/content-sync/failed')
}

export function postRetrySync(qid) {
  return sendJson('/api/scheduler/content-sync/retry', 'POST', { qid })
}

export function postResumeSync(qid) {
  return sendJson('/api/scheduler/content-sync/resume', 'POST', { qid })
}

// ── STEP 18-C: Calculator Display Settings ───────────────────────────────────
// api/routers/settings.py /calculator-display endpoint와 연결.
// Streamlit dashboard.py "🎨 계산기 노출 설정 (v2)" 이관.

export function getCalculatorDisplaySettings() {
  return getJsonAuth('/api/settings/calculator-display')
}

export function patchCalculatorDisplaySettings(updates) {
  return sendJson('/api/settings/calculator-display', 'PATCH', updates)
}

// ── CALCMATE-REMAINING-DASHBOARD-KEEP-MIGRATION-01 ──────────────────────────
// Streamlit dashboard.py "🔧 설정"(파이프라인 모델 매칭/운영 설정/TELEGRAM_EVENTS/
// 텔레그램 테스트), "⬇️ 사이트 Export", "🔍 published Topic ↔ WP 상태 대조" 이관.

export function getOperationsSettings() {
  return getJsonAuth('/api/settings/operations')
}

export function patchOperationsSettings(updates) {
  return sendJson('/api/settings/operations', 'PATCH', updates)
}

// 이름에 외부 서비스명을 넣지 않는다 — SettingsHealth.test.jsx가 client export 이름에
// wordpress/github/cloudflare/telegram/sheets가 없음을 검사한다(getExternalHealth와 같은 관례).
// 호출 대상은 우리 백엔드 POST /api/settings/telegram/test 그대로다.
export function postNotifyConnectionTest(payload = {}) {
  return sendJson('/api/settings/telegram/test', 'POST', payload)
}

export function getSitesExport() {
  return getJsonAuth('/api/sites/export')
}

export function postTopicWpCheck(topicId) {
  return sendJson(`/api/scheduler/topics/${encodeURIComponent(topicId)}/wp-check`, 'POST', {})
}

export function postTopicRevertCandidate(topicId) {
  return sendJson(`/api/scheduler/topics/${encodeURIComponent(topicId)}/revert-candidate`, 'POST', { confirm: true })
}

// CALCMATE-REMAINING-MIGRATION-SMALL-GAPS-02
// dashboard.py "📝 글 생성(1건)" — main.run_once(cfg, max_count=1). 파이프라인 전량
// 실행(postPipelineRunOnce)·Blog Scheduler 실행(runBlogSchedulerOnce)과 다른 기능이다.
export function postPipelineRunOne() {
  return sendJson('/api/scheduler/pipeline/run-one', 'POST')
}

// dashboard.py "🔌 WordPress 연결 테스트". 서버가 연결을 시도하고 결과만 돌려준다.
// (이름에 서비스명을 넣지 않는 기존 규칙 — SettingsHealth 테스트 참고)
export function postPublishConnectionTest(payload = {}) {
  return sendJson('/api/settings/wordpress/test', 'POST', payload)
}

// Mode A 생성 → 검토 → 저장/폐기. 진행 상태는 getCalculatorGenerationJob()으로 조회한다.
// 동시 생성 거부가 HTTP 409(detail)로 오므로 postCalculatorGenerate()와 같이 status를 함께 반환한다.
export async function postCalculatorPreviewGenerate(payload) {
  try {
    const res = await fetch(`${BASE_URL}/api/calculators/generate/preview`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(payload),
    })
    const body = await res.json()
    return { status: res.status, body }
  } catch (err) {
    return { status: 0, body: networkErrorEnvelope(err) }
  }
}

export function postCalculatorPreviewSave(jobId, slug) {
  return sendJson(`/api/calculators/generate/preview/${encodeURIComponent(jobId)}/save`, 'POST', { slug })
}

export function postCalculatorPreviewDiscard(jobId) {
  return sendJson(`/api/calculators/generate/preview/${encodeURIComponent(jobId)}/discard`, 'POST')
}

// CALCMATE-STREAMLIT-REMAINING-MIGRATION-APP-FACTORY-02 — App Factory AI 추천(require_admin).
// 추천은 표시/입력 보조일 뿐 생성·저장·배포를 일으키지 않는다.
export function postAiSuggestIdea(keyword) {
  return sendJson('/api/calculators/ai/suggest-idea', 'POST', { keyword: keyword || null })
}

export function postAiSuggestMode(payload) {
  return sendJson('/api/calculators/ai/suggest-mode', 'POST', payload)
}

export function postAiSuggestTier(payload) {
  return sendJson('/api/calculators/ai/suggest-tier', 'POST', payload)
}

// Tier2-B(날짜형) 키워드 감지 — 규칙은 서버에만 있다(AI 호출 없음).
export function postAiTier2bDetect(payload) {
  return sendJson('/api/calculators/ai/tier2b-keywords', 'POST', payload)
}

export function postAiSuggestSpec(payload) {
  return sendJson('/api/calculators/ai/suggest-spec', 'POST', payload)
}

// success=true여도 확정이 아니다 — 확정은 postContractConfirmFormula()(서버 재검증).
export function postAiSuggestFormula(payload) {
  return sendJson('/api/calculators/ai/suggest-formula', 'POST', payload)
}

export function postContractSlugSuggest(name) {
  return sendJson('/api/calculators/generate/contract/slug-suggest', 'POST', { name })
}

// body 없음 — 서버가 job에 저장된 Contract formula를 다시 검증해 확정 여부를 결정한다.
export function postContractConfirmFormula(jobId) {
  return sendJson(`/api/calculators/generate/contract/${encodeURIComponent(jobId)}/confirm-formula`, 'POST')
}

// SITE-PAGE-DEPLOYMENT-02 — 사이트 공통 페이지(전역 설정 기준 9개) 미리보기/로컬 저장/배포(require_admin).
// 배포는 서버가 로컬 Git으로 9개 파일만 1회 commit 후 원격과 동기화된 경우에만 push한다.
export function postSitePagesPreview() {
  return sendJson('/api/sites/pages/preview', 'POST')
}

export function postSitePagesSave() {
  return sendJson('/api/sites/pages/save', 'POST')
}

export function postSitePagesDeploy() {
  return sendJson('/api/sites/pages/deploy', 'POST')
}

// CALCMATE-STREAMLIT-REMAINING-MIGRATION-AI-ASSISTANT-02 — AI Assistant(운영비서). 전부 require_admin.
// 대화 기록은 서버에 저장되지 않는다(요청마다 messages를 보냄). 경로 검증·민감 파일 차단·
// 승인 재검증은 서버가 한다.
export function getAssistantModels() {
  return getJsonAuth('/api/assistant/models')
}

export function postAssistantChat(model, messages) {
  return sendJson('/api/assistant/chat', 'POST', { model, messages })
}

export function postAssistantFilesList(path) {
  return sendJson('/api/assistant/files/list', 'POST', { path })
}

export function postAssistantFileRead(path) {
  return sendJson('/api/assistant/files/read', 'POST', { path })
}

export function postAssistantFilePreview(path, content) {
  return sendJson('/api/assistant/files/preview', 'POST', { path, content })
}

export function postAssistantFileWrite(path, content, expectedOldSha256) {
  return sendJson('/api/assistant/files/write', 'POST', { path, content, expected_old_sha256: expectedOldSha256 })
}

export function postAssistantFileCreate(path, content) {
  return sendJson('/api/assistant/files/create', 'POST', { path, content })
}

export function getAssistantMemory() {
  return getJsonAuth('/api/assistant/memory')
}

export function postAssistantMemory(kind, text) {
  return sendJson('/api/assistant/memory', 'POST', { kind, text })
}

export function getAssistantTasks() {
  return getJsonAuth('/api/assistant/tasks')
}

export function postAssistantTask(title) {
  return sendJson('/api/assistant/tasks', 'POST', { title })
}

export function patchAssistantTask(taskId, status) {
  return sendJson(`/api/assistant/tasks/${encodeURIComponent(taskId)}`, 'PATCH', { status })
}

// CALCMATE-STREAMLIT-REMAINING-MIGRATION-AI-WORKSPACE-02 — AI Workspace(/api/workspace/*, require_admin).
// context는 선택값(file/repo/structure)만 보내며 서버가 만든다. 대화 기록은 서버에 저장되지 않는다.
export function getWorkspaceModels() {
  return getJsonAuth('/api/workspace/models')
}

export function getWorkspaceContextFiles() {
  return getJsonAuth('/api/workspace/context/files')
}

export function postWorkspaceChat(role, messages, context) {
  return sendJson('/api/workspace/chat', 'POST', { role, messages, context })
}

export function postWorkspaceSandbox(name, content, overwrite = false) {
  return sendJson('/api/workspace/files/sandbox', 'POST', { name, content, overwrite })
}

export function postWorkspaceFilePreview(path, content) {
  return sendJson('/api/workspace/files/preview', 'POST', { path, content })
}

export function postWorkspaceFileWrite(path, content, expectedOldSha256) {
  return sendJson('/api/workspace/files/write', 'POST', { path, content, expected_old_sha256: expectedOldSha256 })
}

export function postWorkspaceFileCreate(path, content) {
  return sendJson('/api/workspace/files/create', 'POST', { path, content })
}

// CALCMATE-STREAMLIT-REMAINING-MIGRATION-GAP-01-03-IMPLEMENT-01 — 전부 require_admin.
// GAP-01 상태토글: status는 'active' | 'inactive'만(서버 재검증).
export function postCalculatorStatus(slug, status) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/status`, 'POST', { status })
}

// GAP-02 삭제: prepare(서버가 1회용 토큰·삭제 범위 발급) → confirm(토큰 + slug 재입력).
export function postCalculatorDeletePrepare(slug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/delete/prepare`, 'POST')
}

export function postCalculatorDeleteConfirm(slug, token, confirmSlug) {
  return sendJson(`/api/calculators/${encodeURIComponent(slug)}/delete/confirm`, 'POST', { token, confirm_slug: confirmSlug })
}

// GAP-03 전체 정적 사이트 재빌드(_site 전체). Build만 하며 push/deploy는 하지 않는다.
export function postSiteRebuild(slug) {
  return sendJson('/api/sites/rebuild', 'POST', { slug })
}
