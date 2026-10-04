import { useEffect, useState } from 'react'
import {
  postAiSuggestIdea,
  postAiSuggestMode,
  postAiSuggestTier,
  postAiTier2bDetect,
} from '../api/client.js'

// CALCMATE-STREAMLIT-REMAINING-MIGRATION-APP-FACTORY-02: dashboard.py App Factory
// "기본 정보" 영역의 AI 보조(L1940-2071) — 키워드/자유 아이디어 제안, Mode AI 추천,
// Tier2-B 키워드 경고(서버 규칙), Tier AI 추천, Tier 안내 문구. 모든 추천은 표시/입력
// 보조일 뿐이며 생성·저장·배포를 실행하지 않는다(최종 선택은 항상 사람이 한다).

const CONF_NOTE = {
  medium: '⚠️ 확신도 보통 —',
  low: '🚨 판단 불확실 —',
}

export const TIER2B_DETECT_DEBOUNCE_MS = 400

export default function AppFactoryAiAssist({
  isAdmin, name, category, description, tierInt, disabled = false,
  onIdea, onTierSuggested, detectDebounceMs = TIER2B_DETECT_DEBOUNCE_MS,
}) {
  const [keyword, setKeyword] = useState('')
  const [ideaLoading, setIdeaLoading] = useState(false)
  const [ideaError, setIdeaError] = useState(null)
  const [modeLoading, setModeLoading] = useState(false)
  const [modeSuggest, setModeSuggest] = useState(null)
  const [tierLoading, setTierLoading] = useState(false)
  const [tierSuggest, setTierSuggest] = useState(null)
  const [nameWarning, setNameWarning] = useState(null)
  const [tier2bDetected, setTier2bDetected] = useState(false)

  const off = !isAdmin || disabled

  // Tier2-B 키워드 사전 감지(dashboard.py L2010 — 이름/설명 입력 시 자동 표시).
  useEffect(() => {
    if (!isAdmin || !name?.trim()) {
      setTier2bDetected(false)
      return undefined
    }
    let alive = true
    const t = setTimeout(() => {
      postAiTier2bDetect({ name, description: description || '' }).then((res) => {
        if (alive) setTier2bDetected(Boolean(res?.success && res.data?.detected))
      })
    }, detectDebounceMs)
    return () => { alive = false; clearTimeout(t) }
  }, [isAdmin, name, description, detectDebounceMs])

  async function handleIdea(useKeyword) {
    setIdeaLoading(true)
    setIdeaError(null)
    const res = await postAiSuggestIdea(useKeyword ? keyword : null)
    setIdeaLoading(false)
    if (res?.success) onIdea?.(res.data)
    else setIdeaError(res?.error?.message || 'AI 제안 실패(직접 입력해주세요).')
  }

  async function handleMode() {
    if (!name?.trim()) { setNameWarning('계산기명을 먼저 입력하세요.'); return }
    setNameWarning(null)
    setModeLoading(true)
    const res = await postAiSuggestMode({ name, category: category || '', description: description || '' })
    setModeLoading(false)
    if (res?.success) setModeSuggest(res.data)
    else setModeSuggest({ error: res?.error?.message || 'Mode 추천 실패(직접 선택)' })
  }

  async function handleTier() {
    if (!name?.trim()) { setNameWarning('계산기명을 먼저 입력하세요.'); return }
    setNameWarning(null)
    setTierLoading(true)
    const res = await postAiSuggestTier({ name, description: description || '' })
    setTierLoading(false)
    if (res?.success) {
      setTierSuggest(res.data)
      onTierSuggested?.(res.data)   // Tier 기본값 + Tier2-B 신호(신뢰도와 무관) 반영
    } else {
      setTierSuggest({ error: res?.error?.message || 'Tier 추천 실패(직접 선택)' })
    }
  }

  const modeLabel = modeSuggest?.mode === 'B' ? 'Mode B — 📋 Contract 기반 생성' : 'Mode A — 🏭 자동 생성'

  return (
    <div className="app-factory-ai-assist">
      <div className="form-row">
        <label className="form-label" htmlFor="af-keyword">키워드로 아이디어 생성</label>
        <input id="af-keyword" className="form-search" value={keyword} disabled={off}
               placeholder="예: 육아휴직, 4대보험, 연차" onChange={(e) => setKeyword(e.target.value)} />
        <button type="button" className="refresh-btn" disabled={off || ideaLoading} onClick={() => handleIdea(true)}>
          🔍 키워드로 제안
        </button>
        <button type="button" className="refresh-btn" disabled={off || ideaLoading} onClick={() => handleIdea(false)}>
          {ideaLoading ? '제안 중...' : '💡 AI 아이디어 제안'}
        </button>
      </div>
      {ideaError && <p className="status-card__error">⚠ {ideaError}</p>}

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={off || modeLoading} onClick={handleMode}>
          {modeLoading ? 'Mode 분석 중...' : '💡 Mode AI 추천'}
        </button>
        <button type="button" className="refresh-btn" disabled={off || tierLoading} onClick={handleTier}>
          {tierLoading ? 'Tier 분석 중...' : '💡 Tier AI 추천'}
        </button>
      </div>
      {nameWarning && <p className="status-card__error">⚠ {nameWarning}</p>}

      {modeSuggest && (modeSuggest.error
        ? <p className="status-card__error">⚠ {modeSuggest.error}</p>
        : (
          <div>
            <p className={modeSuggest.confidence === 'high' ? 'status-card__success' : 'status-card__hint'}>
              {modeSuggest.confidence === 'high'
                ? `✅ AI 추천: ${modeLabel} (확신도: HIGH)`
                : `💡 AI 추천: ${modeLabel} ${CONF_NOTE[modeSuggest.confidence] || ''}`}
              {' '}이유: {modeSuggest.reason}
            </p>
            <p className="status-card__hint">
              참고용 추천입니다. 생성 방식은 직접 선택하세요 — legal_refs·test_cases는 이 추천과 무관하게 항상 사람이 직접 확정합니다.
            </p>
          </div>
        ))}

      {tier2bDetected && (
        <p className="status-card__error" data-testid="tier2b-warning">
          ⚠️ 이름/설명에 날짜·기간 관련 키워드가 감지됩니다. Tier2-B(날짜형) 가능성을 직접 확인하세요.
        </p>
      )}

      {tierSuggest && (tierSuggest.error
        ? <p className="status-card__error">⚠ {tierSuggest.error}</p>
        : (
          <p className={tierSuggest.confidence === 'high' ? 'status-card__success' : 'status-card__hint'}>
            {tierSuggest.confidence === 'high'
              ? `✅ AI 추천: ${tierSuggest.tier} (신뢰도: HIGH) — 높은 확신도로 자동 선택되었습니다. 필요하면 직접 변경할 수 있습니다.`
              : `💡 AI 추천: ${tierSuggest.tier} ${{ medium: '⚠️ 확신도 보통 —', low: '🚨 분류 불확실 —' }[tierSuggest.confidence] || ''}`}
            {' '}이유: {tierSuggest.reason}
          </p>
        ))}

      {tierInt === 1
        ? <p className="status-card__hint">ℹ️ Tier1은 생성 후 계산 로직 + legal 근거 모두 사람이 검증해야 합니다. READY 전환 전까지 index/sitemap 비노출.</p>
        : <p className="status-card__hint">ℹ️ Tier2는 생성 후 계산 정확성 검증 + legal 검증 완료 시 READY 전환 가능.</p>}
    </div>
  )
}
