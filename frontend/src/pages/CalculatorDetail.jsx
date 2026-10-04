import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  getCalculator,
  getCalculatorContent,
  getCalculatorStatus,
  getCalculatorFormula,
  patchCalculatorFormula,
  postCalculatorPromote,
  getCalculatorChecklist,
  patchCalculatorChecklist,
  postCalculatorBuild,
  postCalculatorDeploy,
  getCalculatorReview,
  postCalculatorReviewApprove,
  postCalculatorReviewUnapprove,
  getCalculatorPreview,
  postCalculatorContentSeo,
  postCalculatorContentFaq,
  postCalculatorContentBody,
  postCalculatorContentImage,
  postCalculatorContentGenerateAll,
  getCurrentUser,
  postCalculatorStatus,
  postCalculatorDeletePrepare,
  postCalculatorDeleteConfirm,
  postSiteRebuild,
} from '../api/client.js'

function Badge({ value, onLabel = 'ON', offLabel = 'OFF' }) {
  return (
    <span className={`badge ${value ? 'badge--on' : 'badge--off'}`}>
      {value ? onLabel : offLabel}
    </span>
  )
}

// STEP 4-G: Formula 조회/저장 카드. 삭제/배포와 달리 admin이면 실제로 저장 가능하다.
function FormulaCard({ slug }) {
  const [formulaData, setFormulaData] = useState(null)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setFailed(false)
    Promise.all([getCalculatorFormula(slug), getCurrentUser()]).then(([f, u]) => {
      setFormulaData(f)
      setUser(u)
      if (f?.success && f.data) {
        setValue(f.data.formula || '')
      }
      setFailed(!f?.success)
      setLoading(false)
    })
  }, [slug])

  useEffect(() => {
    load()
  }, [load])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  async function handleSave() {
    setSaving(true)
    setSaveMessage(null)
    setSaveError(null)
    const res = await patchCalculatorFormula(slug, value)
    setSaving(false)
    if (res.success) {
      setSaveMessage('수식 저장 완료')
      setValue(res.data.formula || '')
    } else {
      setSaveError(res.error?.message || '수식 검증 실패')
    }
  }

  if (loading) return null
  if (failed) return null

  return (
    <div className="status-card">
      <h3 className="status-card__title">수식(Formula)</h3>
      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다 — 저장이 가능합니다.'
          : '조회만 가능합니다. 저장하려면 admin 권한이 필요합니다.'}
      </p>
      <div className="form-row">
        <label className="form-label" htmlFor="formula-input">formula</label>
        <input
          id="formula-input"
          className="form-search"
          disabled={!isAdmin || saving}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </div>
      <div className="form-actions">
        <button
          type="button"
          className="refresh-btn"
          disabled={!isAdmin || saving}
          onClick={handleSave}
        >
          {saving ? '저장 중...' : '💾 수식 저장(검증)'}
        </button>
      </div>
      {saveMessage && <p className="status-card__success">{saveMessage}</p>}
      {saveError && <p className="status-card__error">⚠ {saveError}</p>}
    </div>
  )
}

