import { useCallback, useEffect, useState } from 'react'
import {
  getSettings,
  getBlogSchedulerStatus,
  getCalculatorSchedulerStatus,
  getContentSyncStatus,
  getGeneralSettings,
  patchGeneralSettings,
  getImageGoogleSettings,
  patchImageGoogleSettings,
  getCalculatorDisplaySettings,
  patchCalculatorDisplaySettings,
  getOperationsSettings,
  patchOperationsSettings,
  postNotifyConnectionTest,
  postPublishConnectionTest,
  getCurrentUser,
} from '../api/client.js'

// /settings — 통합 조회(STEP 18-M) + General Settings 저장(STEP 4-F).
// Blog Scheduler 설정 변경은 여전히 /scheduler 화면에서만 한다.
const ROWS = [
  { key: 'BLOG_SCHEDULE', label: 'Blog', worker: 'blog' },
  { key: 'CALC_WEBAPP_SCHEDULE', label: 'Calculator', worker: 'calculator' },
  { key: 'CONTENT_SYNC', label: 'Content Sync', worker: 'content_sync' },
  { key: 'PUBLISH_SCHEDULE', label: 'Publish', worker: null },
]

const AI_PROVIDERS = ['openai', 'claude', 'gemini']
const AI_ROLE_LABELS = {
  orchestrator: '총괄 AI',
  research: '리서치 AI',
  code: '코드 AI',
  writer: '작성 AI',
  review: '검수 AI',
  image: '이미지 AI',
}

function workerText(status) {
  if (!status) return '—'
  return status.running ? 'Worker Running' : 'Worker Stopped'
}

function emptyGeneralForm() {
  return {
    openaiApiKey: '',
    claudeApiKey: '',
    geminiApiKey: '',
    wordpressUrl: '',
    wordpressUsername: '',
    wordpressAppPassword: '',
    telegramBotToken: '',
    telegramChatId: '',
    dailyAiBudget: '',
    monthlyAiBudget: '',
    aiRoles: {},
  }
}

