import { useCallback, useEffect, useState } from 'react'
import { getTopicPool, postTopicWpCheck, postTopicRevertCandidate, getCurrentUser } from '../api/client.js'

// CALCMATE-REMAINING-DASHBOARD-KEEP-MIGRATION-01: dashboard.py "🔍 published Topic
// ↔ WP 상태 대조"(1219-1289) 이관. 버튼을 누를 때만 WP GET 1회(주기 실행 없음).
// MISMATCH/WP_POST_NOT_FOUND일 때만 동의 체크 + 클릭으로 published → candidate
// 수동 복귀(서버가 복귀 직전에 다시 대조한다).
const EXPLANATIONS = {
  MATCH: ['success', '✅ MATCH — Topic과 WP 상태가 일치합니다. 조치가 필요 없습니다.'],
  MISMATCH: ['warning', '⚠️ MISMATCH — WP 상태가 기대값과 다릅니다(draft/trash/기타). 실제로 WP에서 내려간 것이 맞는지 사람이 직접 WP에서 확인하세요.'],
  UNEXPECTED_PUBLISHED: ['warning', '⚠️ UNEXPECTED_PUBLISHED — draft로 요청했는데 WP가 공개(publish) 상태입니다. 사람이 직접 공개했을 수 있습니다(candidate 복귀 대상 아님).'],
  WP_POST_NOT_FOUND: ['warning', '⚠️ WP_POST_NOT_FOUND — WP가 404를 반환했습니다(영구 삭제로 추정). 사람이 직접 WP를 확인하세요.'],
  WP_POST_ID_UNAVAILABLE: ['info', 'ℹ️ WP_POST_ID_UNAVAILABLE — 예약 정보에서 WP post id를 찾을 수 없어 대조 자체가 불가능합니다(추측하지 않음).'],
  MODE_UNAVAILABLE: ['info', 'ℹ️ MODE_UNAVAILABLE — 예약 모드를 알 수 없어 기대 WP 상태를 정할 수 없습니다(WP 조회 안 함).'],
  WP_CHECK_ERROR: ['info', 'ℹ️ WP_CHECK_ERROR — WP 조회 중 오류가 발생했습니다(네트워크 등). MATCH/MISMATCH를 단정하지 않습니다 — 잠시 후 다시 시도하세요.'],
  TOPIC_NOT_FOUND: ['error', '❌ TOPIC_NOT_FOUND — 해당 Topic을 찾을 수 없습니다.'],
  TOPIC_NOT_PUBLISHED: ['error', '❌ TOPIC_NOT_PUBLISHED — 대상이 이미 published 상태가 아닙니다(목록이 갱신되지 않았을 수 있습니다).'],
}
const REVERTABLE = ['MISMATCH', 'WP_POST_NOT_FOUND']
const LEVEL_CLASS = { success: 'status-card__success', error: 'status-card__error' }