// STEP 4-H-2: Legal Hold 체크리스트 조회/수정 카드. PromoteCard 바로 위에 두어
// admin이 필수 항목을 확인/체크한 뒤 자연스럽게 READY 전환으로 이어지도록
// 한다. 이 카드는 체크리스트 저장만 담당하며, READY 전환(promote) 호출
// 로직은 PromoteCard의 기존 구현을 그대로 사용한다(여기서 만들거나 바꾸지 않음).
function ChecklistCard({ slug }) {
  const [items, setItems] = useState(null)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [checkedMap, setCheckedMap] = useState({})
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setFailed(false)
    setSaveMessage(null)
    setSaveError(null)
    Promise.all([getCalculatorChecklist(slug), getCurrentUser()]).then(([c, u]) => {
      setUser(u)
      if (c?.success && c.data) {
        const loaded = c.data.items || []
        setItems(loaded)
        const map = {}
        for (const item of loaded) map[item.id] = Boolean(item.checked)
        setCheckedMap(map)
      }
      setFailed(!c?.success)
      setLoading(false)
    })
  }, [slug])

  useEffect(() => {
    load()
  }, [load])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  function toggle(id) {
    if (!isAdmin || saving) return
    setCheckedMap((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  async function handleSave() {
    if (saving || !items) return
    const changed = items
      .filter((item) => Boolean(item.checked) !== Boolean(checkedMap[item.id]))
      .map((item) => ({ id: item.id, checked: Boolean(checkedMap[item.id]) }))
    if (changed.length === 0) {
      setSaveMessage('변경된 항목이 없습니다')
      setSaveError(null)
      return
    }
    setSaving(true)
    setSaveMessage(null)
    setSaveError(null)
    const res = await patchCalculatorChecklist(slug, changed)
    setSaving(false)
    if (res.success) {
      const updated = res.data.items || []
      setItems(updated)
      const map = {}
      for (const item of updated) map[item.id] = Boolean(item.checked)
      setCheckedMap(map)
      setSaveMessage('체크리스트 저장 완료')
    } else {
      setSaveError(res.error?.message || '체크리스트 저장 실패')
    }
  }

  if (loading) return null
  if (failed) return null

  const critical = items.filter((i) => i.severity === 'critical')
  const advisory = items.filter((i) => i.severity !== 'critical')

  function renderItem(item) {
    const inputId = `chk-${slug}-${item.id}`
    return (
      <div className="kv-list__row" key={item.id}>
        <dt>
          <input
            type="checkbox"
            id={inputId}
            checked={Boolean(checkedMap[item.id])}
            disabled={!isAdmin || saving}
            onChange={() => toggle(item.id)}
          />
        </dt>
        <dd>
          <label htmlFor={inputId}>{item.label || item.id}</label>
          {item.display_value && <p className="status-card__hint">{item.display_value}</p>}
        </dd>
      </div>
    )
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">Legal Hold 체크리스트</h3>
      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다 — 항목을 체크하고 저장할 수 있습니다.'
          : '조회만 가능합니다. 저장하려면 admin 권한이 필요합니다.'}
      </p>
      {items.length === 0 && <p className="status-card__hint">체크리스트 항목이 없습니다.</p>}
      {critical.length > 0 && (
        <>
          <p className="panel-section-title">🔴 필수 검토</p>
          <dl className="kv-list">{critical.map(renderItem)}</dl>
        </>
      )}
      {advisory.length > 0 && (
        <>
          <p className="panel-section-title">🟡 권장 검토</p>
          <dl className="kv-list">{advisory.map(renderItem)}</dl>
        </>
      )}
      {items.length > 0 && (
        <div className="form-actions">
          <button
            type="button"
            className="refresh-btn"
            disabled={!isAdmin || saving}
            onClick={handleSave}
          >
            {saving ? '저장 중...' : '💾 체크리스트 저장'}
          </button>
        </div>
      )}
      {saveMessage && <p className="status-card__success">{saveMessage}</p>}
      {saveError && <p className="status-card__error">⚠ {saveError}</p>}
    </div>
  )
}

// STEP 4-H-1: HOLD → READY 승인(promote) 카드. Legal Hold 체크리스트가 모두
// 완료된 계산기만 admin이 READY로 전환할 수 있다(검증은 전부 서버의
// modules.app_factory.promote_to_ready()가 수행 — 여기서는 상태 표시와 버튼 클릭만).
function PromoteCard({ slug, registryStatus }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState(registryStatus)
  const [saveMessage, setSaveMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)

  useEffect(() => {
    setStatus(registryStatus)
  }, [registryStatus])

  useEffect(() => {
    getCurrentUser().then((u) => {
      setUser(u)
      setLoading(false)
    })
  }, [])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')
  const isReady = status === 'READY'

  async function handlePromote() {
    if (saving) return
    setSaving(true)
    setSaveMessage(null)
    setSaveError(null)
    const res = await postCalculatorPromote(slug)
    setSaving(false)
    if (res.success) {
      setStatus(res.data.status)
      setSaveMessage(res.data.message || 'READY로 전환되었습니다')
    } else {
      setSaveError(res.error?.message || 'READY 전환 실패')
    }
  }

  if (loading) return null

  return (
    <div className="status-card">
      <h3 className="status-card__title">Legal Hold 승인</h3>
      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다.'
          : '조회만 가능합니다. READY 전환하려면 admin 권한이 필요합니다.'}
      </p>
      <dl className="kv-list">
        <div className="kv-list__row">
          <dt>현재 상태</dt>
          <dd><Badge value={isReady} onLabel="READY" offLabel={status || 'HOLD'} /></dd>
        </div>
      </dl>
      <div className="form-actions">
        <button
          type="button"
          className="refresh-btn"
          disabled={!isAdmin || isReady || saving}
          title={isReady ? '이미 READY 상태입니다' : undefined}
          onClick={handlePromote}
        >
          {saving ? '전환 중...' : '✅ READY 전환'}
        </button>
      </div>
      {saveMessage && <p className="status-card__success">{saveMessage}</p>}
      {saveError && <p className="status-card__error">⚠ {saveError}</p>}
    </div>
  )
}

