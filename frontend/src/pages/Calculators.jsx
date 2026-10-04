import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import CalculatorCard from '../components/CalculatorCard.jsx'
import AppFactoryAiAssist from '../components/AppFactoryAiAssist.jsx'
import SitePagesDeployPanel from '../components/SitePagesDeployPanel.jsx'
import {
  getCalculators,
  getCurrentUser,
  postCalculatorGenerate,
  getCalculatorGenerationJob,
  postContractSlugCheck,
  postContractFormulaValidate,
  postContractGenerate,
  getContractGenerationJob,
  postContractSave,
  getContractPrefill,
  getContractInstance,
  postCalculatorPreviewGenerate,
  postCalculatorPreviewSave,
  postCalculatorPreviewDiscard,
  postAiSuggestSpec,
  postAiSuggestFormula,
  postContractSlugSuggest,
  postContractConfirmFormula,
} from '../api/client.js'

const GENERATE_POLL_INTERVAL_MS = 1500
const GENERATE_POLL_MAX_ATTEMPTS = 40 // 약 60초

// STEP 4-H-6: Calculator 생성(Mode A) 최소 UI. POST /api/calculators/generate →
// GET /api/calculators/generate/{job_id} 폴링까지만 담당한다. 진행률 %/취소/
// 대기열는 만들지 않는다 — Job 모델에 없는 정보는 표시하지 않는다.
// P0-5: 이 함수 본문(Mode A 폼/상태/제출 로직)은 전혀 변경하지 않았다 — 위에
// genMode 선택 라디오만 추가하고, Mode B는 완전히 별도의 ContractModePanel로
// 분리해 Mode A의 기존 동작/테스트에 영향을 주지 않는다.
export function GenerateCalculatorPanel({ onGenerated, pollIntervalMs = GENERATE_POLL_INTERVAL_MS, pollMaxAttempts = GENERATE_POLL_MAX_ATTEMPTS }) {
  const [genMode, setGenMode] = useState('A')
  const [user, setUser] = useState(null)
  const [loadingUser, setLoadingUser] = useState(true)
  const [name, setName] = useState('')
  const [category, setCategory] = useState('')
  const [description, setDescription] = useState('')
  const [tier, setTier] = useState(2)
  const [submitting, setSubmitting] = useState(false)
  const [status, setStatus] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [busyMessage, setBusyMessage] = useState(null)
  const [timedOut, setTimedOut] = useState(false)
  const pollTimer = useRef(null)
  // APP-FACTORY-02: dashboard.py는 기본 정보(이름/카테고리/설명/Tier)와 Tier2-B 신호를
  // 한 화면에서 공유한다 — 생성 방식을 바꿔도 값이 이어지도록 공유 ref에 보관한다.
  const shared = useRef({ name: '', category: '', description: '', tierInt: 2, tier2b: false })

  function switchMode(next) {
    if (genMode === 'A') shared.current = { ...shared.current, name, category, description, tierInt: tier }
    if (next === 'A') {
      setName(shared.current.name)
      setCategory(shared.current.category)
      setDescription(shared.current.description)
      setTier(shared.current.tierInt)
    }
    setGenMode(next)
  }

  useEffect(() => {
    getCurrentUser().then((u) => {
      setUser(u)
      setLoadingUser(false)
    })
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current)
    }
  }, [])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  const modeSelector = (
    <div className="form-row" role="radiogroup" aria-label="생성 방식">
      <label className="form-label">
        <input type="radio" name="gen-mode" value="A" checked={genMode === 'A'}
               onChange={() => switchMode('A')} /> Mode A — 🏭 자동 생성
      </label>
      <label className="form-label">
        <input type="radio" name="gen-mode" value="B" checked={genMode === 'B'}
               onChange={() => switchMode('B')} /> Mode B — 📋 Contract 검증
      </label>
      <label className="form-label">
        <input type="radio" name="gen-mode" value="AP" checked={genMode === 'AP'}
               onChange={() => switchMode('AP')} /> 🔍 생성 후 검토·저장
      </label>
    </div>
  )

  if (!loadingUser && genMode === 'AP') {
    return (
      <div className="status-card">
        <h3 className="status-card__title">계산기 생성</h3>
        {modeSelector}
        <ModeAPreviewPanel isAdmin={isAdmin} onGenerated={onGenerated} shared={shared}
                           pollIntervalMs={pollIntervalMs} pollMaxAttempts={pollMaxAttempts} />
      </div>
    )
  }

  if (!loadingUser && genMode === 'B') {
    return (
      <div className="status-card">
        <h3 className="status-card__title">계산기 생성</h3>
        {modeSelector}
        <ContractModePanel isAdmin={isAdmin} onGenerated={onGenerated} shared={shared} />
      </div>
    )
  }

  async function pollJob(jobId, attempt) {
    if (attempt >= pollMaxAttempts) {
      setTimedOut(true)
      setStatus(null)
      setSubmitting(false)
      return
    }
    const res = await getCalculatorGenerationJob(jobId)
    if (!res.success) {
      setError(res.error?.message || '작업 상태 조회 실패')
      setStatus('failed')
      setSubmitting(false)
      return
    }
    const job = res.data
    setStatus(job.status)
    if (job.status === 'succeeded') {
      setResult(job.result)
      setSubmitting(false)
      onGenerated?.()
      return
    }
    if (job.status === 'failed') {
      setError(job.error || '생성 실패')
      setSubmitting(false)
      return
    }
    // queued | running → 계속 폴링(무한 반복 금지 — pollMaxAttempts로 상한)
    pollTimer.current = setTimeout(() => pollJob(jobId, attempt + 1), pollIntervalMs)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (submitting || !name.trim()) return
    setSubmitting(true)
    setError(null)
    setBusyMessage(null)
    setResult(null)
    setTimedOut(false)
    setStatus(null)

    const { status: httpStatus, body } = await postCalculatorGenerate({
      name: name.trim(),
      category,
      description,
      tier,
    })

    if (httpStatus === 409) {
      setBusyMessage('현재 다른 계산기 생성 작업이 진행 중입니다.')
      setSubmitting(false)
      return
    }
    if (httpStatus !== 200 || !body?.success) {
      setError(body?.error?.message || body?.detail || '생성 요청 실패')
      setSubmitting(false)
      return
    }

    setStatus(body.data.status)
    pollJob(body.data.job_id, 0)
  }

  if (loadingUser) return null

  const isBusy = status === 'queued' || status === 'running'

  return (
    <div className="status-card">
      <h3 className="status-card__title">🏭 새 계산기 생성 (Mode A)</h3>
      {modeSelector}
      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다 — 생성을 시작할 수 있습니다.'
          : '조회만 가능합니다. 생성하려면 admin 권한이 필요합니다.'}
      </p>
      <form onSubmit={handleSubmit}>
        <div className="form-row">
          <label className="form-label" htmlFor="gen-name">계산기명 *</label>
          <input
            id="gen-name"
            className="form-search"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={!isAdmin || submitting}
            placeholder="예: 퇴직금 계산기"
          />
        </div>
        <div className="form-row">
          <label className="form-label" htmlFor="gen-category">카테고리</label>
          <input
            id="gen-category"
            className="form-search"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            disabled={!isAdmin || submitting}
            placeholder="예: 노무/급여"
          />
        </div>
        <div className="form-row">
          <label className="form-label" htmlFor="gen-desc">설명</label>
          <input
            id="gen-desc"
            className="form-search"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={!isAdmin || submitting}
            placeholder="예: 근속연수와 평균임금으로 퇴직금 계산"
          />
        </div>
        <AppFactoryAiAssist isAdmin={isAdmin} disabled={submitting} name={name} category={category}
                            description={description} tierInt={tier}
                            onIdea={(i) => { setName(i.name || ''); setCategory(i.category || ''); setDescription(i.desc || '') }}
                            onTierSuggested={(r) => { setTier(r.tier_int); shared.current.tier2b = Boolean(r.tier2b_suggested) }} />
        <div className="form-row">
          <label className="form-label" htmlFor="gen-tier">Tier</label>
          <select
            id="gen-tier"
            className="form-select"
            value={tier}
            onChange={(e) => setTier(Number(e.target.value))}
            disabled={!isAdmin || submitting}
          >
            <option value={2}>Tier2 — 단순 산술/일반 공식</option>
            <option value={1}>Tier1 — 법령/조건분기/복잡 계산</option>
          </select>
        </div>
        <div className="form-actions">
          <button type="submit" className="refresh-btn" disabled={!isAdmin || submitting || !name.trim()}>
            {submitting ? (isBusy ? `생성 중... (${status})` : '요청 중...') : '🏭 생성 시작'}
          </button>
        </div>
      </form>
      {busyMessage && <p className="status-card__error">⚠ {busyMessage}</p>}
      {timedOut && <p className="status-card__error">⚠ 작업 상태 확인 시간이 초과되었습니다.</p>}
      {error && <p className="status-card__error">⚠ {error}</p>}
      {result && (
        <div>
          <p className="status-card__success">✅ 생성 완료</p>
          <dl className="kv-list">
            <div className="kv-list__row">
              <dt>slug</dt>
              <dd className="kv-list__value">{result.slug}</dd>
            </div>
            <div className="kv-list__row">
              <dt>name</dt>
              <dd className="kv-list__value">{result.name}</dd>
            </div>
            <div className="kv-list__row">
              <dt>message</dt>
              <dd className="kv-list__value">{result.message}</dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  )
}

