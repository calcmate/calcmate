import { useCallback, useEffect, useState } from 'react'
import {
  getCalculatorDisplaySettings,
  patchCalculatorDisplaySettings,
  getCurrentUser,
} from '../api/client.js'

// /settings 하위: "🎨 계산기 노출 설정 (v2)" — dashboard.py:3586-3634 이관.
// 14개 필드: SITE_MODE, SHOW_SHARE, SHOW_PWA, SHOW_RESULT_SAVE, SHOW_FAQ,
// SHOW_NOTICE, SHOW_RELATED, SHOW_DETAIL, SHOW_ADSENSE, SHOW_CPA,
// RESULT_EXPORT_TYPE, KAKAO_JS_KEY, CALCULATOR_VERSION, LAW_VERSION
// 기존 ImageGoogleSettingsPanel 패턴을 그대로 재사용.

const SITE_MODES = ['pre_adsense', 'adsense', 'cpa', 'full']
const EXPORT_TYPES = ['png', 'pdf', 'both', 'none']

function emptyCalculatorDisplayForm() {
  return {
    site_mode: 'pre_adsense',
    show_share: true,
    show_pwa: false,
    show_result_save: true,
    show_faq: true,
    show_notice: true,
    show_related: true,
    show_detail: true,
    show_adsense: false,
    show_cpa: false,
    result_export_type: 'png',
    kakao_js_key: '',
    calculator_version: '2.0.0',
    law_version: '2026-07',
  }
}