// P0-4: 콘텐츠 생성(SEO/FAQ/본문/이미지/전체) 카드. dashboard.py "🤖 AI 자동 생성"
// 4개 버튼 + "⚡ 전체 자동생성"과 동일한 생성기를 재사용하는 API를 호출한다.
// 서버가 결정적 QA(빈 콘텐츠/mock 시그니처/cross-calculator contamination)와
// AI Review를 통과한 경우에만 saved:true를 반환하므로, 버튼을 눌렀다고 무조건
// "완료"로 표시하지 않는다 — saved/blocked_reason/qa/review를 그대로 반영한다.
// 서버가 실시간 진행 상황을 스트리밍하지 않으므로(단일 요청-응답), "생성 중"은
// 요청이 진행 중임을 뜻하고, 최종 상태(완료/검토필요/실패)는 응답이 온 뒤 그
// 필드값으로부터 결정적으로 계산한다(가짜 실시간 진행률을 보여주지 않는다).
function ContentQaFailList({ failed }) {
  if (!Array.isArray(failed) || failed.length === 0) return null
  return (
    <ul className="today-list">
      {failed.map((f, i) => (
        <li key={i}>❌ [{f.gate}/{f.grade}] {f.detail}</li>
      ))}
    </ul>
  )
}

function ContentGenerationCard({ slug }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(null) // 'seo' | 'faq' | 'body' | 'image' | 'full' | null
  const [results, setResults] = useState({ seo: null, faq: null, body: null, image: null, full: null })

  useEffect(() => {
    getCurrentUser().then((u) => {
      setUser(u)
      setLoading(false)
    })
  }, [])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  async function run(kind, apiFn, label) {
    setBusy(kind)
    setResults((prev) => ({ ...prev, [kind]: null }))
    const res = await apiFn(slug)
    setBusy(null)
    setResults((prev) => ({
      ...prev,
      [kind]: res.success ? res.data : { ok: false, saved: false, blocked_reason: res.error?.message || `${label} 요청 실패`, qa: { ok: false, failed: [] }, content: null },
    }))
  }

  if (loading) return null

  function statusLabel(r) {
    if (!r) return '대기'
    if (!r.ok) return '실패'
    if (r.saved) return '완료'
    if (r.review && r.review.review_status === 'NEEDS_REVIEW') return '검토 필요'
    return 'QA 실패'
  }

  function ResultBlock({ kind, label, apiFn, children }) {
    const r = results[kind]
    const isBusy = busy === kind
    return (
      <div className="content-gen-row">
        <div className="form-actions">
          <button type="button" className="refresh-btn" disabled={!isAdmin || Boolean(busy)} onClick={() => run(kind, apiFn, label)}>
            {isBusy ? `${label} 생성 중...` : `${label} 생성`}
          </button>
          <span className={`badge ${r ? (r.saved ? 'badge--on' : 'badge--off') : ''}`}>{statusLabel(r)}</span>
        </div>
        {r && !r.saved && r.blocked_reason && (
          <p className="status-card__error">🔒 {r.blocked_reason}</p>
        )}
        {r && r.qa && <ContentQaFailList failed={r.qa.failed} />}
        {r && r.content && children ? children(r.content) : null}
      </div>
    )
  }

  const full = results.full

  return (
    <div className="status-card">
      <h3 className="status-card__title">콘텐츠 생성</h3>
      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다 — SEO/FAQ/본문/이미지 프롬프트를 생성할 수 있습니다.'
          : '조회만 가능합니다. 콘텐츠 생성에는 admin 권한이 필요합니다.'}
      </p>

      <ResultBlock kind="seo" label="SEO" apiFn={postCalculatorContentSeo}>
        {(c) => (
          <div className="content-preview">
            <div><strong>제목:</strong> {c.seo_title}</div>
            <div><strong>설명:</strong> {c.seo_description}</div>
          </div>
        )}
      </ResultBlock>

      <ResultBlock kind="faq" label="FAQ" apiFn={postCalculatorContentFaq}>
        {(c) => (
          <ul className="today-list">
            {(c.faq || []).map((f, i) => (
              <li key={i}>Q. {f.question || f.q} / A. {f.answer || f.a}</li>
            ))}
          </ul>
        )}
      </ResultBlock>

      <ResultBlock kind="body" label="본문" apiFn={postCalculatorContentBody}>
        {(c) => <pre className="content-preview">{(c.article_content || '').slice(0, 1500)}</pre>}
      </ResultBlock>

      <ResultBlock kind="image" label="이미지 프롬프트" apiFn={postCalculatorContentImage}>
        {(c) => (
          <div className="content-preview">
            <div><strong>썸네일:</strong> {c.image_prompt_thumbnail}</div>
            <div><strong>본문:</strong> {c.image_prompt_body}</div>
          </div>
        )}
      </ResultBlock>

      <div className="content-gen-row">
        <p className="panel-section-title">⚡ 전체 자동생성(SEO → FAQ → 본문 → 이미지 → QA → AI Review)</p>
        <div className="form-actions">
          <button
            type="button" className="refresh-btn" disabled={!isAdmin || Boolean(busy)}
            onClick={() => run('full', postCalculatorContentGenerateAll, '전체')}
          >
            {busy === 'full' ? '생성 중... (수십 초)' : '⚡ 전체 자동생성'}
          </button>
          <span className={`badge ${full ? (full.saved ? 'badge--on' : 'badge--off') : ''}`}>{statusLabel(full)}</span>
        </div>
        {full && !full.saved && full.blocked_reason && (
          <p className="status-card__error">🔒 {full.blocked_reason}</p>
        )}
        {full && full.review && (
          <p className="status-card__hint">
            AI Review: {full.review.review_status} ({full.review.review_score}점) — {full.review.review_reason}
          </p>
        )}
        {full && full.qa && <ContentQaFailList failed={full.qa.failed} />}
        {full && full.content && (
          <details>
            <summary>생성 결과 상세 보기</summary>
            <div className="content-preview">
              <div><strong>SEO 제목:</strong> {full.content.seo_title}</div>
              <div><strong>SEO 설명:</strong> {full.content.seo_description}</div>
              <div><strong>FAQ:</strong> {(full.content.faq || []).length}개</div>
              <div><strong>본문 길이:</strong> {(full.content.article_content || '').length}자</div>
            </div>
          </details>
        )}
      </div>
    </div>
  )
}