// GeneralSettingsPanel — 저장 가능한 항목만 별도 컴포넌트로 분리(기존 조회 테이블은 무수정).
function GeneralSettingsPanel() {
  const [general, setGeneral] = useState(null)
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [form, setForm] = useState(emptyGeneralForm())
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)
  const [wpTesting, setWpTesting] = useState(false)
  const [wpResult, setWpResult] = useState(null) // {ok, message}

  async function handleWpTest() {
    setWpTesting(true)
    setWpResult(null)
    const payload = {}
    if (form.wordpressUrl) payload.wordpress_url = form.wordpressUrl
    if (form.wordpressUsername) payload.wordpress_username = form.wordpressUsername
    if (form.wordpressAppPassword) payload.wordpress_app_password = form.wordpressAppPassword
    const res = await postPublishConnectionTest(payload)
    setWpTesting(false)
    if (res?.success) {
      setWpResult({ ok: Boolean(res.data?.ok), message: res.data?.message || '-' })
    } else {
      setWpResult({ ok: false, message: res?.error?.message || '연결 테스트 요청 실패' })
    }
  }

  const load = useCallback(() => {
    setLoading(true)
    setFailed(false)
    Promise.all([getGeneralSettings(), getCurrentUser()]).then(([g, u]) => {
      setGeneral(g)
      setUser(u)
      if (g?.success && g.data) {
        setForm((f) => ({
          ...f,
          wordpressUrl: g.data.WORDPRESS_URL || '',
          wordpressUsername: g.data.WORDPRESS_USERNAME || '',
          dailyAiBudget: g.data.DAILY_AI_BUDGET ?? '',
          monthlyAiBudget: g.data.MONTHLY_AI_BUDGET ?? '',
        }))
      }
      setFailed(!g?.success)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  function setField(name, value) {
    setForm((f) => ({ ...f, [name]: value }))
  }

  function setRole(role, field, value) {
    setForm((f) => ({
      ...f,
      aiRoles: {
        ...f.aiRoles,
        [role]: { ...(f.aiRoles[role] || {}), [field]: value },
      },
    }))
  }

  async function handleSave() {
    setSaving(true)
    setSaveMessage(null)
    setSaveError(null)

    const payload = {}
    if (form.openaiApiKey) payload.openai_api_key = form.openaiApiKey
    if (form.claudeApiKey) payload.claude_api_key = form.claudeApiKey
    if (form.geminiApiKey) payload.gemini_api_key = form.geminiApiKey
    if (form.wordpressUrl) payload.wordpress_url = form.wordpressUrl
    if (form.wordpressUsername) payload.wordpress_username = form.wordpressUsername
    if (form.wordpressAppPassword) payload.wordpress_app_password = form.wordpressAppPassword
    if (form.telegramBotToken) payload.telegram_bot_token = form.telegramBotToken
    if (form.telegramChatId) payload.telegram_chat_id = form.telegramChatId
    if (form.dailyAiBudget !== '') payload.daily_ai_budget = Number(form.dailyAiBudget)
    if (form.monthlyAiBudget !== '') payload.monthly_ai_budget = Number(form.monthlyAiBudget)
    const roleEntries = Object.entries(form.aiRoles).filter(
      ([, r]) => r && r.provider && r.model
    )
    if (roleEntries.length > 0) {
      payload.ai_roles = Object.fromEntries(roleEntries)
    }

    const res = await patchGeneralSettings(payload)
    setSaving(false)
    if (res.success) {
      setSaveMessage('저장되었습니다.')
      setForm((f) => ({
        ...f,
        openaiApiKey: '',
        claudeApiKey: '',
        geminiApiKey: '',
        wordpressAppPassword: '',
        telegramBotToken: '',
        telegramChatId: '',
      }))
      load()
    } else {
      setSaveError(res.error?.message || '저장 실패')
    }
  }

  if (loading) return <p className="status-card__hint">불러오는 중...</p>
  if (failed) return <p className="status-card__error">⚠ API 연결 실패</p>

  const secretStatus = (key) =>
    general?.data?.[key]?.configured ? '설정됨' : '미설정'

  return (
    <div className="status-card settings-panel">
      <h3 className="status-card__title">General Settings</h3>
      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다 — 저장이 가능합니다.'
          : '조회만 가능합니다. 저장하려면 admin 권한이 필요합니다.'}
      </p>

      <p className="panel-section-title">🔑 AI API Keys</p>
      <div className="form-row">
        <label className="form-label" htmlFor="s-openai">OpenAI API Key ({secretStatus('OPENAI_API_KEY')})</label>
        <input id="s-openai" type="password" className="form-search" disabled={!isAdmin}
               placeholder="변경할 때만 입력" value={form.openaiApiKey}
               onChange={(e) => setField('openaiApiKey', e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="s-claude">Claude API Key ({secretStatus('CLAUDE_API_KEY')})</label>
        <input id="s-claude" type="password" className="form-search" disabled={!isAdmin}
               placeholder="변경할 때만 입력" value={form.claudeApiKey}
               onChange={(e) => setField('claudeApiKey', e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="s-gemini">Gemini API Key ({secretStatus('GEMINI_API_KEY')})</label>
        <input id="s-gemini" type="password" className="form-search" disabled={!isAdmin}
               placeholder="변경할 때만 입력" value={form.geminiApiKey}
               onChange={(e) => setField('geminiApiKey', e.target.value)} />
      </div>

      <p className="panel-section-title">🌐 WordPress</p>
      <div className="form-row">
        <label className="form-label" htmlFor="s-wpurl">WORDPRESS_URL</label>
        <input id="s-wpurl" className="form-search" disabled={!isAdmin}
               value={form.wordpressUrl} onChange={(e) => setField('wordpressUrl', e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="s-wpuser">WORDPRESS_USERNAME</label>
        <input id="s-wpuser" className="form-search" disabled={!isAdmin}
               value={form.wordpressUsername} onChange={(e) => setField('wordpressUsername', e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="s-wppw">WORDPRESS_APP_PASSWORD ({secretStatus('WORDPRESS_APP_PASSWORD')})</label>
        <input id="s-wppw" type="password" className="form-search" disabled={!isAdmin}
               placeholder="변경할 때만 입력" value={form.wordpressAppPassword}
               onChange={(e) => setField('wordpressAppPassword', e.target.value)} />
      </div>
      {/* SMALL-GAPS-02: dashboard.py "🔌 WordPress 연결 테스트" — 서버가 연결을 시도한다.
          앱 비밀번호를 비워 두면 저장된 값으로 테스트한다(저장값 원문은 화면에 오지 않음). */}
      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || wpTesting} onClick={handleWpTest}>
          {wpTesting ? '테스트 중...' : '🔌 WordPress 연결 테스트'}
        </button>
      </div>
      {wpResult && (
        <p className={wpResult.ok ? 'status-card__success' : 'status-card__error'}>
          {wpResult.ok ? '✅' : '⚠'} {wpResult.message}
        </p>
      )}

      <p className="panel-section-title">📨 Telegram</p>
      <div className="form-row">
        <label className="form-label" htmlFor="s-tgtoken">TELEGRAM_BOT_TOKEN ({secretStatus('TELEGRAM_BOT_TOKEN')})</label>
        <input id="s-tgtoken" type="password" className="form-search" disabled={!isAdmin}
               placeholder="변경할 때만 입력" value={form.telegramBotToken}
               onChange={(e) => setField('telegramBotToken', e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="s-tgchat">TELEGRAM_CHAT_ID ({secretStatus('TELEGRAM_CHAT_ID')})</label>
        <input id="s-tgchat" type="password" className="form-search" disabled={!isAdmin}
               placeholder="변경할 때만 입력" value={form.telegramChatId}
               onChange={(e) => setField('telegramChatId', e.target.value)} />
      </div>

      <p className="panel-section-title">💰 Budget</p>
      <div className="form-row">
        <label className="form-label" htmlFor="s-daily">DAILY_AI_BUDGET (USD)</label>
        <input id="s-daily" type="number" min={1} max={1000} className="form-number" disabled={!isAdmin}
               value={form.dailyAiBudget} onChange={(e) => setField('dailyAiBudget', e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="s-monthly">MONTHLY_AI_BUDGET (USD)</label>
        <input id="s-monthly" type="number" min={1} max={10000} className="form-number" disabled={!isAdmin}
               value={form.monthlyAiBudget} onChange={(e) => setField('monthlyAiBudget', e.target.value)} />
      </div>

      <p className="panel-section-title">🤖 AI Roles</p>
      {general?.data?.AI_ROLES && Object.entries(general.data.AI_ROLES).map(([role, spec]) => (
        <div className="form-row form-row--slot" key={role}>
          <span className="form-label">{AI_ROLE_LABELS[role] || role}</span>
          <div className="slot-inputs">
            <select
              className="form-select" disabled={!isAdmin}
              value={form.aiRoles[role]?.provider ?? spec.provider}
              onChange={(e) => setRole(role, 'provider', e.target.value)}
            >
              {AI_PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <input
              className="form-search" disabled={!isAdmin}
              value={form.aiRoles[role]?.model ?? spec.model}
              onChange={(e) => setRole(role, 'model', e.target.value)}
            />
          </div>
        </div>
      ))}

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || saving} onClick={handleSave}>
          {saving ? '저장 중...' : '💾 설정 저장'}
        </button>
      </div>
      {saveMessage && <p className="status-card__success">{saveMessage}</p>}
      {saveError && <p className="status-card__error">⚠ {saveError}</p>}
    </div>
  )
}

import CalculatorDisplaySettingsPanel from '../components/CalculatorDisplaySettingsPanel.jsx'
const IMAGE_PROVIDERS = ['free_pollinations', 'gemini', 'openai']
const IMAGE_SIZES = ['auto', '1024x1024', '1792x1024']
const IMAGE_QUALITIES = ['standard', 'hd']

function emptyImageGoogleForm() {
  return {
    imageProvider: 'free_pollinations',
    imageModel: '',
    imageSize: 'auto',
    imageQuality: 'standard',
    googleSheetId: '',
    googleDriveRootId: '',
    googleDrivePlaceholderFolderId: '',
  }
}

// ImageGoogleSettingsPanel — STEP P2-14: dashboard.py "🎨 블로그 이미지 생성 AI
// 설정"(3150-3183)/"📊 Google 연동"(3186-3189) 이관. GeneralSettingsPanel과
// 동일한 패턴(GET으로 초기값 로드 → 폼 편집 → PATCH만 호출)을 따르되, 이 7개는
// secret이 아니므로 값을 그대로 표시한다(마스킹 없음).
function ImageGoogleSettingsPanel() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [form, setForm] = useState(emptyImageGoogleForm())
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setFailed(false)
    Promise.all([getImageGoogleSettings(), getCurrentUser()]).then(([g, u]) => {
      setUser(u)
      if (g?.success && g.data) {
        setForm({
          imageProvider: g.data.IMAGE_PROVIDER || 'free_pollinations',
          imageModel: g.data.MODEL_IMAGE || '',
          imageSize: g.data.IMAGE_SIZE || 'auto',
          imageQuality: g.data.IMAGE_QUALITY || 'standard',
          googleSheetId: g.data.GOOGLE_SHEET_ID || '',
          googleDriveRootId: g.data.GOOGLE_DRIVE_ROOT_ID || '',
          googleDrivePlaceholderFolderId: g.data.GOOGLE_DRIVE_PLACEHOLDER_FOLDER_ID || '',
        })
      }
      setFailed(!g?.success)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  function setField(name, value) {
    setForm((f) => ({ ...f, [name]: value }))
  }

  async function handleSave() {
    setSaving(true)
    setSaveMessage(null)
    setSaveError(null)

    const res = await patchImageGoogleSettings({
      image_provider: form.imageProvider,
      image_model: form.imageModel,
      image_size: form.imageSize,
      image_quality: form.imageQuality,
      google_sheet_id: form.googleSheetId,
      google_drive_root_id: form.googleDriveRootId,
      google_drive_placeholder_folder_id: form.googleDrivePlaceholderFolderId,
    })
    setSaving(false)
    if (res.success) {
      setSaveMessage('저장되었습니다.')
      load()
    } else {
      setSaveError(res.error?.message || '저장 실패')
    }
  }

  if (loading) return <p className="status-card__hint">불러오는 중...</p>
  if (failed) return <p className="status-card__error">⚠ API 연결 실패</p>

  return (
    <div className="status-card settings-panel">
      <h3 className="status-card__title">🎨 Image-gen AI / 📊 Google 연동</h3>
      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다 — 저장이 가능합니다.'
          : '조회만 가능합니다. 저장하려면 admin 권한이 필요합니다.'}
      </p>

      <p className="panel-section-title">🎨 Image-gen AI</p>
      <div className="form-row">
        <label className="form-label" htmlFor="ig-provider">Image Provider</label>
        <select id="ig-provider" className="form-select" disabled={!isAdmin}
                value={form.imageProvider} onChange={(e) => setField('imageProvider', e.target.value)}>
          {IMAGE_PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="ig-model">Image Model</label>
        <input id="ig-model" className="form-search" disabled={!isAdmin}
               value={form.imageModel} onChange={(e) => setField('imageModel', e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="ig-size">Image Size</label>
        <select id="ig-size" className="form-select" disabled={!isAdmin}
                value={form.imageSize} onChange={(e) => setField('imageSize', e.target.value)}>
          {IMAGE_SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="ig-quality">Image Quality</label>
        <select id="ig-quality" className="form-select" disabled={!isAdmin}
                value={form.imageQuality} onChange={(e) => setField('imageQuality', e.target.value)}>
          {IMAGE_QUALITIES.map((q) => <option key={q} value={q}>{q}</option>)}
        </select>
      </div>

      <p className="panel-section-title">📊 Google 연동</p>
      <div className="form-row">
        <label className="form-label" htmlFor="ig-sheet">Google Sheet ID</label>
        <input id="ig-sheet" className="form-search" disabled={!isAdmin}
               value={form.googleSheetId} onChange={(e) => setField('googleSheetId', e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="ig-drive">Google Drive Root ID</label>
        <input id="ig-drive" className="form-search" disabled={!isAdmin}
               value={form.googleDriveRootId} onChange={(e) => setField('googleDriveRootId', e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="ig-placeholder">Google Drive Placeholder Folder ID</label>
        <input id="ig-placeholder" className="form-search" disabled={!isAdmin}
               value={form.googleDrivePlaceholderFolderId}
               onChange={(e) => setField('googleDrivePlaceholderFolderId', e.target.value)} />
      </div>

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || saving} onClick={handleSave}>
          {saving ? '저장 중...' : '💾 저장'}
        </button>
      </div>
      {saveMessage && <p className="status-card__success">{saveMessage}</p>}
      {saveError && <p className="status-card__error">⚠ {saveError}</p>}
    </div>
  )
}

// OperationsSettingsPanel — CALCMATE-REMAINING-DASHBOARD-KEEP-MIGRATION-01:
// dashboard.py "🤖 최신 텍스트 AI 역할 및 모델 매칭"(3101-3133, 블로그 파이프라인이
// 읽는 flat 키 — 위 AI Roles와 별개), "⚙️ 운영 설정"(3216-3231), "이벤트별 알림
// ON/OFF"(3252-3261), "📤 텔레그램 테스트 전송"(3241-3251) 이관. 옵션은 원본 그대로.
const PIPELINE_MODEL_PRESETS = {
  openai: ['gpt-4o', 'gpt-4o-mini'],
  claude: ['claude-sonnet-4-6', 'claude-opus-4-8', 'claude-haiku-4-5-20251001'],
  gemini: ['gemini-2.5-flash', 'gemini-2.5-pro'],
}
const PIPELINE_ROLES = [
  { id: 'orchestrator', label: '1. 전체 총괄 (Orchestrator)', providerKey: 'ORCHESTRATOR_PROVIDER', modelKey: 'MODEL_ORCHESTRATOR' },
  { id: 'planner', label: '2. 키워드 기획 (Planner)', providerKey: 'PLANNER_PROVIDER', modelKey: 'MODEL_PLANNER' },
  { id: 'writer', label: '3. 본문 초고 작성 (Writer)', providerKey: 'WRITER_PROVIDER', modelKey: 'MODEL_WRITER' },
  { id: 'editor', label: '4. SEO 교정 및 검수 (Editor)', providerKey: 'EDITOR_PROVIDER', modelKey: 'MODEL_EDITOR' },
]
const TELEGRAM_EVENTS = [
  ['error', '오류 발생'], ['budget', '비용 경고'], ['daily_summary', '일일 요약'],
  ['publish_request', '발행 승인 요청'], ['quality_critical_hold', '품질 HOLD(Critical)'],
  ['publish_success', '발행 완료'],
]

function OperationsSettingsPanel() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)
  const [tgToken, setTgToken] = useState('')
  const [tgChat, setTgChat] = useState('')
  const [tgTesting, setTgTesting] = useState(false)
  const [tgResult, setTgResult] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setFailed(false)
    Promise.all([getOperationsSettings(), getCurrentUser()]).then(([o, u]) => {
      setUser(u)
      if (o?.success && o.data) setForm(o.data)
      setFailed(!o?.success)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const isAdmin = Boolean(user?.success && user.data?.role === 'admin')

  function setField(key, value) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  function setProvider(role, provider) {
    setForm((f) => ({
      ...f,
      [role.providerKey]: provider,
      [role.modelKey]: (PIPELINE_MODEL_PRESETS[provider] || [])[0] || '',
    }))
  }

  async function handleSave() {
    setSaving(true)
    setSaveMessage(null)
    setSaveError(null)
    const payload = {
      model_cleaner: form.MODEL_CLEANER,
      model_editor_fallback: form.MODEL_EDITOR_FALLBACK,
      adsense_mode: form.ADSENSE_MODE,
      dlq_threshold: Number(form.DLQ_THRESHOLD),
      auto_topic_expansion: Boolean(form.AUTO_TOPIC_EXPANSION),
      enable_strategy_room: Boolean(form.ENABLE_STRATEGY_ROOM),
      telegram_events: form.TELEGRAM_EVENTS,
    }
    for (const role of PIPELINE_ROLES) {
      payload[`${role.id}_provider`] = form[role.providerKey]
      payload[`model_${role.id}`] = form[role.modelKey]
    }
    const res = await patchOperationsSettings(payload)
    setSaving(false)
    if (res.success) {
      setSaveMessage('저장되었습니다.')
      load()
    } else {
      setSaveError(res.error?.message || '저장 실패')
    }
  }

  async function handleTelegramTest() {
    setTgTesting(true)
    setTgResult(null)
    const payload = {}
    if (tgToken.trim()) payload.telegram_bot_token = tgToken.trim()
    if (tgChat.trim()) payload.telegram_chat_id = tgChat.trim()
    const res = await postNotifyConnectionTest(payload)
    setTgTesting(false)
    setTgResult(res.success
      ? { ok: true, message: '전송 시도 완료. 텔레그램 메시지를 확인하세요(미수신 시 토큰/Chat ID 재확인).' }
      : { ok: false, message: res.error?.message || '전송 실패' })
  }

  if (loading) return <p className="status-card__hint">불러오는 중...</p>
  if (failed || !form) return <p className="status-card__error">⚠ API 연결 실패</p>

  const modelOptions = (provider, current) => {
    const presets = PIPELINE_MODEL_PRESETS[provider] || []
    return presets.includes(current) || !current ? presets : [current, ...presets]
  }

  return (
    <div className="status-card settings-panel">
      <h3 className="status-card__title">🤖 블로그 파이프라인 모델 / ⚙️ 운영 설정</h3>
      <p className="status-card__hint">
        {isAdmin
          ? 'admin 권한으로 로그인되어 있습니다 — 저장이 가능합니다.'
          : '조회만 가능합니다. 저장하려면 admin 권한이 필요합니다.'}
      </p>

      <p className="panel-section-title">🤖 텍스트 AI 역할 및 모델 매칭 (블로그 파이프라인)</p>
      {PIPELINE_ROLES.map((role) => (
        <div className="form-row form-row--slot" key={role.id}>
          <span className="form-label">{role.label}</span>
          <div className="slot-inputs">
            <select aria-label={`${role.label} 제공사`} className="form-select" disabled={!isAdmin}
                    value={form[role.providerKey] || ''} onChange={(e) => setProvider(role, e.target.value)}>
              {Object.keys(PIPELINE_MODEL_PRESETS).map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <select aria-label={`${role.label} 모델명`} className="form-select" disabled={!isAdmin}
                    value={form[role.modelKey] || ''} onChange={(e) => setField(role.modelKey, e.target.value)}>
              {modelOptions(form[role.providerKey], form[role.modelKey]).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
        </div>
      ))}
      <div className="form-row">
        <label className="form-label" htmlFor="op-cleaner">뉴스 정리기 (Cleaner) 모델</label>
        <select id="op-cleaner" className="form-select" disabled={!isAdmin}
                value={form.MODEL_CLEANER || ''} onChange={(e) => setField('MODEL_CLEANER', e.target.value)}>
          {modelOptions('openai', form.MODEL_CLEANER).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="op-fallback">교정 실패시 백업 (Fallback) 모델</label>
        <select id="op-fallback" className="form-select" disabled={!isAdmin}
                value={form.MODEL_EDITOR_FALLBACK || ''} onChange={(e) => setField('MODEL_EDITOR_FALLBACK', e.target.value)}>
          {modelOptions('openai', form.MODEL_EDITOR_FALLBACK).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>

      <p className="panel-section-title">⚙️ 운영 설정</p>
      <div className="form-row">
        <label className="form-label" htmlFor="op-adsense">ADSENSE_MODE</label>
        <select id="op-adsense" className="form-select" disabled={!isAdmin}
                value={form.ADSENSE_MODE || 'pre'} onChange={(e) => setField('ADSENSE_MODE', e.target.value)}>
          {['pre', 'post'].map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="op-dlq">DLQ_THRESHOLD</label>
        <input id="op-dlq" type="number" min={1} max={10} className="form-number" disabled={!isAdmin}
               value={form.DLQ_THRESHOLD ?? ''} onChange={(e) => setField('DLQ_THRESHOLD', e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="op-autotopic">AUTO_TOPIC_EXPANSION</label>
        <input id="op-autotopic" type="checkbox" disabled={!isAdmin}
               checked={Boolean(form.AUTO_TOPIC_EXPANSION)} onChange={(e) => setField('AUTO_TOPIC_EXPANSION', e.target.checked)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="op-strategy">ENABLE_STRATEGY_ROOM</label>
        <input id="op-strategy" type="checkbox" disabled={!isAdmin}
               checked={Boolean(form.ENABLE_STRATEGY_ROOM)} onChange={(e) => setField('ENABLE_STRATEGY_ROOM', e.target.checked)} />
      </div>

      <p className="panel-section-title">📨 텔레그램 이벤트별 알림 ON/OFF</p>
      {TELEGRAM_EVENTS.map(([key, label]) => (
        <div className="form-row" key={key}>
          <label className="form-label" htmlFor={`op-tgev-${key}`}>{label}</label>
          <input id={`op-tgev-${key}`} type="checkbox" disabled={!isAdmin}
                 checked={Boolean(form.TELEGRAM_EVENTS?.[key])}
                 onChange={(e) => setField('TELEGRAM_EVENTS', { ...form.TELEGRAM_EVENTS, [key]: e.target.checked })} />
        </div>
      ))}
      <p className="status-card__hint">telegram_ops 경유 이벤트에 적용. 파이프라인 크리티컬 알림(오류/예산/헬스)은 항상 발송.</p>

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || saving} onClick={handleSave}>
          {saving ? '저장 중...' : '💾 저장'}
        </button>
      </div>
      {saveMessage && <p className="status-card__success">{saveMessage}</p>}
      {saveError && <p className="status-card__error">⚠ {saveError}</p>}

      <p className="panel-section-title">📤 텔레그램 테스트 전송</p>
      <p className="status-card__hint">비워 두면 저장된 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID로 보냅니다.</p>
      <div className="form-row">
        <label className="form-label" htmlFor="op-tgtoken">TELEGRAM_BOT_TOKEN (테스트용)</label>
        <input id="op-tgtoken" type="password" className="form-search" disabled={!isAdmin}
               placeholder="저장된 값 사용" value={tgToken} onChange={(e) => setTgToken(e.target.value)} />
      </div>
      <div className="form-row">
        <label className="form-label" htmlFor="op-tgchat">TELEGRAM_CHAT_ID (테스트용)</label>
        <input id="op-tgchat" className="form-search" disabled={!isAdmin}
               placeholder="저장된 값 사용" value={tgChat} onChange={(e) => setTgChat(e.target.value)} />
      </div>
      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || tgTesting} onClick={handleTelegramTest}>
          {tgTesting ? '전송 중...' : '📤 텔레그램 테스트 전송'}
        </button>
      </div>
      {tgResult && (
        <p className={tgResult.ok ? 'status-card__success' : 'status-card__error'}>
          {tgResult.ok ? tgResult.message : `⚠ ${tgResult.message}`}
        </p>
      )}
    </div>
  )
}

export default function Settings() {
  const [settings, setSettings] = useState(null)
  const [workers, setWorkers] = useState({})
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setFailed(false)
    Promise.all([
      getSettings(),
      getBlogSchedulerStatus(),
      getCalculatorSchedulerStatus(),
      getContentSyncStatus(),
    ]).then(([s, blog, calc, sync]) => {
      setSettings(s)
      setWorkers({ blog: blog?.data, calculator: calc?.data, content_sync: sync?.data })
      setFailed(!s?.success || !blog?.success || !calc?.success || !sync?.success)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="page">
      <div className="page__header">
        <h1>Settings</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      <p className="status-card__hint">
        Scheduler 관련 섹션은 READ-ONLY입니다(Blog Scheduler 설정은 Scheduler 화면에서 변경).
        <br />
        아래 General Settings(API 키/WordPress/Telegram/Budget/AI Roles)는 admin 권한으로 저장할 수 있습니다.
      </p>

      <GeneralSettingsPanel />
      <ImageGoogleSettingsPanel />
      <OperationsSettingsPanel />
      <CalculatorDisplaySettingsPanel />

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {!loading && failed && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !failed && settings && (
        <div className="status-card settings-panel">
          <table className="settings-table">
            <thead>
              <tr>
                <th>Section</th>
                <th>Enabled</th>
                <th>Mode</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map((row) => {
                const section = settings.data?.[row.key] || {}
                const worker = row.worker ? workers[row.worker] : null
                return (
                  <tr key={row.key}>
                    <td>{row.label}</td>
                    <td>
                      <span className={`badge ${section.enabled ? 'badge--on' : 'badge--off'}`}>
                        {section.enabled ? 'ON' : 'OFF'}
                      </span>
                    </td>
                    <td>{section.mode || '-'}</td>
                    <td>{workerText(worker)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
