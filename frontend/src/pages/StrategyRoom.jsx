import { useEffect, useState } from 'react'
import { getCurrentUser, postStrategyRoomRun } from '../api/client.js'

// 🧠 전략회의실 — STEP S8: dashboard.py "🧠 전략회의실" 탭(analysis-only, 직접
// 적용 안 함)을 그대로 이관. modules.strategy_room.run_strategy_room()의 반환
// 구조를 그대로 표시한다(임의로 포맷을 재설계하지 않음).
const LIST_SECTIONS = [
  ['🆕 신규 카테고리 후보', 'new_category_candidates'],
  ['📡 RSS 수집원 추천', 'rss_recommendations'],
  ['♻️ 리라이팅 후보', 'rewrite_candidates'],
  ['⏰ 최적 발행 시간대', 'best_publish_time'],
]

const ATE_CONDITIONS = [
  ['애드센스 발행', 'condition_1_adsense_post'],
  ['게시물 수', 'condition_2_post_count'],
  ['CTR', 'condition_3_ctr'],
  ['긍정 추천', 'condition_4_positive_recommendation'],
  ['전체 충족', 'all_met'],
]

function renderItem(item, i) {
  return (
    <li key={i} className="log-list__item" style={{ overflowWrap: 'break-word' }}>
      {typeof item === 'string' ? item : JSON.stringify(item)}
    </li>
  )
}

export default function StrategyRoom() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [running, setRunning] = useState(false)
  const [outcome, setOutcome] = useState(null) // {enabled, result, error} | null

  useEffect(() => {
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
  }, [])

  const handleRun = () => {
    if (running) return
    setRunning(true)
    postStrategyRoomRun().then((res) => {
      setRunning(false)
      if (res?.success) {
        setOutcome(res.data)
      } else {
        setOutcome({ enabled: true, result: {}, error: res?.error?.message || '실행 요청 실패' })
      }
    })
  }

  const data = outcome?.result
  const hasData = data && Object.keys(data).length > 0

  return (
    <div className="page">
      <div className="page__header">
        <h1>🧠 전략회의실</h1>
      </div>
      <p className="status-card__hint">
        AI가 최근 운영 데이터를 분석해 카테고리·RSS·발행시간·수익화 전략을 추천합니다(실행만, 직접 적용 안 함).
      </p>

      {outcome && !outcome.enabled && (
        <p className="status-card__error">
          ⚠️ ENABLE_STRATEGY_ROOM 설정이 꺼져 있습니다. '설정 → 운영 설정'에서 켜주세요.
        </p>
      )}

      <div className="form-actions">
        <button type="button" className="refresh-btn" disabled={!isAdmin || running} onClick={handleRun}>
          {running ? '분석 중...' : '▶ 전략회의실 실행'}
        </button>
      </div>

      {outcome?.error && <p className="status-card__error">⚠ {outcome.error}</p>}

      {outcome && !outcome.error && !hasData && (
        <p className="status-card__error">
          전략회의실이 빈 결과를 반환했습니다. LLM이 올바른 JSON을 반환하지 못했거나 설정이 꺼져 있을 수 있습니다.
          잠시 후 다시 실행해 보세요.
        </p>
      )}

      {hasData && (
        <div className="status-card">
          <h3 className="status-card__title">📝 요약</h3>
          <p style={{ overflowWrap: 'break-word' }}>{data.summary || '(요약 없음)'}</p>

          {data.auto_topic_expansion_eligible && (
            <>
              <p className="panel-section-title">🚦 AUTO_TOPIC_EXPANSION 전환 조건</p>
              <dl className="kv-list">
                {ATE_CONDITIONS.map(([label, key]) => (
                  <div className="kv-list__row" key={key}>
                    <dt>{label}</dt>
                    <dd>{data.auto_topic_expansion_eligible[key] ? '✅' : '❌'}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}

          {LIST_SECTIONS.map(([title, key]) => (
            <div key={key}>
              <p className="panel-section-title">{title}</p>
              {Array.isArray(data[key]) && data[key].length > 0 ? (
                <ul className="log-list">{data[key].map(renderItem)}</ul>
              ) : (
                <p className="status-card__hint">추천 없음</p>
              )}
            </div>
          ))}

          <p className="panel-section-title">💰 수익화 제안</p>
          <p style={{ overflowWrap: 'break-word' }}>
            {data.monetization_suggestions || '추천 없음 (ADSENSE_MODE=pre이면 비활성)'}
          </p>

          <p className="status-card__hint">사용 토큰: {data._tokens ?? '-'}</p>
          <details>
            <summary>🔧 원본 JSON 보기</summary>
            <pre style={{ overflowWrap: 'break-word', whiteSpace: 'pre-wrap' }}>
              {JSON.stringify(data, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </div>
  )
}