// P0-2: Build/Deploy 카드. dashboard.py의 "🧮 생성"→QA→"🚀 배포" 버튼과 동일한
// 백엔드 함수(app_generator.generate_calculator/pre_build_qa/github_deployer.
// deploy_app)를 재사용하는 API를 호출한다. Deploy 버튼을 누른다고 무조건
// 성공으로 표시하지 않는다 — 서버가 돌려준 ok/blocked_reason을 그대로 반영한다.
//
// STEP S1: dashboard.py의 "👤 사람 검수"(QA PASS 후에만 노출, 승인 전에는 배포
// 버튼이 disabled — dashboard.py:1753-1796)와 동일한 안전 게이트를 복원한다.
// 승인 여부는 항상 서버 조회(getCalculatorReview) 결과를 기준으로 판단한다 —
// 클라이언트가 "승인했다"고 로컬 상태만 바꾸고 Deploy 버튼을 활성화하지 않는다
// (실제 차단은 어차피 서버가 하지만, UI도 서버 진실을 그대로 반영해야 한다).
function BuildDeployCard({ slug }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [building, setBuilding] = useState(false)
  const [deploying, setDeploying] = useState(false)
  const [approving, setApproving] = useState(false)
  const [buildResult, setBuildResult] = useState(null)
  const [deployResult, setDeployResult] = useState(null)
  const [reviewStatus, setReviewStatus] = useState(null)
  const [reviewError, setReviewError] = useState(null)

  const loadReviewStatus = useCallback(async () => {
    const res = await getCalculatorReview(slug)
    if (res.success) {
      setReviewStatus(res.data)
    } else {
      setReviewStatus(null)
      setReviewError(res.error?.message || '검수 상태 조회 실패')
    }
  }, [slug])

  useEffect(() => {
    getCurrentUser().then((u) => {
      setUser(u)
      setLoading(false)
    })
    loadReviewStatus()
  }, [loadReviewStatus])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  async function handleBuild() {
    setBuilding(true)
    setBuildResult(null)
    const res = await postCalculatorBuild(slug)
    setBuilding(false)
    setBuildResult(res.success ? res.data : { ok: false, message: res.error?.message || 'Build 요청 실패' })
    await loadReviewStatus() // Build 재실행으로 스냅샷 내용이 바뀌면 기존 승인이 무효화될 수 있다
  }

  async function handleApprove() {
    setApproving(true)
    setReviewError(null)
    const res = await postCalculatorReviewApprove(slug)
    setApproving(false)
    if (res.success && res.data.ok) {
      await loadReviewStatus()
    } else {
      setReviewError((res.success ? res.data.blocked_reason : res.error?.message) || '검수 승인 실패')
      await loadReviewStatus()
    }
  }

  async function handleUnapprove() {
    setApproving(true)
    setReviewError(null)
    const res = await postCalculatorReviewUnapprove(slug)
    setApproving(false)
    if (res.success) await loadReviewStatus()
  }

  async function handleDeploy() {
    setDeploying(true)
    setDeployResult(null)
    const res = await postCalculatorDeploy(slug)
    setDeploying(false)
    setDeployResult(res.success ? res.data : { ok: false, blocked_reason: res.error?.message || 'Deploy 요청 실패' })
    await loadReviewStatus()
  }

  if (loading) return null

  const qaFailedCount = Array.isArray(buildResult?.qa_steps)
    ? buildResult.qa_steps.filter((s) => !s.passed && !s.skipped).length
    : 0

  const hasSnapshot = Boolean(reviewStatus?.has_snapshot)
  const approved = Boolean(reviewStatus?.approved)
  const stale = Boolean(reviewStatus?.stale)

  let reviewLabel = 'Build 필요'
  if (hasSnapshot) {
    reviewLabel = approved ? '✅ 검수 승인 완료' : stale ? '⚠️ 검수 재필요(Build 결과 변경됨)' : '⏳ 검수 필요'
  }
  const canApprove = isAdmin && hasSnapshot && !approved && !approving
  const canDeploy = isAdmin && approved && !deploying

  return (
    <div className="status-card">
      <h3 className="status-card__title">Build / Deploy</h3>
      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다 — Build/Deploy를 실행할 수 있습니다.'
          : '조회만 가능합니다. Build/Deploy에는 admin 권한이 필요합니다.'}
      </p>
      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || building} onClick={handleBuild}>
          {building ? 'Build 진행 중...' : '🧮 Build'}
        </button>
      </div>

      {buildResult && (
        <div>
          <p className={buildResult.ok ? 'status-card__success' : 'status-card__error'}>
            {buildResult.ok ? '✅ Build 성공 — 정적 스냅샷 저장됨' : `⚠ Build 실패/차단: ${buildResult.message || ''}`}
          </p>
          {buildResult.formula_valid === false && (
            <p className="status-card__error">Formula Hard Gate 실패: {buildResult.formula_message}</p>
          )}
          {buildResult.html_completeness && !buildResult.html_completeness.ok && (
            <p className="status-card__error">HTML/JS 완결성 검증 실패: {buildResult.html_completeness.message}</p>
          )}
          {Array.isArray(buildResult.qa_steps) && buildResult.qa_steps.length > 0 && (
            <details>
              <summary>Pre-build QA 상세({qaFailedCount}건 실패)</summary>
              <ul className="today-list">
                {buildResult.qa_steps.map((s) => (
                  <li key={s.step}>
                    {s.passed ? '✅' : s.skipped ? '⏭️' : '❌'} Step {s.step}: {s.label} — {s.detail}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <p className="panel-section-title">👤 사람 검수</p>
      <div className="form-actions">
        <span className={`badge ${approved ? 'badge--on' : 'badge--off'}`}>{reviewLabel}</span>
        {!approved && (
          <button type="button" className="refresh-btn" disabled={!canApprove} onClick={handleApprove}
                  title={!hasSnapshot ? '먼저 🧮 Build를 실행하세요' : undefined}>
            {approving ? '승인 처리 중...' : '✅ 검수 승인'}
          </button>
        )}
        {approved && (
          <button type="button" className="refresh-btn" disabled={!isAdmin || approving} onClick={handleUnapprove}>
            {approving ? '처리 중...' : '↩️ 승인 취소'}
          </button>
        )}
      </div>
      {reviewError && <p className="status-card__error">⚠ {reviewError}</p>}

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!canDeploy} onClick={handleDeploy}
                title={!approved ? '검수 승인 후 배포할 수 있습니다' : undefined}>
          {deploying ? 'Deploy 진행 중...' : '🚀 Deploy'}
        </button>
      </div>

      {deployResult && (
        <p className={deployResult.ok ? 'status-card__success' : 'status-card__error'}>
          {deployResult.ok ? deployResult.message : `🔒 ${deployResult.blocked_reason || 'Deploy 실패'}`}
        </p>
      )}
    </div>
  )
}

// P0-3: Build 결과물 Preview 카드. dashboard.py "🔎 앱 미리보기"(streamlit.components.
// v1.html)와 동일하게, GitHub Pages에 실제 배포되는 정적 HTML(CSS/JS 인라인)을
// 격리된 iframe에서 사람이 실제 사용자 화면처럼 확인한다. sandbox="allow-scripts"만
// 부여해(allow-same-origin 없음) iframe이 부모 페이지의 window/DOM/localStorage에
// 접근할 수 없는 별도 opaque origin에서 실행되도록 한다 — 새 라이브러리 없이 브라우저
// 표준 격리만 사용. Preview는 조회 전용(GET, 인증 없음)이라 admin 게이팅을 하지 않는다
// (다른 조회 섹션인 콘텐츠 미리보기와 동일한 노출 범위).
function PreviewCard({ slug }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [fetchError, setFetchError] = useState(null)

  async function handleOpen() {
    setOpen(true)
    setLoading(true)
    setFetchError(null)
    setResult(null)
    const res = await getCalculatorPreview(slug)
    setLoading(false)
    if (res.success) {
      setResult(res.data)
    } else {
      setFetchError(res.error?.message || 'Preview 조회 실패')
    }
  }

  function handleClose() {
    setOpen(false)
    setResult(null)
    setFetchError(null)
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">Preview</h3>
      <p className="status-card__hint">
        Build가 실제로 저장한 정적 산출물을 격리된 iframe에서 미리 봅니다(재생성하지 않음 — Build 버튼을 먼저 실행하세요).
      </p>
      <div className="form-actions">
        {!open ? (
          <button type="button" className="refresh-btn" onClick={handleOpen}>
            🔎 Preview 열기
          </button>
        ) : (
          <button type="button" className="refresh-btn" onClick={handleClose}>
            ✖ Preview 닫기
          </button>
        )}
      </div>

      {open && loading && <p className="status-card__hint">불러오는 중...</p>}
      {open && !loading && fetchError && <p className="status-card__error">⚠ {fetchError}</p>}
      {open && !loading && result && !result.previewable && (
        <p className="status-card__error">🔒 {result.message || 'Preview 불가'}</p>
      )}
      {open && !loading && result?.previewable && (
        <iframe
          title={`preview-${slug}`}
          className="calculator-preview-frame"
          srcDoc={result.html}
          sandbox="allow-scripts"
          referrerPolicy="no-referrer"
        />
      )}
    </div>
  )
}

// ── CALCMATE-STREAMLIT-REMAINING-MIGRATION-GAP-01-03-IMPLEMENT-01 ─────────────
// GAP-01: dashboard.py "⏸ 상태토글"(active ↔ inactive). 최종 상태는 서버 응답 값으로 반영한다.
function StatusToggleCard({ slug, dbStatus, onChanged }) {
  const [user, setUser] = useState(null)
  const [current, setCurrent] = useState(dbStatus || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { setCurrent(dbStatus || '') }, [dbStatus])
  useEffect(() => { getCurrentUser().then(setUser) }, [])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')
  const target = String(current).toLowerCase() === 'active' ? 'inactive' : 'active'

  async function handleToggle() {
    if (!isAdmin || saving) return
    setSaving(true)
    setError(null)
    const res = await postCalculatorStatus(slug, target)
    setSaving(false)
    if (res?.success) {
      setCurrent(res.data.status)
      onChanged?.(res.data.status)
    } else {
      setError(res?.error?.message || '상태 변경 실패')
    }
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">상태 토글</h3>
      <p className="status-card__hint">
        {isAdmin ? 'active ↔ inactive 전환' : '조회만 가능합니다. 상태 변경은 admin 권한이 필요합니다.'}
      </p>
      <dl className="kv-list">
        <div className="kv-list__row">
          <dt>현재 상태</dt>
          <dd data-testid="calc-db-status">{current || 'unknown'}</dd>
        </div>
      </dl>
      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || saving} onClick={handleToggle}>
          {saving ? '변경 중...' : `⏸ 상태토글 (→ ${target})`}
        </button>
      </div>
      {error && <p className="status-card__error">⚠ {error}</p>}
    </div>
  )
}

// GAP-03: dashboard.py "⚙️ Build"(전체 정적 사이트 재빌드). 개별 Build(BuildDeployCard)와 별개이며
// push/deploy는 하지 않는다 — 결과와 수동 배포 안내만 보여준다.
function SiteRebuildCard({ slug, registryStatus }) {
  const [user, setUser] = useState(null)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => { getCurrentUser().then(setUser) }, [])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')
  const isReady = registryStatus === 'READY'

  async function handleRebuild() {
    if (!isAdmin || !isReady || running) return
    setRunning(true)
    setError(null)
    const res = await postSiteRebuild(slug)
    setRunning(false)
    if (res?.success) setResult(res.data)
    else setError(res?.error?.message || '전체 사이트 Build 요청 실패')
  }

  const v = result?.validation
  const qaFailed = (result?.qa || []).filter((r) => !r.passed && !r.skipped)
  return (
    <div className="status-card">
      <h3 className="status-card__title">⚙️ 전체 사이트 Build</h3>
      <p className="status-card__hint">
        _site 전체(계산기·공통 페이지·sitemap)를 다시 만듭니다. 배포(push)는 하지 않습니다.
        {!isReady && ' READY 상태의 App Factory 계산기에서만 실행할 수 있습니다.'}
      </p>
      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || !isReady || running} onClick={handleRebuild}>
          {running ? 'Build 중...' : '⚙️ 전체 사이트 Build'}
        </button>
      </div>
      {running && <p className="status-card__hint">재빌드 진행 중(최대 180초)...</p>}
      {error && <p className="status-card__error">⚠ {error}</p>}
      {result && (
        <div data-testid="site-rebuild-result">
          <p className={result.ok ? 'status-card__success' : 'status-card__error'}>{result.message}</p>
          {qaFailed.length > 0 && (
            <ul className="today-list">
              {qaFailed.map((r) => <li key={r.step}>❌ Step {r.step}: {r.label} — {r.detail}</li>)}
            </ul>
          )}
          {result.summary && (
            <p className="status-card__hint">
              생성 {result.summary.ok_count} · 건너뜀 {result.summary.skip_count} · 오류 {result.summary.error_count}
              {result.summary.errors?.length > 0 && ` (오류: ${result.summary.errors.join(', ')})`}
              {result.duration_sec != null && ` · ${result.duration_sec}초`}
            </p>
          )}
          {v && (
            <ul className="today-list">
              <li>{v.required_missing.length === 0 && v.required_stale.length === 0 ? '✅' : '⚠️'} 공통 페이지 9종
                {v.required_missing.length > 0 && ` — 누락: ${v.required_missing.join(', ')}`}
                {v.required_stale.length > 0 && ` — 갱신 안 됨: ${v.required_stale.join(', ')}`}</li>
              <li>{v.calculators_missing.length === 0 ? '✅' : '⚠️'} 계산기 {v.calculators_expected}종
                {v.calculators_missing.length > 0 && ` — 누락: ${v.calculators_missing.join(', ')}`}</li>
              <li>{v.target_index ? '✅' : '⚠️'} _site/{slug}/index.html</li>
              <li>{v.target_in_sitemap ? '✅' : '⚠️'} sitemap.xml에 {slug} 포함</li>
            </ul>
          )}
          {result.ok && result.manual_deploy_steps && (
            <>
              <p className="panel-section-title">📋 배포 전 확인 체크리스트 (수동 진행)</p>
              <ol>{result.manual_deploy_steps.map((s) => <li key={s}><code>{s}</code></li>)}</ol>
            </>
          )}
        </div>
      )}
    </div>
  )
}

// GAP-02: dashboard.py "🗑 삭제"(app_factory.delete_app — DB + Registry). 즉시 삭제하지 않는다:
// 1) 삭제 준비(서버가 대상·범위·1회용 토큰 발급) → 2) slug 재입력 → 3) 정말 삭제.
function DeleteCalculatorCard({ slug, onDeleted }) {
  const [user, setUser] = useState(null)
  const [prep, setPrep] = useState(null)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => { getCurrentUser().then(setUser) }, [])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  async function handlePrepare() {
    if (!isAdmin || busy) return
    setBusy(true)
    setError(null)
    const res = await postCalculatorDeletePrepare(slug)
    setBusy(false)
    if (res?.success) { setPrep(res.data); setTyped('') }
    else setError(res?.error?.message || '삭제 준비 실패')
  }

  async function handleConfirm() {
    if (!prep || busy || typed !== prep.slug) return
    setBusy(true)
    setError(null)
    const res = await postCalculatorDeleteConfirm(slug, prep.token, typed)
    setBusy(false)
    if (res?.success) {
      onDeleted?.(res.data)
    } else {
      setPrep(null)
      setError(res?.error?.message || '삭제 실패')
    }
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">관리</h3>
      {!prep && (
        <div className="form-actions">
          <button type="button" className="refresh-btn" disabled={!isAdmin || busy} onClick={handlePrepare}
                  title={isAdmin ? undefined : '삭제는 admin 권한이 필요합니다'}>
            {busy ? '확인 중...' : '🗑 삭제'}
          </button>
        </div>
      )}
      {prep && (
        <div data-testid="calc-delete-confirm">
          <p className="status-card__error">⚠ 되돌릴 수 없습니다. 아래 계산기를 삭제합니다.</p>
          <dl className="kv-list">
            <div className="kv-list__row"><dt>이름</dt><dd>{prep.name}</dd></div>
            <div className="kv-list__row"><dt>slug</dt><dd>{prep.slug}</dd></div>
          </dl>
          <p className="status-card__hint">삭제 대상: {prep.scope.join(', ')}</p>
          <p className="status-card__hint">삭제하지 않음: {prep.not_touched.join(', ')}</p>
          <div className="form-row">
            <label className="form-label" htmlFor="calc-delete-typed">확인을 위해 slug를 입력하세요</label>
            <input id="calc-delete-typed" className="form-search" value={typed} disabled={busy}
                   onChange={(e) => setTyped(e.target.value)} />
          </div>
          <div className="form-actions">
            <button type="button" className="refresh-btn" disabled={busy || typed !== prep.slug} onClick={handleConfirm}>
              {busy ? '삭제 중...' : '정말 삭제'}
            </button>
            <button type="button" className="refresh-btn" disabled={busy} onClick={() => { setPrep(null); setTyped('') }}>
              취소
            </button>
          </div>
        </div>
      )}
      {error && <p className="status-card__error">⚠ {error}</p>}
    </div>
  )
}