export default function TopicReconciliationPanel() {
  const [topics, setTopics] = useState([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [isAdmin, setIsAdmin] = useState(false)
  const [topicId, setTopicId] = useState('')
  const [checking, setChecking] = useState(false)
  const [check, setCheck] = useState(null)
  const [checkError, setCheckError] = useState(null)
  const [confirmed, setConfirmed] = useState(false)
  const [reverting, setReverting] = useState(false)
  const [revertOutcome, setRevertOutcome] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    getTopicPool('published').then((res) => {
      const list = res?.success ? (res.data?.topics || []) : []
      setTopics(list)
      setFailed(!res?.success)
      setTopicId((cur) => (list.some((t) => t.topic_id === cur) ? cur : (list[0]?.topic_id || '')))
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
    getCurrentUser().then((res) => setIsAdmin(Boolean(res?.success && res.data?.role === 'admin')))
  }, [load])

  const handleCheck = () => {
    if (!topicId || checking) return
    setChecking(true)
    setCheck(null)
    setCheckError(null)
    setConfirmed(false)
    setRevertOutcome(null)
    postTopicWpCheck(topicId).then((res) => {
      setChecking(false)
      if (res?.success) setCheck({ ...res.data, topic_id: topicId })
      else setCheckError(res?.error?.message || '대조 요청 실패')
    })
  }

  const handleRevert = () => {
    if (!confirmed || reverting) return
    setReverting(true)
    setRevertOutcome(null)
    postTopicRevertCandidate(topicId).then((res) => {
      setReverting(false)
      if (res?.success) {
        setRevertOutcome({ ok: true, message: '✅ candidate로 복귀했습니다.' })
        setCheck(null)
        setConfirmed(false)
        load()
      } else {
        setRevertOutcome({ ok: false, message: `❌ 복귀 실패(상태 변경 없음): ${res?.error?.message || '요청 실패'}` })
      }
    })
  }

  const shownCheck = check && check.topic_id === topicId ? check : null
  const [level, message] = shownCheck
    ? (EXPLANATIONS[shownCheck.status] || ['info', shownCheck.status])
    : [null, null]

  return (
    <div className="status-card">
      <h3 className="status-card__title">🔍 published Topic ↔ WP 상태 대조</h3>
      <p className="status-card__hint">
        현재 &quot;published&quot; 상태인 Topic을 실제 WordPress 게시물 상태와 대조합니다(조회만, 자동 변경 없음).
        주기적으로 자동 실행되지 않으며, 버튼을 누를 때만 WP GET 1회가 발생합니다.
      </p>
      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {!loading && failed && <p className="status-card__error">⚠ API 연결 실패</p>}
      {!loading && !failed && topics.length === 0 && (
        <p className="status-card__hint">현재 published 상태인 Topic이 없습니다.</p>
      )}
      {!loading && !failed && topics.length > 0 && (
        <>
          <div className="form-row">
            <label className="form-label" htmlFor="rc-topic">대상 Topic</label>
            <select id="rc-topic" className="form-select" value={topicId}
                    onChange={(e) => { setTopicId(e.target.value); setConfirmed(false); setRevertOutcome(null) }}>
              {topics.map((t) => (
                <option key={t.topic_id} value={t.topic_id}>{`${t.topic_id} (${t.slug || ''})`}</option>
              ))}
            </select>
          </div>
          <div className="form-actions">
            <button type="button" className="refresh-btn" disabled={!isAdmin || checking || !topicId} onClick={handleCheck}>
              {checking ? '대조 중...' : '🔍 WP 상태 대조'}
            </button>
          </div>
        </>
      )}
      {checkError && <p className="status-card__error">⚠ {checkError}</p>}
      {shownCheck && (
        <>
          <ul className="log-list">
            <li className="log-list__item">- WP post id: <code>{String(shownCheck.wp_post_id ?? 'None')}</code></li>
            <li className="log-list__item">- WP status: <code>{String(shownCheck.wp_status ?? 'None')}</code></li>
            <li className="log-list__item">- 판정: <code>{shownCheck.status}</code></li>
          </ul>
          <p className={LEVEL_CLASS[level] || 'status-card__hint'}>{message}</p>
          {REVERTABLE.includes(shownCheck.status) && (
            <>
              <div className="form-row">
                <label className="form-label" htmlFor="rc-confirm">
                  이 Topic을 다시 candidate로 되돌리는 것에 동의합니다(WP 상태를 직접 확인했으며, 복구/재발행은 별도로 진행합니다).
                </label>
                <input id="rc-confirm" type="checkbox" disabled={!isAdmin}
                       checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
              </div>
              <div className="form-actions">
                <button type="button" className="refresh-btn" disabled={!isAdmin || !confirmed || reverting} onClick={handleRevert}>
                  {reverting ? '복귀 중...' : '⚠️ published → candidate 수동 복귀'}
                </button>
              </div>
            </>
          )}
        </>
      )}
      {revertOutcome && (
        <p className={revertOutcome.ok ? 'status-card__success' : 'status-card__error'}>{revertOutcome.message}</p>
      )}
    </div>
  )
}
