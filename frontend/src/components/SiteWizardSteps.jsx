import { useState, useEffect } from 'react'
import {
  TYPE_LABELS,
  AI_PROFILES,
  WP_FEATS,
  CALC_FEATS,
  COMMON_FEATS,
  GLOB,
  DEFAULT_AI,
} from './SiteManagementPanel.jsx'

// ── STEP 1: Profile ────────────────────────────────────────────────────────────
export function Step1Profile({ data, setData, errors, setErrors, onNext }) {
  const validate = () => {
    const newErrors = {}
    if (!data.site_name?.trim()) newErrors.site_name = '사이트명은 필수입니다.'
    if (!data.domain?.trim()) newErrors.domain = '도메인은 필수입니다.'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleChange = (field, value) => {
    setData((d) => ({ ...d, [field]: value }))
    if (errors[field]) setErrors((e) => ({ ...e, [field]: null }))
  }

  return (
    <div className="wizard-step">
      <h3 className="wizard-step__title">Step 1 · Site Profile</h3>
      <p className="wizard-step__hint">사이트 기본 정보를 입력하세요.</p>

      <div className="form-row">
        <label className="form-label" htmlFor="w_site_name">
          사이트명 <span className="required">*</span>
        </label>
        <input
          id="w_site_name"
          type="text"
          className={`form-search ${errors.site_name ? 'form-search--error' : ''}`}
          value={data.site_name || ''}
          onChange={(e) => handleChange('site_name', e.target.value)}
          placeholder="예: 내 블로그"
        />
        {errors.site_name && <span className="form-error">{errors.site_name}</span>}
      </div>

      <div className="form-row">
        <label className="form-label" htmlFor="w_domain">
          도메인 <span className="required">*</span>
        </label>
        <input
          id="w_domain"
          type="text"
          className={`form-search ${errors.domain ? 'form-search--error' : ''}`}
          value={data.domain || ''}
          onChange={(e) => handleChange('domain', e.target.value)}
          placeholder="example.com"
        />
        {errors.domain && <span className="form-error">{errors.domain}</span>}
      </div>

      <div className="form-row">
        <label className="form-label" htmlFor="w_wp_url">WordPress URL (선택)</label>
        <input
          id="w_wp_url"
          type="text"
          className="form-search"
          value={data.wp_url || ''}
          onChange={(e) => handleChange('wp_url', e.target.value)}
          placeholder="https://yourblog.com"
        />
        <span className="form-hint">WordPress를 사용하는 경우에만 입력하세요.</span>
      </div>

      <div className="wizard-actions">
        <button
          type="button"
          className="refresh-btn wizard-btn--primary"
          onClick={() => validate() && onNext()}
        >
          다음 →
        </button>
      </div>
    </div>
  )
}

// ── STEP 2: Platform ──────────────────────────────────────────────────────────
export function Step2Platform({ data, setData, errors, setErrors, onNext, onBack }) {
  const validate = () => {
    const newErrors = {}
    if (!data.platforms || data.platforms.length === 0) {
      newErrors.platforms = '최소 하나의 플랫폼을 선택하세요.'
    }
    if (data.platforms?.includes('WordPress')) {
      if (!data.wp_url?.trim()) newErrors.wp_url = 'WordPress URL은 필수입니다.'
      if (!data.wp_user?.trim()) newErrors.wp_user = 'WordPress ID는 필수입니다.'
      if (!data.wp_pw?.trim()) newErrors.wp_pw = 'App Password는 필수입니다.'
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleChange = (field, value) => {
    setData((d) => ({ ...d, [field]: value }))
    if (errors[field]) setErrors((e) => ({ ...e, [field]: null }))
  }

  const handlePlatformChange = (platform, checked) => {
    const current = data.platforms || []
    const next = checked
      ? [...current, platform]
      : current.filter((p) => p !== platform)
    setData((d) => ({ ...d, platforms: next }))
    if (errors.platforms) setErrors((e) => ({ ...e, platforms: null }))
  }

  const handleWpCredentialChange = (field, value) => {
    setData((d) => ({ ...d, [field]: value }))
    if (errors[field]) setErrors((e) => ({ ...e, [field]: null }))
  }

  return (
    <div className="wizard-step">
      <h3 className="wizard-step__title">Step 2 · Platform 선택</h3>
      <p className="wizard-step__hint">사이트가 사용할 플랫폼을 선택하세요. 복수 선택 가능합니다.</p>

      <div className="form-row form-row--checkbox">
        <label>
          <input
            type="checkbox"
            checked={data.platforms?.includes('WordPress') || false}
            onChange={(e) => handlePlatformChange('WordPress', e.target.checked)}
          />
          {' '}WordPress
        </label>
        <label>
          <input
            type="checkbox"
            checked={data.platforms?.includes('Calculator') || false}
            onChange={(e) => handlePlatformChange('Calculator', e.target.checked)}
          />
          {' '}Calculator
        </label>
      </div>

      {data.platforms?.includes('WordPress') && (
        <div className="wizard-step__section">
          <p className="wizard-step__hint"><strong>WordPress 자격증명 (필수)</strong></p>

          <div className="form-row">
            <label className="form-label" htmlFor="w_wp_url2">WordPress URL *</label>
            <input
              id="w_wp_url2"
              type="text"
              className={`form-search ${errors.wp_url ? 'form-search--error' : ''}`}
              value={data.wp_url || ''}
              onChange={(e) => handleWpCredentialChange('wp_url', e.target.value)}
              placeholder="https://yourblog.com"
            />
            {errors.wp_url && <span className="form-error">{errors.wp_url}</span>}
          </div>

          <div className="form-row">
            <label className="form-label" htmlFor="w_wp_user">WordPress ID *</label>
            <input
              id="w_wp_user"
              type="text"
              className={`form-search ${errors.wp_user ? 'form-search--error' : ''}`}
              value={data.wp_user || ''}
              onChange={(e) => handleWpCredentialChange('wp_user', e.target.value)}
              placeholder="admin"
            />
            {errors.wp_user && <span className="form-error">{errors.wp_user}</span>}
          </div>

          <div className="form-row">
            <label className="form-label" htmlFor="w_wp_pw">App Password *</label>
            <input
              id="w_wp_pw"
              type="password"
              className={`form-search ${errors.wp_pw ? 'form-search--error' : ''}`}
              value={data.wp_pw || ''}
              onChange={(e) => handleWpCredentialChange('wp_pw', e.target.value)}
              placeholder="xxxx xxxx xxxx xxxx"
            />
            {errors.wp_pw && <span className="form-error">{errors.wp_pw}</span>}
            <span className="form-hint">WordPress 관리자 → 사용자 → 앱 비밀번호에서 생성</span>
          </div>
        </div>
      )}

      <div className="wizard-actions">
        <button type="button" className="refresh-btn" onClick={onBack}>
          ← 이전
        </button>
        <button
          type="button"
          className="refresh-btn wizard-btn--primary"
          onClick={() => validate() && onNext()}
        >
          다음 →
        </button>
      </div>
    </div>
  )
}

// ── STEP 3: Features ──────────────────────────────────────────────────────────
export function Step3Features({ data, setData, onNext, onBack }) {
  const handleFeatureChange = (group, feature, checked) => {
    const current = data.features?.[group] || []
    const next = checked
      ? [...current, feature]
      : current.filter((f) => f !== feature)
    setData((d) => ({
      ...d,
      features: { ...d.features, [group]: next },
    }))
  }

  return (
    <div className="wizard-step">
      <h3 className="wizard-step__title">Step 3 · Feature 선택</h3>
      <p className="wizard-step__hint">플랫폼별로 활성화할 기능을 선택하세요. 기본값은 모두 활성화입니다.</p>

      {data.platforms?.includes('WordPress') && (
        <div className="wizard-step__section">
          <h4 className="wizard-step__section-title">WordPress Features</h4>
          <div className="form-row form-row--checkbox">
            {WP_FEATS.map((feat) => (
              <label key={feat}>
                <input
                  type="checkbox"
                  checked={data.features?.wordpress?.includes(feat) ?? true}
                  onChange={(e) => handleFeatureChange('wordpress', feat, e.target.checked)}
                />
                {' '}{feat}
              </label>
            ))}
          </div>
        </div>
      )}

      {data.platforms?.includes('Calculator') && (
        <div className="wizard-step__section">
          <h4 className="wizard-step__section-title">Calculator Features</h4>
          <div className="form-row form-row--checkbox">
            {CALC_FEATS.map((feat) => (
              <label key={feat}>
                <input
                  type="checkbox"
                  checked={data.features?.calculator?.includes(feat) ?? true}
                  onChange={(e) => handleFeatureChange('calculator', feat, e.target.checked)}
                />
                {' '}{feat}
              </label>
            ))}
          </div>
        </div>
      )}

      <div className="wizard-step__section">
        <h4 className="wizard-step__section-title">공통 Features</h4>
        <div className="form-row form-row--checkbox">
          {COMMON_FEATS.map((feat) => (
            <label key={feat}>
              <input
                type="checkbox"
                checked={data.features?.common?.includes(feat) ?? true}
                onChange={(e) => handleFeatureChange('common', feat, e.target.checked)}
              />
              {' '}{feat}
            </label>
          ))}
        </div>
      </div>

      <div className="wizard-actions">
        <button type="button" className="refresh-btn" onClick={onBack}>
          ← 이전
        </button>
        <button
          type="button"
          className="refresh-btn wizard-btn--primary"
          onClick={onNext}
        >
          다음 →
        </button>
      </div>
    </div>
  )
}

// ── STEP 4: Settings ──────────────────────────────────────────────────────────
export function Step4Settings({ data, setData, errors, setErrors, onNext, onBack }) {
  const handleChange = (field, value) => {
    setData((d) => ({ ...d, [field]: value }))
    if (errors[field]) setErrors((e) => ({ ...e, [field]: null }))
  }

  const validate = () => {
    // All fields optional in this step
    return true
  }

  return (
    <div className="wizard-step">
      <h3 className="wizard-step__title">Step 4 · Settings (Override)</h3>
      <p className="wizard-step__hint">미변경 시 Global 기본값이 적용됩니다. 상세 항목은 추후 Site Settings에서 편집 가능합니다.</p>

      <div className="form-row">
        <label className="form-label" htmlFor="w_research_ai">Research AI</label>
        <select
          id="w_research_ai"
          className="form-select"
          value={data.research_ai || DEFAULT_AI.research_ai}
          onChange={(e) => handleChange('research_ai', e.target.value)}
        >
          {AI_PROFILES.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      <div className="form-row">
        <label className="form-label" htmlFor="w_writing_ai">Writing AI</label>
        <select
          id="w_writing_ai"
          className="form-select"
          value={data.writing_ai || DEFAULT_AI.writing_ai}
          onChange={(e) => handleChange('writing_ai', e.target.value)}
        >
          {AI_PROFILES.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      <div className="form-row">
        <label className="form-label" htmlFor="w_review_ai">Review AI</label>
        <select
          id="w_review_ai"
          className="form-select"
          value={data.review_ai || DEFAULT_AI.review_ai}
          onChange={(e) => handleChange('review_ai', e.target.value)}
        >
          {AI_PROFILES.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      <div className="form-row">
        <label className="form-label" htmlFor="w_daily_override">일 발행수 (Override)</label>
        <input
          id="w_daily_override"
          type="number"
          min="1"
          max="20"
          className={`form-number ${errors.daily_override ? 'form-number--error' : ''}`}
          value={data.daily_override || 3}
          onChange={(e) => handleChange('daily_override', parseInt(e.target.value) || 0)}
        />
      </div>

      <div className="wizard-actions">
        <button type="button" className="refresh-btn" onClick={onBack}>
          ← 이전
        </button>
        <button
          type="button"
          className="refresh-btn wizard-btn--primary"
          onClick={() => validate() && onNext()}
        >
          다음 →
        </button>
      </div>
    </div>
  )
}

// ── STEP 5: Pipeline / Create ─────────────────────────────────────────────────
export function Step5Create({ data, onBack, onCreate, submitting, submitError }) {
  const platforms = data.platforms || []
  const features = data.features || {}

  let pipeMsg = 'Platform 미선택 — 나중에 Platform을 추가하면 Pipeline이 결정됩니다.'
  if (platforms.includes('Calculator') && platforms.includes('WordPress')) {
    pipeMsg = '이 Site는 <strong>Calculator Pipeline → WordPress 발행</strong> 순서로 실행됩니다.'
  } else if (platforms.includes('Calculator')) {
    pipeMsg = '이 Site는 <strong>Calculator Pipeline</strong>으로 실행됩니다.'
  } else if (platforms.includes('WordPress')) {
    pipeMsg = '이 Site는 <strong>RSS/정책 Pipeline → WordPress 발행</strong>으로 실행됩니다.'
  }

  const summary = {
    profile: { name: data.site_name, domain: data.domain },
    platforms,
    features,
    override: {
      research_ai: data.research_ai,
      writing_ai: data.writing_ai,
      review_ai: data.review_ai,
      daily: data.daily_override,
    },
  }

  return (
    <div className="wizard-step">
      <h3 className="wizard-step__title">Step 5 · Pipeline 연결 확인 / 생성</h3>

      <div className="wizard-step__section">
        <p dangerouslySetInnerHTML={{ __html: pipeMsg }} />
      </div>

      <div className="wizard-step__section">
        <h4>입력값 요약</h4>
        <pre className="wizard-summary">{JSON.stringify(summary, null, 2)}</pre>
      </div>

      {submitError && (
        <div className="status-card__error" style={{ marginTop: '1rem' }}>
          ⚠ {submitError}
        </div>
      )}

      <div className="wizard-actions">
        <button type="button" className="refresh-btn" onClick={onBack}>
          ← 이전
        </button>
        <button
          type="button"
          className="refresh-btn wizard-btn--primary"
          onClick={onCreate}
          disabled={submitting}
        >
          {submitting ? '생성 중...' : '✅ 사이트 생성'}
        </button>
      </div>
    </div>
  )
}