// /calculators/:slug — 조회 전용(생성/삭제 버튼은 disabled, Build/Deploy는 P0-2에서
// 활성화됨). 수식 편집/저장는 STEP 4-G에서, 체크리스트 조회/수정은 STEP 4-H-2에서,
// READY 승인은 STEP 4-H-1에서, Preview는 P0-3에서 각각 활성화된다.
export default function CalculatorDetail() {
  const { slug } = useParams()
  const navigate = useNavigate()
  const [detail, setDetail] = useState(null)
  const [content, setContent] = useState(null)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      getCalculator(slug),
      getCalculatorContent(slug),
      getCalculatorStatus(slug),
    ]).then(([d, c, s]) => {
      setDetail(d)
      setContent(c)
      setStatus(s)
      setLoading(false)
    })
  }, [slug])

  useEffect(() => {
    load()
  }, [load])

  const notFound = !loading && detail && !detail.success && detail.error?.code === 'NOT_FOUND'
  const failed = !loading && !notFound && (!detail?.success || !content?.success || !status?.success)

  return (
    <div className="page">
      <div className="page__header">
        <h1 className="detail-title">{detail?.data?.name || slug}</h1>
        <Link to="/calculators" className="refresh-btn refresh-btn--link">
          ← 목록으로
        </Link>
      </div>
      <p className="status-card__hint detail-slug">slug: {slug}</p>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {notFound && <p className="status-card__error">⚠ 존재하지 않는 계산기입니다.</p>}
      {failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !notFound && !failed && (
        <div className="card-grid">
          <div className="status-card">
            <h3 className="status-card__title">Status</h3>
            <dl className="kv-list">
              <div className="kv-list__row">
                <dt>DB 상태</dt>
                <dd><Badge value={status.data.db_status === 'active'} onLabel="active" offLabel={status.data.db_status || 'unknown'} /></dd>
              </div>
              <div className="kv-list__row">
                <dt>Registry 상태</dt>
                <dd>{status.data.registry_status || '—'}</dd>
              </div>
              <div className="kv-list__row">
                <dt>Legal Hold</dt>
                <dd><Badge value={status.data.is_legal_hold} /></dd>
              </div>
              <div className="kv-list__row">
                <dt>Tier</dt>
                <dd>{status.data.tier ?? '—'}</dd>
              </div>
              <div className="kv-list__row">
                <dt>마지막 수정</dt>
                <dd className="kv-list__value">{detail.data.updated_at || '—'}</dd>
              </div>
            </dl>
          </div>

          <div className="status-card">
            <h3 className="status-card__title">배포 상태</h3>
            <dl className="kv-list">
              <div className="kv-list__row">
                <dt>콘텐츠 존재</dt>
                <dd><Badge value={status.data.has_content} /></dd>
              </div>
              <div className="kv-list__row">
                <dt>정적 HTML 존재</dt>
                <dd><Badge value={status.data.has_static_site} /></dd>
              </div>
              <div className="kv-list__row">
                <dt>배포됨</dt>
                <dd><Badge value={status.data.is_deployed} /></dd>
              </div>
            </dl>
            {status.data.static_files?.length > 0 && (
              <p className="status-card__hint">파일: {status.data.static_files.join(', ')}</p>
            )}
            {status.data.published_url && (
              <p className="status-card__hint detail-url">{status.data.published_url}</p>
            )}
          </div>

          <div className="status-card blog-panel">
            <h3 className="status-card__title">콘텐츠</h3>
            <dl className="kv-list">
              <div className="kv-list__row">
                <dt>SEO 제목</dt>
                <dd className="kv-list__value">{content.data.seo_title || '—'}</dd>
              </div>
              <div className="kv-list__row">
                <dt>메타 설명</dt>
                <dd className="kv-list__value">{content.data.seo_description || '—'}</dd>
              </div>
            </dl>

            {Array.isArray(content.data.faq) && content.data.faq.length > 0 && (
              <>
                <p className="panel-section-title">FAQ</p>
                <ul className="today-list">
                  {content.data.faq.map((item, i) => (
                    <li key={i}>
                      Q. {item.question || item.q} / A. {item.answer || item.a}
                    </li>
                  ))}
                </ul>
              </>
            )}

            <p className="panel-section-title">본문 미리보기</p>
            {/* React가 문자열을 텍스트로만 렌더링해 자동 escape한다 — dangerouslySetInnerHTML을 쓰지 않는다(XSS 방지). */}
            <pre className="content-preview">{content.data.article_content || '(콘텐츠 없음)'}</pre>
            {content.data.article_truncated && (
              <p className="status-card__hint">
                본문이 길어 일부만 표시됩니다(전체 {content.data.article_length.toLocaleString()}자).
              </p>
            )}
          </div>

          <FormulaCard slug={slug} />

          <ChecklistCard slug={slug} />

          <PromoteCard slug={slug} registryStatus={status.data.registry_status} />

          <ContentGenerationCard slug={slug} />

          <BuildDeployCard slug={slug} />

          <PreviewCard slug={slug} />

          <StatusToggleCard
            slug={slug}
            dbStatus={status.data.db_status}
            onChanged={(s) => setStatus((prev) => ({ ...prev, data: { ...prev.data, db_status: s } }))}
          />

          <SiteRebuildCard slug={slug} registryStatus={status.data.registry_status} />

          <DeleteCalculatorCard slug={slug} onDeleted={() => navigate('/calculators')} />
        </div>
      )}
    </div>
  )
}