// SMALL-GAPS-02: Mode A "생성 후 검토·저장" — dashboard.py "🏭 자동 생성"의
// 생성 → 결과 검토 → slug 자동 채움/중복 확인 → 저장 또는 폐기 흐름. 위 Mode A
// (POST /generate, 생성+저장 일괄)는 그대로 두고 별도 옵션으로 제공한다.
// 저장 시 서버가 Formula Hard Gate / HTML 완결성 / slug 형식·중복을 다시 확인한다
// (원본은 formula 검증 실패 시 경고 후 저장 가능 — FastAPI는 저장을 차단한다).
const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]*$/

export function ModeAPreviewPanel({ isAdmin, onGenerated, shared, pollIntervalMs = GENERATE_POLL_INTERVAL_MS, pollMaxAttempts = GENERATE_POLL_MAX_ATTEMPTS }) {
  const [name, setName] = useState(shared?.current?.name || '')
  const [category, setCategory] = useState(shared?.current?.category || '')
  const [description, setDescription] = useState(shared?.current?.description || '')
  const [tier, setTier] = useState(shared?.current?.tierInt || 2)
  useEffect(() => {
    if (shared) shared.current = { ...shared.current, name, category, description, tierInt: tier }
  }, [shared, name, category, description, tier])
  const [submitting, setSubmitting] = useState(false)
  const [status, setStatus] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [preview, setPreview] = useState(null)
  const [error, setError] = useState(null)
  const [busyMessage, setBusyMessage] = useState(null)
  const [slug, setSlug] = useState('')
  const [slugCheck, setSlugCheck] = useState(null) // {conflict, message}
  const [saving, setSaving] = useState(false)
  const [saveResult, setSaveResult] = useState(null) // {ok, message}
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const pollTimer = useRef(null)

  useEffect(() => () => { if (pollTimer.current) clearTimeout(pollTimer.current) }, [])

  async function checkSlug(value) {
    const s = (value || '').trim().toLowerCase()
    if (!SLUG_PATTERN.test(s)) {
      setSlugCheck({ conflict: null, message: '영문 소문자·숫자·하이픈만 사용 가능합니다.' })
      return
    }
    const res = await postContractSlugCheck(s)
    setSlugCheck(res.success ? res.data : { conflict: null, message: res.error?.message || '확인 실패' })
  }

  function resetAll() {
    setJobId(null)
    setPreview(null)
    setStatus(null)
    setSlug('')
    setSlugCheck(null)
    setConfirmDiscard(false)
    setError(null)
  }

  async function pollJob(id, attempt) {
    if (attempt >= pollMaxAttempts) {
      setError('작업 상태 확인 시간이 초과되었습니다.')
      setSubmitting(false)
      return
    }
    const res = await getCalculatorGenerationJob(id)
    if (!res.success) {
      setError(res.error?.message || '작업 상태 조회 실패')
      setSubmitting(false)
      return
    }
    const job = res.data
    setStatus(job.status)
    if (job.status === 'succeeded') {
      setPreview(job.result)
      setSlug(job.result?.suggested_slug || '')
      setSubmitting(false)
      if (job.result?.suggested_slug) checkSlug(job.result.suggested_slug)
      return
    }
    if (job.status === 'failed') {
      setError(job.error || '생성 실패')
      setSubmitting(false)
      return
    }
    pollTimer.current = setTimeout(() => pollJob(id, attempt + 1), pollIntervalMs)
  }

  async function handleGenerate(e) {
    e.preventDefault()
    if (submitting || !name.trim()) return
    resetAll()
    setSaveResult(null)
    setBusyMessage(null)
    setSubmitting(true)
    const { status: httpStatus, body } = await postCalculatorPreviewGenerate({
      name: name.trim(), category, description, tier,
    })
    if (httpStatus === 409) {
      setBusyMessage('현재 다른 계산기 생성 작업이 진행 중입니다.')
      setSubmitting(false)
      return
    }
    if (httpStatus !== 200 || !body?.success) {
      setError(body?.error?.message || body?.detail || '생성 요청 실패')
      setSubmitting(false)
      return
    }
    setJobId(body.data.job_id)
    setStatus(body.data.status)
    pollJob(body.data.job_id, 0)
  }

  async function handleSave() {
    if (!jobId || saving) return
    setSaving(true)
    setSaveResult(null)
    const res = await postCalculatorPreviewSave(jobId, slug.trim().toLowerCase())
    setSaving(false)
    if (res?.success && res.data?.ok) {
      setSaveResult({ ok: true, message: res.data.message })
      resetAll()
      onGenerated?.()
    } else if (res?.success) {
      setSaveResult({ ok: false, message: res.data?.blocked_reason || '저장이 차단되었습니다.' })
    } else {
      setSaveResult({ ok: false, message: res?.error?.message || (res?.detail ? 'slug 형식을 확인하세요.' : '저장 요청 실패') })
    }
  }

  async function handleDiscard() {
    if (!jobId) return
    const res = await postCalculatorPreviewDiscard(jobId)
    if (res?.success) {
      resetAll()
      setSaveResult(null)
    } else {
      setError(res?.error?.message || '폐기 요청 실패')
      setConfirmDiscard(false)
    }
  }

  const isBusy = status === 'queued' || status === 'running'
  const slugValid = SLUG_PATTERN.test(slug.trim().toLowerCase())
  const saveDisabled = !isAdmin || saving || !slugValid || slugCheck?.conflict === true
    || preview?.formula_valid === false || preview?.html_complete === false

  return (
    <div>
      <p className="status-card__hint">
        AI 생성 결과를 먼저 검토한 뒤 저장하거나 폐기합니다. 검토 단계에서는 아무것도 저장되지 않습니다.
      </p>
      {!preview && (
        <form onSubmit={handleGenerate}>
          <div className="form-row">
            <label className="form-label" htmlFor="ap-name">계산기명 *</label>
            <input id="ap-name" className="form-search" value={name} onChange={(e) => setName(e.target.value)}
                   disabled={!isAdmin || submitting} placeholder="예: 퇴직금 계산기" />
          </div>
          <div className="form-row">
            <label className="form-label" htmlFor="ap-category">카테고리</label>
            <input id="ap-category" className="form-search" value={category}
                   onChange={(e) => setCategory(e.target.value)} disabled={!isAdmin || submitting} />
          </div>
          <div className="form-row">
            <label className="form-label" htmlFor="ap-desc">설명</label>
            <input id="ap-desc" className="form-search" value={description}
                   onChange={(e) => setDescription(e.target.value)} disabled={!isAdmin || submitting} />
          </div>
          <AppFactoryAiAssist isAdmin={isAdmin} disabled={submitting} name={name} category={category}
                              description={description} tierInt={tier}
                              onIdea={(i) => { setName(i.name || ''); setCategory(i.category || ''); setDescription(i.desc || '') }}
                              onTierSuggested={(r) => { setTier(r.tier_int); if (shared) shared.current.tier2b = Boolean(r.tier2b_suggested) }} />
          <div className="form-row">
            <label className="form-label" htmlFor="ap-tier">Tier</label>
            <select id="ap-tier" className="form-select" value={tier}
                    onChange={(e) => setTier(Number(e.target.value))} disabled={!isAdmin || submitting}>
              <option value={2}>Tier2 — 단순 산술/일반 공식</option>
              <option value={1}>Tier1 — 법령/조건분기/복잡 계산</option>
            </select>
          </div>
          <div className="form-actions">
            <button type="submit" className="refresh-btn" disabled={!isAdmin || submitting || !name.trim()}>
              {submitting ? (isBusy ? `생성 중... (${status})` : '요청 중...') : '🔍 미리보기 생성'}
            </button>
          </div>
        </form>
      )}
      {busyMessage && <p className="status-card__error">⚠ {busyMessage}</p>}
      {error && <p className="status-card__error">⚠ {error}</p>}
      {saveResult && (
        <p className={saveResult.ok ? 'status-card__success' : 'status-card__error'}>
          {saveResult.ok ? '✅' : '⚠'} {saveResult.message}
        </p>
      )}

      {preview && (
        <div data-testid="mode-a-preview">
          <p className="status-card__success">
            생성 완료 — 토큰 {preview.tokens ?? '-'} | {preview.tier === 1 ? 'Tier1 (복잡)' : 'Tier2 (단순)'}
          </p>
          {preview.formula_valid === false && (
            <p className="status-card__error">⚠ 수식 검증 실패: {preview.formula_msg} — 저장이 차단됩니다.</p>
          )}
          {preview.html_complete === false && (
            <p className="status-card__error">⚠ HTML/JS 완결성 검사 실패: {preview.html_msg} — 저장이 차단됩니다.</p>
          )}
          <dl className="kv-list">
            <div className="kv-list__row"><dt>SEO 제목</dt><dd className="kv-list__value">{preview.seo_title || '-'}</dd></div>
            <div className="kv-list__row"><dt>계산기 유형</dt><dd className="kv-list__value">{preview.calculator_type || '-'}</dd></div>
            <div className="kv-list__row"><dt>HTML 길이</dt><dd className="kv-list__value">{preview.html_length}</dd></div>
            <div className="kv-list__row"><dt>FAQ 수</dt><dd className="kv-list__value">{Array.isArray(preview.faq) ? preview.faq.length : 0}</dd></div>
            <div className="kv-list__row">
              <dt>formula</dt>
              <dd className="kv-list__value">
                <code>{typeof preview.formula === 'string' ? preview.formula : JSON.stringify(preview.formula)}</code>
              </dd>
            </div>
          </dl>
          <details>
            <summary>입력/출력 스키마</summary>
            <pre>{JSON.stringify({ input: preview.input_schema, output: preview.output_schema }, null, 2)}</pre>
          </details>
          <details>
            <summary>HTML 코드</summary>
            <pre>{(preview.html || '').slice(0, 4000)}</pre>
          </details>
          <details>
            <summary>FAQ / 블로그 초안</summary>
            <pre>{JSON.stringify(preview.faq, null, 2)}</pre>
            <pre>{preview.blog_draft || ''}</pre>
          </details>
          {preview.html && (
            <details>
              <summary>🔎 실제 렌더 미리보기</summary>
              <iframe title="계산기 렌더 미리보기" sandbox="allow-scripts" srcDoc={preview.html}
                      style={{ width: '100%', height: 420, border: 0 }} />
            </details>
          )}

          <div className="form-row">
            <label className="form-label" htmlFor="ap-slug">영문 slug * (저장 후 변경 불가)</label>
            <input id="ap-slug" className="form-search" value={slug} disabled={!isAdmin || saving}
                   onChange={(e) => { setSlug(e.target.value); setSlugCheck(null) }} />
            <button type="button" className="refresh-btn" disabled={!isAdmin || !slug.trim()}
                    onClick={() => checkSlug(slug)}>🔍 slug 중복 확인</button>
          </div>
          {slugCheck && (
            <p className={slugCheck.conflict === false ? 'status-card__success' : 'status-card__error'}>
              {slugCheck.conflict === false ? '✅ 슬러그 사용 가능' : slugCheck.conflict ? '⛔ 슬러그 중복' : '⚠'}: {slugCheck.message}
            </p>
          )}

          <div className="form-actions">
            <button type="button" className="refresh-btn" disabled={saveDisabled} onClick={handleSave}>
              {saving ? '저장 중...' : '💾 calculators + app_templates 저장'}
            </button>
            <button type="button" className="refresh-btn" disabled={!isAdmin || saving}
                    onClick={() => setConfirmDiscard(true)}>🗑️ 생성 결과 폐기 & 초기화</button>
          </div>
          {confirmDiscard && (
            <div>
              <p className="status-card__error">
                ⚠ 현재 생성된 계산기 결과를 폐기하고 입력 화면을 초기화합니다. 저장하지 않은 생성 결과가 사라집니다.
              </p>
              <div className="form-actions">
                <button type="button" className="refresh-btn" onClick={handleDiscard}>⚠️ 폐기하고 초기화</button>
                <button type="button" className="refresh-btn" onClick={() => setConfirmDiscard(false)}>취소</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// dashboard.py L2392-2397 Formula 상태 배지(+ 서버 상태 formula_invalid).
const FORMULA_STATUS_BADGE = {
  not_generated: '⚪ Formula 미생성',
  ai_suggested: '🔵 AI 제안',
  pending_validation: '🟡 검증 대기',
  operator_confirmed: '🟢 운영자 확정',
  formula_invalid: '🔴 검증 실패',
}

const CONTRACT_POLL_INTERVAL_MS = 1500
const CONTRACT_POLL_MAX_ATTEMPTS = 40 // 약 60초

function parseCsvFields(text) {
  return text.split(',').map((s) => s.trim()).filter(Boolean)
}

function parseJsonOrRaw(text) {
  const raw = text.trim()
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return raw
  }
}

function parseJsonArray(text) {
  const raw = text.trim()
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

// P0-5: Mode B(Contract 기반 생성). dashboard.py "📋 Contract 확정 스펙 입력" +
// "📋 Contract 기반 생성" 버튼과 동일한 backend(build_contract/check_hold_rules/
// generate_app_with_contract/validate_formula_with_samples/save_app)를 호출한다.
// 새로운 저장 방식/파이프라인을 만들지 않는다 — 서버가 이미 강제하는 게이트
// (formula_status==operator_confirmed, contract_validation.valid)를 그대로 반영한다.
function ContractModePanel({ isAdmin, onGenerated, shared }) {
  const [name, setName] = useState(shared?.current?.name || '')
  const [category, setCategory] = useState(shared?.current?.category || '')
  const [description, setDescription] = useState(shared?.current?.description || '')
  // APP-FACTORY-02: dashboard.py와 같이 Tier2-B 신호(AI 추천)가 있으면 Tier2-B로,
  // 아니면 공유 Tier(1 → Tier1, 2 → Tier2-A)로 시작한다.
  const [tier, setTier] = useState(
    shared?.current?.tier2b ? 'Tier2-B' : (shared?.current?.tierInt === 1 ? 'Tier1' : 'Tier2-A'))
  const [slug, setSlug] = useState('')
  const [inputFieldsText, setInputFieldsText] = useState('')
  const [outputFieldsText, setOutputFieldsText] = useState('')
  const [formulaText, setFormulaText] = useState('')
  const [testCasesText, setTestCasesText] = useState('')
  // STEP S2: legal_refs/scope_exclusions는 dashboard.py에서도 자유 텍스트 입력이 아니라
  // Registry prefill/Contract Instance 복원으로만 채워지는 read-only 표시 필드다
  // (dashboard.py:2317-2323 — "🚫 scope_exclusions 표시(read-only)"). 서버가 이미
  // 결정한 안전 정보이므로 여기서도 직접 입력 UI를 만들지 않고 그대로 표시/전달만 한다.
  const [legalRefs, setLegalRefs] = useState([])
  const [scopeExclusions, setScopeExclusions] = useState([])

  const [slugChecking, setSlugChecking] = useState(false)
  const [slugCheckResult, setSlugCheckResult] = useState(null)

  const [prefillLoading, setPrefillLoading] = useState(false)
  const [prefillError, setPrefillError] = useState(null)
  const [prefillInfo, setPrefillInfo] = useState(null)

  const [instanceLoading, setInstanceLoading] = useState(false)
  const [instanceError, setInstanceError] = useState(null)
  const [instanceInfo, setInstanceInfo] = useState(null)

  const [validating, setValidating] = useState(false)
  const [validation, setValidation] = useState(null)

  const [submitting, setSubmitting] = useState(false)
  const [jobStatus, setJobStatus] = useState(null)
  const [genResult, setGenResult] = useState(null)
  const [genError, setGenError] = useState(null)
  const [busyMessage, setBusyMessage] = useState(null)
  const pollTimer = useRef(null)

  const [saving, setSaving] = useState(false)
  const [saveResult, setSaveResult] = useState(null)

  // APP-FACTORY-02: 필드/Formula AI 제안 · Formula 운영자 확정
  const [specLoading, setSpecLoading] = useState(false)
  const [specMsg, setSpecMsg] = useState(null)          // {kind: 'success'|'warning', text}
  const [pendingSpec, setPendingSpec] = useState(null)  // 기존 값이 있어 적용하지 않은 제안
  const [formulaAiLoading, setFormulaAiLoading] = useState(false)
  const [formulaAiArmed, setFormulaAiArmed] = useState(false)   // 기존 formula 교체 2단계
  const [formulaAiMsg, setFormulaAiMsg] = useState(null)        // {kind, text, warnings}
  const [aiSuggestedText, setAiSuggestedText] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [confirmMsg, setConfirmMsg] = useState(null)            // {ok, text, validation}

  useEffect(() => () => { if (pollTimer.current) clearTimeout(pollTimer.current) }, [])

  useEffect(() => {
    if (shared) {
      shared.current = {
        ...shared.current, name, category, description,
        tierInt: tier === 'Tier1' ? 1 : 2, tier2b: tier === 'Tier2-B',
      }
    }
  }, [shared, name, category, description, tier])

  // dashboard.py L2106-2109: 계산기명이 있고 확정 slug가 비어 있을 때만 generate_slug()로
  // 자동 제안한다. 한 번이라도 값이 들어가면(자동/직접) 덮어쓰지 않는다.
  useEffect(() => {
    if (!isAdmin || !name.trim() || slug.trim()) return undefined
    let alive = true
    const timer = setTimeout(() => {
      postContractSlugSuggest(name.trim()).then((res) => {
        if (alive && res?.success && res.data?.slug) {
          setSlug((prev) => (prev.trim() ? prev : res.data.slug))
        }
      })
    }, 400)
    return () => { alive = false; clearTimeout(timer) }
  }, [isAdmin, name, slug])

  // dashboard.py "💡 필드 자동 제안"(L2219-2262). 빈 입력란만 채우고, 이미 값이 있는
  // 입력란은 덮어쓰지 않은 채 제안값을 보여 주며 [제안값으로 교체]로만 바꾼다.
  async function handleSuggestSpec() {
    if (!name.trim()) {
      setSpecMsg({ kind: 'warning', text: '⚠️ 필드 자동 제안을 사용하려면 먼저 [계산기명]을 입력하세요.' })
      return
    }
    setSpecLoading(true)
    setSpecMsg(null)
    setPendingSpec(null)
    const res = await postAiSuggestSpec({ name: name.trim(), category, description, tier })
    setSpecLoading(false)
    if (!res?.success) {
      setSpecMsg({ kind: 'warning', text: `⚠️ ${res?.error?.message || '필드 자동 제안에 실패했습니다. 기존 입력값은 유지됩니다.'}` })
      return
    }
    const s = res.data
    const inText = (s.input_fields || []).join(', ')
    const outText = (s.output_fields || []).join(', ')
    if (!inText && !outText) {
      setSpecMsg({ kind: 'warning', text: '⚠️ AI가 유효한 필드를 제안하지 못했습니다. 기존 입력값은 유지됩니다.' })
      return
    }
    const pending = {}
    if (inText) { if (inputFieldsText.trim()) pending.input = inText; else setInputFieldsText(inText) }
    if (outText) { if (outputFieldsText.trim()) pending.output = outText; else setOutputFieldsText(outText) }
    if (s.formula) { if (formulaText.trim()) pending.formula = s.formula; else setFormulaText(s.formula) }
    const kept = Object.keys(pending).length > 0
    setPendingSpec(kept ? pending : null)
    const labels = Object.entries(s.labels || {}).slice(0, 5).map(([k, v]) => `${k}=${v}`).join(', ')
    setSpecMsg({
      kind: 'success',
      text: `✅ AI 필드 제안 — input ${s.input_fields.length}개 / output ${s.output_fields.length}개`
        + `${s.formula ? ' / formula 포함' : ''}${labels ? ` (${labels})` : ''}`
        + (kept ? ' · 이미 값이 있는 항목은 유지했습니다(아래에서 교체 가능).' : ' · 필요하면 직접 수정하세요.'),
    })
  }

  function applyPendingSpec() {
    if (!pendingSpec) return
    if (pendingSpec.input) setInputFieldsText(pendingSpec.input)
    if (pendingSpec.output) setOutputFieldsText(pendingSpec.output)
    if (pendingSpec.formula) { setFormulaText(pendingSpec.formula); setAiSuggestedText(null) }
    setPendingSpec(null)
  }

  // dashboard.py "🤖 AI Formula 제안"(L2318-2376): 기존 formula가 있으면 첫 클릭은 경고만,
  // 다시 클릭하면 AI 제안으로 교체한다. 제안은 확정이 아니다(검증 → 확정 필요).
  async function handleSuggestFormula() {
    if (formulaText.trim() && !formulaAiArmed) {
      setFormulaAiArmed(true)
      setFormulaAiMsg({ kind: 'warning', text: '⚠️ 기존 Formula가 있습니다. 다시 클릭하면 AI 제안으로 교체됩니다.', warnings: [] })
      return
    }
    setFormulaAiArmed(false)
    setFormulaAiLoading(true)
    setFormulaAiMsg(null)
    const res = await postAiSuggestFormula({
      name: name.trim(), category, description,
      input_fields: parseCsvFields(inputFieldsText), output_fields: parseCsvFields(outputFieldsText),
      legal_refs: legalRefs, slug: slug.trim() || null,
    })
    setFormulaAiLoading(false)
    const d = res?.success ? res.data : null
    if (d?.success) {
      setFormulaText(d.formula)
      setAiSuggestedText(d.formula)
      setValidation(null)
      setFormulaAiMsg({ kind: 'success', text: 'AI Formula 제안 완료. 반드시 검토 후 [🔍 Formula 검증]을 실행하세요.', warnings: d.warnings || [] })
    } else {
      setFormulaAiMsg({ kind: 'error', text: `❌ AI Formula 제안 실패: ${d?.reason || res?.error?.message || '요청 실패'}`, warnings: d?.warnings || [] })
    }
  }

  function handleFormulaChange(value) {
    setFormulaText(value)
    setFormulaAiArmed(false)
    if (aiSuggestedText !== null && value.trim() !== aiSuggestedText) setAiSuggestedText(null)  // CA-3-1
  }

  // dashboard.py "✅ Formula 확정"(L2466-2476). 서버가 job의 Contract formula를 다시
  // 검증한 뒤 operator_confirmed 여부를 결정한다 — 화면은 확정 요청만 보낸다.
  async function handleConfirmFormula() {
    if (!genResult?.jobId || confirming) return
    setConfirming(true)
    setConfirmMsg(null)
    const res = await postContractConfirmFormula(genResult.jobId)
    if (!res?.success) {
      setConfirming(false)
      setConfirmMsg({ ok: false, text: res?.error?.message || 'Formula 확정 요청 실패' })
      return
    }
    const d = res.data
    if (d.ok) {
      const job = await getContractGenerationJob(genResult.jobId)
      if (job?.success && job.data?.result) setGenResult({ jobId: genResult.jobId, ...job.data.result })
    }
    setConfirming(false)
    setConfirmMsg({ ok: Boolean(d.ok), text: d.message, validation: d.validation })
  }

  async function handleSlugCheck() {
    if (!slug.trim()) return
    setSlugChecking(true)
    setSlugCheckResult(null)
    const res = await postContractSlugCheck(slug.trim().toLowerCase())
    setSlugChecking(false)
    setSlugCheckResult(res.success ? res.data : { conflict: null, message: res.error?.message || '확인 실패' })
  }

  // STEP S2: dashboard.py "📥 Registry에서 불러오기" 버튼과 동일 — 이미 존재하는
  // 계산기(Registry v3 등록분)의 slug로 input/output/scope_exclusions/legal_refs를
  // 서버가 실제로 갖고 있는 값 그대로 불러온다. 프리필은 backend가 반환한 값만
  // 사용하며(추측 없음), found=False(Registry에 없음)는 오류가 아니라 정상 상태다.
  async function handlePrefill() {
    if (!slug.trim()) return
    setPrefillLoading(true)
    setPrefillError(null)
    setPrefillInfo(null)
    const res = await getContractPrefill(slug.trim().toLowerCase())
    setPrefillLoading(false)
    if (!res.success) {
      setPrefillError(res.error?.message || 'Registry 프리필 조회 실패')
      return
    }
    const data = res.data
    if (!data.found) {
      setPrefillError(data.message || `Registry v3에 '${slug.trim()}' 엔트리가 없습니다.`)
      return
    }
    if (data.name) setName(data.name)
    if (data.category) setCategory(data.category)
    setInputFieldsText((data.input_fields || []).join(', '))
    setOutputFieldsText((data.output_fields || []).join(', '))
    setLegalRefs(data.legal_refs || [])
    setScopeExclusions(data.scope_exclusions || [])
    setPrefillInfo(`✅ Registry에서 불러옴: input ${data.input_fields.length}개, output ${data.output_fields.length}개, `
      + `legal_refs ${data.legal_refs.length}개, scope_exclusions ${data.scope_exclusions.length}개`)
  }

  // STEP S2: dashboard.py "📂 Contract Instance 불러오기" 버튼과 동일 — 이전에 Mode B로
  // 저장된 Contract instance(formula/test_cases 포함)를 복원한다. instance가 없는 것은
  // 오류가 아니라 정상 상태이며(존재하지 않는 instance를 임의로 생성/저장하지 않는다),
  // legal_refs는 이 endpoint의 응답에 항상 있지는 않다(app_factory.py의 기존 동작 —
  // Registry snapshot 폴백 경로에만 있음) — 없으면 기존 값을 그대로 둔다.
  async function handleInstanceRestore() {
    if (!slug.trim()) return
    setInstanceLoading(true)
    setInstanceError(null)
    setInstanceInfo(null)
    const res = await getContractInstance(slug.trim().toLowerCase())
    setInstanceLoading(false)
    if (!res.success) {
      setInstanceError(res.error?.message || 'Contract Instance 조회 실패')
      return
    }
    const data = res.data
    if (!data.found) {
      setInstanceInfo(`ℹ️ ${data.message || '저장된 Contract instance가 없습니다(정상 — 새로 작성하세요).'}`)
      return
    }
    if (data.name) setName(data.name)
    setInputFieldsText((data.input_fields || []).join(', '))
    setOutputFieldsText((data.output_fields || []).join(', '))
    setScopeExclusions(data.scope_exclusions || [])
    if (Array.isArray(data.legal_refs)) setLegalRefs(data.legal_refs) // 없으면 기존 값 유지
    if (data.formula !== null && data.formula !== undefined) {
      setFormulaText(typeof data.formula === 'string' ? data.formula : JSON.stringify(data.formula))
    }
    if (Array.isArray(data.test_cases) && data.test_cases.length > 0) {
      setTestCasesText(JSON.stringify(data.test_cases))
    }
    setInstanceInfo(`✅ Contract Instance 복원됨(formula_status: ${data.formula_status || 'not_generated'})`
      + (data.message ? ` — ${data.message}` : ''))
  }

  async function handleValidate() {
    const formula = parseJsonOrRaw(formulaText)
    if (!formula) return
    setValidating(true)
    setValidation(null)
    const res = await postContractFormulaValidate(
      formula, parseCsvFields(inputFieldsText), parseJsonArray(testCasesText))
    setValidating(false)
    setValidation(res.success ? res.data : { valid: false, message: res.error?.message || '검증 실패', sample_results: [] })
  }

  async function pollJob(jobId, attempt) {
    if (attempt >= CONTRACT_POLL_MAX_ATTEMPTS) {
      setJobStatus('timeout')
      setSubmitting(false)
      return
    }
    const res = await getContractGenerationJob(jobId)
    if (!res.success) {
      setGenError(res.error?.message || '작업 상태 조회 실패')
      setSubmitting(false)
      return
    }
    const job = res.data
    setJobStatus(job.status)
    if (job.status === 'succeeded') {
      setGenResult({ jobId, ...job.result })
      setSubmitting(false)
      onGenerated?.()
      return
    }
    if (job.status === 'failed') {
      setGenError(job.error || '생성 실패')
      setSubmitting(false)
      return
    }
    pollTimer.current = setTimeout(() => pollJob(jobId, attempt + 1), CONTRACT_POLL_INTERVAL_MS)
  }

  async function handleGenerate(e) {
    e.preventDefault()
    if (submitting || !name.trim() || !slug.trim()) return
    setSubmitting(true)
    setGenError(null)
    setBusyMessage(null)
    setGenResult(null)
    setSaveResult(null)
    setJobStatus(null)

    const { status: httpStatus, body } = await postContractGenerate({
      name: name.trim(), category, description, tier, slug: slug.trim().toLowerCase(),
      input_fields: parseCsvFields(inputFieldsText),
      output_fields: parseCsvFields(outputFieldsText),
      formula: parseJsonOrRaw(formulaText),
      test_cases: parseJsonArray(testCasesText),
      // STEP S2: 더 이상 빈 배열로 하드코딩하지 않는다 — Registry prefill/Contract
      // Instance 복원으로 실제 로드된 값을 그대로 전달한다(사용자가 직접 입력하는
      // 필드가 아니므로 클라이언트가 임의로 값을 만들어내지 않는다). 서버는
      // check_hold_rules()/generate_app_with_contract() 등 기존 검증을 그대로 재검증한다.
      scope_exclusions: scopeExclusions, legal_refs: legalRefs,
    })

    if (httpStatus === 409) {
      setBusyMessage('현재 다른 계산기 생성 작업이 진행 중입니다.')
      setSubmitting(false)
      return
    }
    if (httpStatus !== 200 || !body?.success) {
      setGenError(body?.error?.message || body?.detail || '생성 요청 실패')
      setSubmitting(false)
      return
    }
    setJobStatus(body.data.status)
    pollJob(body.data.job_id, 0)
  }

  async function handleSave() {
    if (!genResult?.jobId || saving) return
    setSaving(true)
    setSaveResult(null)
    const res = await postContractSave(genResult.jobId, genResult.contract?.slug || slug.trim().toLowerCase())
    setSaving(false)
    setSaveResult(res.success ? res.data : { ok: false, blocked_reason: res.error?.message || '저장 요청 실패' })
    if (res.success && res.data?.ok) onGenerated?.()
  }

  const isBusy = jobStatus === 'queued' || jobStatus === 'running'
  const formulaStatus = genResult?.contract?.formula_status
  const contractValid = genResult?.contract_validation?.valid !== false
  const saveBlockedReason = !genResult
    ? null
    : formulaStatus !== 'operator_confirmed'
      ? `🔒 저장하려면 Formula 검증 통과 후 [✅ Formula 확정]이 필요합니다. 현재 상태: ${formulaStatus}`
      : !contractValid
        ? '⛔ Contract 불일치(slug/schema/formula)로 저장이 차단됩니다.'
        : null

  return (
    <div>
      <p className="status-card__hint">
        법령·취업규칙 등으로 필드명·수식이 이미 확정된 계산기에만 사용하세요.
        Contract는 AI 호출 전에 확정되어야 하며, Formula 검증을 통과하고 운영자가 확정해야 저장할 수 있습니다
        (Tier2-B 날짜형은 자동 확정).
      </p>

      <div className="form-row">
        <label className="form-label" htmlFor="c-name">계산기명 *</label>
        <input id="c-name" className="form-search" value={name} onChange={(e) => setName(e.target.value)}
               disabled={!isAdmin || submitting} placeholder="예: 연차 잔여일 계산기" />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="c-category">카테고리</label>
        <input id="c-category" className="form-search" value={category} onChange={(e) => setCategory(e.target.value)}
               disabled={!isAdmin || submitting} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="c-desc">설명</label>
        <input id="c-desc" className="form-search" value={description} onChange={(e) => setDescription(e.target.value)}
               disabled={!isAdmin || submitting} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="c-tier">Tier</label>
        <select id="c-tier" className="form-select" value={tier} onChange={(e) => setTier(e.target.value)}
                disabled={!isAdmin || submitting}>
          <option value="Tier2-A">Tier2-A — 단순 산술/일반 공식</option>
          <option value="Tier1">Tier1 — 법령/조건분기/복잡 계산</option>
          <option value="Tier2-B">Tier2-B — 날짜형(AI 없이 결정적 생성)</option>
        </select>
      </div>
      <AppFactoryAiAssist isAdmin={isAdmin} disabled={submitting} name={name} category={category}
                          description={description} tierInt={tier === 'Tier1' ? 1 : 2}
                          onIdea={(i) => { setName(i.name || ''); setCategory(i.category || ''); setDescription(i.desc || '') }}
                          onTierSuggested={(r) => setTier(r.tier)} />

      <p className="panel-section-title">📋 Contract 확인</p>
      <div className="form-row">
        <label className="form-label" htmlFor="c-slug">확정 slug *</label>
        <input id="c-slug" className="form-search" value={slug}
               onChange={(e) => { setSlug(e.target.value); setSlugCheckResult(null) }}
               disabled={!isAdmin || submitting} placeholder="annual-leave-remaining" />
        <button type="button" className="refresh-btn" disabled={!isAdmin || !slug.trim() || slugChecking}
                onClick={handleSlugCheck}>
          {slugChecking ? '확인 중...' : '슬러그 확인'}
        </button>
      </div>
      {slugCheckResult && (
        slugCheckResult.conflict
          ? <p className="status-card__error">❌ {slugCheckResult.message}</p>
          : <p className="status-card__success">✅ 사용 가능한 슬러그입니다.</p>
      )}

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || !slug.trim() || prefillLoading}
                onClick={handlePrefill}>
          {prefillLoading ? '불러오는 중...' : '📥 Registry에서 불러오기'}
        </button>
        <button type="button" className="refresh-btn" disabled={!isAdmin || !slug.trim() || instanceLoading}
                onClick={handleInstanceRestore}>
          {instanceLoading ? '불러오는 중...' : '📂 Contract Instance 불러오기'}
        </button>
      </div>
      {prefillError && <p className="status-card__error">⚠ {prefillError}</p>}
      {prefillInfo && <p className="status-card__success">{prefillInfo}</p>}
      {instanceError && <p className="status-card__error">⚠ {instanceError}</p>}
      {instanceInfo && <p className="status-card__hint">{instanceInfo}</p>}

      <div className="form-row">
        <label className="form-label" htmlFor="c-input-fields">Input fields (쉼표 구분) *</label>
        <input id="c-input-fields" className="form-search" value={inputFieldsText}
               onChange={(e) => setInputFieldsText(e.target.value)} disabled={!isAdmin || submitting}
               placeholder="years_of_service, used_days" />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="c-output-fields">Output fields (쉼표 구분) *</label>
        <input id="c-output-fields" className="form-search" value={outputFieldsText}
               onChange={(e) => setOutputFieldsText(e.target.value)} disabled={!isAdmin || submitting}
               placeholder="total_days, remaining_days" />
      </div>
      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || submitting || specLoading}
                onClick={handleSuggestSpec}>
          {specLoading ? '제안 중...' : '💡 필드 자동 제안'}
        </button>
      </div>
      {specMsg && <p className={specMsg.kind === 'success' ? 'status-card__success' : 'status-card__error'}>{specMsg.text}</p>}
      {pendingSpec && (
        <div data-testid="pending-spec">
          <ul className="today-list">
            {pendingSpec.input && <li>제안 input: {pendingSpec.input}</li>}
            {pendingSpec.output && <li>제안 output: {pendingSpec.output}</li>}
            {pendingSpec.formula && <li>제안 formula: {pendingSpec.formula}</li>}
          </ul>
          <button type="button" className="refresh-btn" disabled={!isAdmin} onClick={applyPendingSpec}>제안값으로 교체</button>
        </div>
      )}

      {/* STEP S2: dashboard.py와 동일하게 legal_refs/scope_exclusions는 직접 입력이
          아니라 read-only 표시 — Registry prefill/Instance 복원으로만 채워진다. */}
      {(legalRefs.length > 0 || scopeExclusions.length > 0) && (
        <div className="form-row">
          <dl className="kv-list">
            {legalRefs.length > 0 && (
              <div className="kv-list__row">
                <dt>legal_refs</dt>
                <dd className="kv-list__value">{legalRefs.join(', ')}</dd>
              </div>
            )}
            {scopeExclusions.length > 0 && (
              <div className="kv-list__row">
                <dt>scope_exclusions</dt>
                <dd className="kv-list__value">{scopeExclusions.join(' / ')}</dd>
              </div>
            )}
          </dl>
        </div>
      )}

      <p className="panel-section-title">🔍 Formula 검증(샘플 기대값)</p>
      <div className="form-row">
        <label className="form-label" htmlFor="c-formula">Formula (문자열 또는 JSON)</label>
        <textarea id="c-formula" className="form-search" rows={2} value={formulaText}
                  onChange={(e) => handleFormulaChange(e.target.value)} disabled={!isAdmin || submitting}
                  placeholder='{"total_days": "..."}' />
      </div>
      <div className="form-actions">
        <button type="button" className="refresh-btn"
                disabled={!isAdmin || submitting || formulaAiLoading || !inputFieldsText.trim() || !outputFieldsText.trim()}
                onClick={handleSuggestFormula}>
          {formulaAiLoading ? '🤖 제안 중...' : '🤖 AI Formula 제안'}
        </button>
      </div>
      {formulaAiMsg && (
        <div>
          <p className={formulaAiMsg.kind === 'success' ? 'status-card__hint' : 'status-card__error'}>{formulaAiMsg.text}</p>
          {(formulaAiMsg.warnings || []).map((w, i) => <p key={i} className="status-card__error">⚠️ {w}</p>)}
        </div>
      )}
      <p className="status-card__hint" data-testid="formula-input-status">
        Formula 입력 상태: {genResult
          ? (FORMULA_STATUS_BADGE[genResult.contract?.formula_status] || genResult.contract?.formula_status)
          : (aiSuggestedText !== null && formulaText.trim() === aiSuggestedText
            ? FORMULA_STATUS_BADGE.ai_suggested
            : formulaText.trim() ? FORMULA_STATUS_BADGE.pending_validation : FORMULA_STATUS_BADGE.not_generated)}
      </p>
      <div className="form-row">
        <label className="form-label" htmlFor="c-test-cases">테스트 케이스(JSON 배열)</label>
        <textarea id="c-test-cases" className="form-search" rows={2} value={testCasesText}
                  onChange={(e) => setTestCasesText(e.target.value)} disabled={!isAdmin || submitting}
                  placeholder='[{"input": {"years_of_service": 1}, "expected": {"total_days": 15}}]' />
      </div>
      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || !formulaText.trim() || validating}
                onClick={handleValidate}>
          {validating ? '검증 중...' : '🔍 Formula 검증'}
        </button>
      </div>
      {validation && (
        <div>
          <p className={validation.all_samples_pass ? 'status-card__success' : 'status-card__error'}>
            {validation.all_samples_pass ? '✅ 샘플 검증 통과' : `❌ 샘플 검증 실패 — ${validation.message || ''}`}
          </p>
          {Array.isArray(validation.sample_results) && validation.sample_results.length > 0 && (
            <ul className="today-list">
              {validation.sample_results.map((s, i) => (
                <li key={i}>
                  {s.match === true ? '✅' : '❌'} 샘플 {i + 1} — 입력 {JSON.stringify(s.input)} /
                  {' '}예상 {JSON.stringify(s.expected)} / 실제 {JSON.stringify(s.output)}
                  {s.error ? ` (오류: ${s.error})` : ''}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <form onSubmit={handleGenerate}>
        <div className="form-actions">
          <button type="submit" className="refresh-btn" disabled={!isAdmin || submitting || !name.trim() || !slug.trim()}>
            {submitting ? (isBusy ? `생성 중... (${jobStatus})` : '요청 중...') : '📋 Contract 기반 생성'}
          </button>
        </div>
      </form>
      {busyMessage && <p className="status-card__error">⚠ {busyMessage}</p>}
      {jobStatus === 'timeout' && <p className="status-card__error">⚠ 작업 상태 확인 시간이 초과되었습니다.</p>}
      {genError && <p className="status-card__error">⚠ {genError}</p>}

      {genResult && (
        <div>
          <p className="status-card__success">
            생성 완료 — {genResult.formula_valid ? '✅ Formula Hard Gate 통과' : '❌ Formula Hard Gate 실패'}
          </p>
          {!genResult.formula_valid && <p className="status-card__error">{genResult.formula_msg}</p>}
          <p className="status-card__hint">Formula 상태: {formulaStatus}</p>
          {formulaStatus !== 'operator_confirmed' && (
            <div className="form-actions">
              <button type="button" className="refresh-btn" disabled={!isAdmin || confirming} onClick={handleConfirmFormula}>
                {confirming ? '확정 중...' : '✅ Formula 확정'}
              </button>
            </div>
          )}
          {confirmMsg && (
            <div>
              <p className={confirmMsg.ok ? 'status-card__success' : 'status-card__error'}>{confirmMsg.text}</p>
              {confirmMsg.validation && !confirmMsg.ok && (
                <p className="status-card__error">
                  {confirmMsg.validation.valid ? '❌ 기대값 불일치(Level 3)' : `❌ Formula 검증 실패: ${confirmMsg.validation.message || ''}`}
                </p>
              )}
            </div>
          )}

          <p className="panel-section-title">📋 Contract 검증 결과</p>
          <p className={contractValid ? 'status-card__success' : 'status-card__error'}>
            {contractValid ? '✅ Contract 검증 통과 — slug/schema/formula 모두 일치' : '⛔ Contract 불일치 — 저장이 차단됩니다'}
          </p>
          {genResult.post_generation_sample_validation && (
            <ul className="today-list">
              {(genResult.post_generation_sample_validation.sample_results || []).map((s, i) => (
                <li key={i}>
                  {s.match === true ? '✅' : '❌'} 샘플 {i + 1} — 예상 {JSON.stringify(s.expected)} / 실제 {JSON.stringify(s.output)}
                </li>
              ))}
            </ul>
          )}
          {genResult.hold_messages?.length > 0 && (
            <ul className="today-list">
              {genResult.hold_messages.map((m, i) => <li key={i}>⚠️ {m}</li>)}
            </ul>
          )}

          <div className="form-actions">
            <button type="button" className="refresh-btn" primary="true"
                    disabled={!isAdmin || saving || Boolean(saveBlockedReason)}
                    onClick={handleSave}>
              {saving ? '저장 중...' : '💾 calculators + app_templates 저장'}
            </button>
          </div>
          {saveBlockedReason && <p className="status-card__error">{saveBlockedReason}</p>}
          {saveResult && (
            saveResult.ok
              ? <p className="status-card__success">✅ {saveResult.message}</p>
              : <p className="status-card__error">🔒 {saveResult.blocked_reason}</p>
          )}
        </div>
      )}
    </div>
  )
}

// /calculators — 목록 조회 + STEP 4-H-6에서 활성화된 생성(Mode A). 삭제/배포는
// 이번 STEP에서도 만들지 않는다.
export default function Calculators() {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  // STEP V1-OPS-04: Sidebar "계산기 > 생성/관리" 하위탭이 ?new=1로 진입하면
  // 생성 패널을 펼친 상태로 시작한다(기존 토글 동작은 그대로 유지).
  const [searchParams] = useSearchParams()
  const [showGenerate, setShowGenerate] = useState(searchParams.get('new') === '1')

  const load = useCallback(() => {
    setLoading(true)
    getCalculators().then((res) => {
      setResult(res)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const calculators = result?.data?.calculators || []
  const failed = !loading && !result?.success

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return calculators
    return calculators.filter(
      (c) => c.slug.toLowerCase().includes(q) || (c.name || '').toLowerCase().includes(q)
    )
  }, [calculators, query])

  return (
    <div className="page">
      <div className="page__header">
        <h1>🧮 Calculator 관리</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      <div className="form-row">
        <input
          type="search"
          className="form-search"
          placeholder="검색 (slug 또는 이름)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="계산기 검색"
        />
        <button
          type="button"
          className="refresh-btn"
          onClick={() => setShowGenerate((v) => !v)}
          aria-expanded={showGenerate}
        >
          {showGenerate ? '− 닫기' : '+ 새 계산기'}
        </button>
      </div>

      {showGenerate && <GenerateCalculatorPanel onGenerated={load} />}

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && (
        <>
          <p className="status-card__hint">
            총 {calculators.length}개 중 {filtered.length}개 표시
          </p>
          <div className="calc-grid">
            {filtered.map((c) => (
              <CalculatorCard key={c.slug} calc={c} />
            ))}
          </div>
          {filtered.length === 0 && (
            <p className="status-card__hint">검색 결과가 없습니다.</p>
          )}
        </>
      )}

      {/* SITE-PAGE-DEPLOYMENT-02: dashboard.py "🧮 계산기 관리" 탭 하단 "🌐 사이트 페이지 배포" 이관. */}
      <SitePagesDeployPanel />
    </div>
  )
}
