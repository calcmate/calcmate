import { useState, useCallback } from 'react'
import {
  postCreateSite,
  putUpdateSite,
  postSaveOverride,
  getCurrentUser,
} from '../api/client.js'
import {
  Step1Profile,
  Step2Platform,
  Step3Features,
  Step4Settings,
  Step5Create,
} from '../components/SiteWizardSteps.jsx'
import { DEFAULT_AI } from '../components/SiteManagementPanel.jsx'

const STEPS = [
  { key: 'profile', label: '1. Profile', component: Step1Profile },
  { key: 'platform', label: '2. Platform', component: Step2Platform },
  { key: 'features', label: '3. Features', component: Step3Features },
  { key: 'settings', label: '4. Settings', component: Step4Settings },
  { key: 'create', label: '5. Pipeline / Create', component: Step5Create },
]

const INITIAL_DATA = {
  site_name: '',
  domain: '',
  wp_url: '',
  platforms: [],
  wp_user: '',
  wp_pw: '',
  features: {
    wordpress: [],
    calculator: [],
    common: [],
  },
  research_ai: DEFAULT_AI.research_ai,
  writing_ai: DEFAULT_AI.writing_ai,
  review_ai: DEFAULT_AI.review_ai,
  daily_override: 3,
}

export default function SiteWizard() {
  const [currentStepIndex, setCurrentStepIndex] = useState(0)
  const [wizardData, setWizardData] = useState(INITIAL_DATA)
  const [errors, setErrors] = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [completed, setCompleted] = useState(false)
  const [createdSite, setCreatedSite] = useState(null)
  const [user, setUser] = useState(null)
  const [isAdmin, setIsAdmin] = useState(false)

  useEffect(() => {
    getCurrentUser().then((res) => {
      if (res?.success && res.data) {
        setUser(res.data)
        setIsAdmin(res.data.role === 'admin')
      }
    })
  }, [])

  const currentStep = STEPS[currentStepIndex]
  const StepComponent = currentStep.component

  const handleNext = useCallback(() => {
    if (currentStepIndex < STEPS.length - 1) {
      setCurrentStepIndex(currentStepIndex + 1)
    }
  }, [currentStepIndex])

  const handleBack = useCallback(() => {
    if (currentStepIndex > 0) {
      setCurrentStepIndex(currentStepIndex - 1)
    }
  }, [currentStepIndex])

  const handleCreate = useCallback(async () => {
    if (!isAdmin) {
      setSubmitError('admin 권한이 필요합니다.')
      return
    }

    setSubmitting(true)
    setSubmitError(null)

    try {
      // Step 1: Create site via POST /api/sites
      const platforms = wizardData.platforms || []
      const needsWp = platforms.includes('WordPress')

      const createPayload = {
        type_label: needsWp ? '사용자정의' : '계산기',
        site_name: wizardData.site_name,
        domain: wizardData.domain,
        category: '',
        platforms,
        wp_url: wizardData.wp_url || '',
        wp_user: wizardData.wp_user || '',
        wp_app_password: wizardData.wp_pw || '',
        rss_sources: '',
        research_ai: wizardData.research_ai,
        writing_ai: wizardData.writing_ai,
        review_ai: wizardData.review_ai,
      }

      const createRes = await postCreateSite(createPayload)

      if (!createRes?.success) {
        throw new Error(createRes?.error?.message || '사이트 생성 실패')
      }

      const siteId = createRes.data?.site_id
      if (!siteId) {
        throw new Error('생성된 사이트 ID를 받지 못했습니다.')
      }

      // Step 2: Save override fields (daily_override, calc_active, AI roles)
      // Note: platforms and features are saved internally by create_site service
      // but daily_override and calc_active need the override endpoint
      const overridePayload = {
        research_ai: wizardData.research_ai,
        writing_ai: wizardData.writing_ai,
        review_ai: wizardData.review_ai,
        daily_override: String(wizardData.daily_override || ''),
        calc_active: [], // Will be populated from features if needed
      }

      // Only save override if there are meaningful values
      const hasOverrideValues = Object.values(overridePayload).some(
        (v) => v !== '' && v !== 'gemini_flash' && v !== 'gpt4o' && v !== 'claude_sonnet' && v !== '3'
      )

      if (hasOverrideValues) {
        const overrideRes = await postSaveOverride(siteId, overridePayload)
        if (!overrideRes?.success) {
          console.warn('Override 저장 경고:', overrideRes?.error?.message)
          // Don't fail the whole flow for override warning
        }
      }

      setCreatedSite(createRes.data)
      setCompleted(true)
    } catch (err) {
      setSubmitError(err.message || '사이트 생성 중 오류가 발생했습니다.')
    } finally {
      setSubmitting(false)
    }
  }, [wizardData, isAdmin])

  const renderStep = () => {
    const commonProps = {
      data: wizardData,
      setData: setWizardData,
      errors,
      setErrors,
      onNext: handleNext,
      onBack: handleBack,
    }

    if (currentStep.key === 'create') {
      return (
        <Step5Create
          {...commonProps}
          onCreate={handleCreate}
          submitting={submitting}
          submitError={submitError}
        />
      )
    }

    return <currentStep.component {...commonProps} />
  }

  const progressPercent = ((currentStepIndex + 1) / STEPS.length) * 100

  return (
    <div className="page site-wizard-page">
      <div className="page__header">
        <h1>🧙 사이트 마법사</h1>
      </div>

      <div className="wizard-progress" role="progressbar" aria-valuenow={progressPercent} aria-valuemin={0} aria-valuemax={100}>
        <div className="wizard-progress__bar">
          <div
            className="wizard-progress__fill"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
        <div className="wizard-progress__steps">
          {STEPS.map((step, idx) => (
            <div
              key={step.key}
              className={`wizard-progress__step ${idx === currentStepIndex ? 'wizard-progress__step--current' : ''} ${idx < currentStepIndex ? 'wizard-progress__step--completed' : ''}`}
            >
              <span className="wizard-progress__step-number">{idx + 1}</span>
              <span className="wizard-progress__step-label">{step.label}</span>
            </div>
          ))}
        </div>
      </div>

      {completed && createdSite && (
        <div className="wizard-complete status-card status-card--success">
          <h3 className="status-card__title">🎉 사이트 생성 완료</h3>
          <p className="status-card__hint">
            <strong>{createdSite.site_name}</strong> ({createdSite.domain}) 사이트가 성공적으로 생성되었습니다.
          </p>
          <div className="wizard-complete__details">
            <p>Site ID: {createdSite.site_id}</p>
            <p>Type: {createdSite.site_type}</p>
            <p>Status: {createdSite.status}</p>
            <p>Platforms: {createdSite.platforms?.join(', ') || '없음'}</p>
          </div>
          <div className="wizard-complete__actions">
            <button
              type="button"
              className="refresh-btn"
              onClick={() => window.location.href = '/sites'}
            >
              사이트 관리 페이지로 이동
            </button>
            <button
              type="button"
              className="refresh-btn"
              onClick={() => {
                setCurrentStepIndex(0)
                setWizardData(INITIAL_DATA)
                setErrors({})
                setCompleted(false)
                setCreatedSite(null)
              }}
            >
              새 사이트 추가
            </button>
          </div>
        </div>
      )}

      {!completed && (
        <div className="wizard-content status-card">
          {renderStep()}
        </div>
      )}

      {!isAdmin && !completed && (
        <div className="wizard-notice status-card__hint">
          현재 admin 권한이 없습니다. 저장하려면 admin으로 로그인하세요.
        </div>
      )}
    </div>
  )
}