export default function CalculatorDisplaySettingsPanel() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [form, setForm] = useState(emptyCalculatorDisplayForm())
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setFailed(false)
    Promise.all([getCalculatorDisplaySettings(), getCurrentUser()]).then(([g, u]) => {
      setUser(u)
      if (g?.success && g.data) {
        setForm({
          site_mode: g.data.SITE_MODE || 'pre_adsense',
          show_share: g.data.SHOW_SHARE ?? true,
          show_pwa: g.data.SHOW_PWA ?? false,
          show_result_save: g.data.SHOW_RESULT_SAVE ?? true,
          show_faq: g.data.SHOW_FAQ ?? true,
          show_notice: g.data.SHOW_NOTICE ?? true,
          show_related: g.data.SHOW_RELATED ?? true,
          show_detail: g.data.SHOW_DETAIL ?? true,
          show_adsense: g.data.SHOW_ADSENSE ?? false,
          show_cpa: g.data.SHOW_CPA ?? false,
          result_export_type: g.data.RESULT_EXPORT_TYPE || 'png',
          kakao_js_key: g.data.KAKAO_JS_KEY || '',
          calculator_version: g.data.CALCULATOR_VERSION || '2.0.0',
          law_version: g.data.LAW_VERSION || '2026-07',
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

    const payload = {}
    // boolean fields
    const boolFields = [
      'show_share', 'show_pwa', 'show_result_save', 'show_faq',
      'show_notice', 'show_related', 'show_detail', 'show_adsense', 'show_cpa'
    ]
    boolFields.forEach((name) => {
      if (form[name] !== undefined) payload[name] = form[name]
    })
    // string/enum fields
    const stringFields = ['site_mode', 'result_export_type', 'kakao_js_key', 'calculator_version', 'law_version']
    stringFields.forEach((name) => {
      if (form[name] !== undefined) payload[name] = form[name]
    })

    const res = await patchCalculatorDisplaySettings(payload)
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
      <h3 className="status-card__title">🎨 계산기 노출 설정 (v2)</h3>
      <p className="status-card__hint">
        생성되는 계산기 앱의 노출/정책. 저장 시 config.yaml에 반영되어 재생성물에 적용됩니다. (UI/계산식 무변경)
        {isAdmin
          ? ' — admin 권한으로 로그인되어 있습니다. 저장이 가능합니다.'
          : ' — 조회만 가능합니다. 저장하려면 admin 권한이 필요합니다.'}
      </p>

      <p className="panel-section-title">SITE_MODE</p>
      <div className="form-row">
        <label className="form-label" htmlFor="cds-site_mode">SITE_MODE</label>
        <select
          id="cds-site_mode"
          className="form-select"
          disabled={!isAdmin}
          value={form.site_mode}
          onChange={(e) => setField('site_mode', e.target.value)}
        >
          {SITE_MODES.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>

      <p className="panel-section-title">노출 토글</p>
      <div className="form-row form-row--checkbox">
        <label>
          <input
            type="checkbox"
            disabled={!isAdmin}
            checked={form.show_share}
            onChange={(e) => setField('show_share', e.target.checked)}
          />
          SHOW_SHARE
        </label>
        <label>
          <input
            type="checkbox"
            disabled={!isAdmin}
            checked={form.show_pwa}
            onChange={(e) => setField('show_pwa', e.target.checked)}
          />
          SHOW_PWA
        </label>
        <label>
          <input
            type="checkbox"
            disabled={!isAdmin}
            checked={form.show_result_save}
            onChange={(e) => setField('show_result_save', e.target.checked)}
          />
          SHOW_RESULT_SAVE
        </label>
        <label>
          <input
            type="checkbox"
            disabled={!isAdmin}
            checked={form.show_faq}
            onChange={(e) => setField('show_faq', e.target.checked)}
          />
          SHOW_FAQ
        </label>
        <label>
          <input
            type="checkbox"
            disabled={!isAdmin}
            checked={form.show_notice}
            onChange={(e) => setField('show_notice', e.target.checked)}
          />
          SHOW_NOTICE
        </label>
        <label>
          <input
            type="checkbox"
            disabled={!isAdmin}
            checked={form.show_related}
            onChange={(e) => setField('show_related', e.target.checked)}
          />
          SHOW_RELATED
        </label>
        <label>
          <input
            type="checkbox"
            disabled={!isAdmin}
            checked={form.show_detail}
            onChange={(e) => setField('show_detail', e.target.checked)}
          />
          SHOW_DETAIL
        </label>
        <label>
          <input
            type="checkbox"
            disabled={!isAdmin}
            checked={form.show_adsense}
            onChange={(e) => setField('show_adsense', e.target.checked)}
          />
          SHOW_ADSENSE (오버라이드)
        </label>
        <label>
          <input
            type="checkbox"
            disabled={!isAdmin}
            checked={form.show_cpa}
            onChange={(e) => setField('show_cpa', e.target.checked)}
          />
          SHOW_CPA (오버라이드)
        </label>
      </div>

      <p className="panel-section-title">결과 내보내기 / 키 / 버전</p>
      <div className="form-row">
        <label className="form-label" htmlFor="cds-result_export_type">RESULT_EXPORT_TYPE</label>
        <select
          id="cds-result_export_type"
          className="form-select"
          disabled={!isAdmin}
          value={form.result_export_type}
          onChange={(e) => setField('result_export_type', e.target.value)}
        >
          {EXPORT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      <div className="form-row">
        <label className="form-label" htmlFor="cds-kakao_js_key">KAKAO_JS_KEY</label>
        <input
          id="cds-kakao_js_key"
          type="text"
          className="form-search"
          disabled={!isAdmin}
          value={form.kakao_js_key}
          onChange={(e) => setField('kakao_js_key', e.target.value)}
          placeholder="카카오 JS 키 (클라이언트용)"
        />
      </div>

      <div className="form-row">
        <label className="form-label" htmlFor="cds-calculator_version">CALCULATOR_VERSION</label>
        <input
          id="cds-calculator_version"
          type="text"
          className="form-search"
          disabled={!isAdmin}
          value={form.calculator_version}
          onChange={(e) => setField('calculator_version', e.target.value)}
          placeholder="예: 2.0.0"
        />
      </div>

      <div className="form-row">
        <label className="form-label" htmlFor="cds-law_version">LAW_VERSION</label>
        <input
          id="cds-law_version"
          type="text"
          className="form-search"
          disabled={!isAdmin}
          value={form.law_version}
          onChange={(e) => setField('law_version', e.target.value)}
          placeholder="예: 2026-07"
        />
      </div>

      <div className="form-actions">
        <button
          type="button"
          className="refresh-btn"
          disabled={!isAdmin || saving}
          onClick={handleSave}
        >
          {saving ? '저장 중...' : '💾 저장'}
        </button>
      </div>
      {saveMessage && <p className="status-card__success">{saveMessage}</p>}
      {saveError && <p className="status-card__error">⚠ {saveError}</p>}
    </div>
  )
}