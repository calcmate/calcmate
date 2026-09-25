import { useCallback, useEffect, useState } from 'react'
import {
  getPublishingPolicy,
  patchPublishingPolicy,
  getAutoPublishing,
  patchAutoPublishing,
  getPublishingPolicyPreview,
  getCurrentUser,
} from '../api/client.js'

// 🤖 Publishing Policy — CALCMATE-BLOG-PUBLISHING-POLICY-FASTAPI-REACT-
// CONNECTION-IMPLEMENT-01. dashboard.py(Streamlit, "🤖 자동 콘텐츠 발행 정책",
// dashboard.py:1164-1362)의 기능 계약을 React로 재현한다. 랜덤 시간 생성/
// 검증 로직은 이 파일에 없다 — 전부 modules/publishing_policy.py(서버 측,
// api/services/publishing_policy_service.py 경유)의 책임이며, 이 컴포넌트는
// 화면 상태(weekday별 count/time_ranges 배열)만 관리하고 저장/미리보기 시
// 서버에 그대로 위임한다. 기존 BlogSchedulerPanel(Golden10)과는 완전히
// 별개 정책이며 그 컴포넌트를 전혀 참조/수정하지 않는다.

const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
const WEEKDAY_LABELS = {
  mon: '월요일', tue: '화요일', wed: '수요일', thu: '목요일',
  fri: '금요일', sat: '토요일', sun: '일요일',
}

function emptyRange() {
  return { start: '09:00', end: '18:00' }
}

function emptyDayEntry() {
  return { count: 0, time_ranges: [] }
}

export default function PublishingPolicyPanel() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)

  const [weekdays, setWeekdays] = useState({})
  const [maxPending, setMaxPending] = useState(10)

  const [autoPubEnabled, setAutoPubEnabled] = useState(false)

  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)

  const [autoPubSaving, setAutoPubSaving] = useState(false)
  const [autoPubMessage, setAutoPubMessage] = useState(null)
  const [autoPubError, setAutoPubError] = useState(null)

  const [preview, setPreview] = useState(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError(false)
    Promise.all([getPublishingPolicy(), getAutoPublishing(), getCurrentUser()]).then(
      ([p, a, u]) => {
        setLoadError(!p?.success || !a?.success)
        setIsAdmin(Boolean(u?.success && u.data?.role === 'admin'))
        if (p?.success && p.data) {
          setWeekdays(p.data.weekdays || {})
          setMaxPending(p.data.max_pending_reservations ?? 10)
        }
        if (a?.success && a.data) {
          setAutoPubEnabled(Boolean(a.data.enabled))
        }
        setLoading(false)
      }
    )
  }, [])

  useEffect(() => {
    load()
  }, [load])

  function updateCount(day, nextCount) {
    const count = Math.max(0, Math.min(10, Number(nextCount) || 0))
    setWeekdays((w) => {
      const entry = w[day] || emptyDayEntry()
      const ranges = [...entry.time_ranges]
      while (ranges.length < count) ranges.push(emptyRange())
      while (ranges.length > count) ranges.pop()
      return { ...w, [day]: { count, time_ranges: ranges } }
    })
  }

  function updateRange(day, index, field, value) {
    setWeekdays((w) => {
      const entry = w[day] || emptyDayEntry()
      const ranges = entry.time_ranges.map((r, i) => (i === index ? { ...r, [field]: value } : r))
      return { ...w, [day]: { ...entry, time_ranges: ranges } }
    })
  }

  async function handleSavePolicy() {
    setSaving(true)
    setSaveMessage(null)
    setSaveError(null)
    const res = await patchPublishingPolicy({
      timezone: 'Asia/Seoul',
      weekdays,
      max_pending_reservations: Number(maxPending),
    })
    setSaving(false)
    if (res.success) {
      setSaveMessage('✅ Publishing Policy 저장 완료')
      load()
    } else {
      setSaveError(res.error?.message || '저장 실패')
    }
  }

  async function handleSaveAutoPub() {
    setAutoPubSaving(true)
    setAutoPubMessage(null)
    setAutoPubError(null)
    const res = await patchAutoPublishing({ enabled: autoPubEnabled })
    setAutoPubSaving(false)
    if (res.success) {
      setAutoPubMessage(`✅ 저장 완료 · enabled=${autoPubEnabled}`)
    } else {
      setAutoPubError(res.error?.message || '저장 실패')
    }
  }

  async function handlePreview() {
    setPreviewLoading(true)
    setPreviewError(null)
    const res = await getPublishingPolicyPreview()
    setPreviewLoading(false)
    if (res.success) {
      setPreview(res.data)
    } else {
      setPreview(null)
      setPreviewError(res.error?.message || '미리보기 실패')
    }
  }

  return (
    <div className="status-card">
      <h3 className="status-card__title">🤖 자동 콘텐츠 발행 정책 (Publishing Policy)</h3>
      <p className="status-card__hint">
        Topic Pool 기반 자동 콘텐츠 발행 전용 설정입니다. Golden10 Blog Schedule과는
        완전히 별개이며, 여기서 저장해도 기존 Blog Schedule 동작에는 영향이 없습니다.
      </p>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {!loading && loadError && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !loadError && (
        <>
          <hr className="panel-divider" />
          <p className="panel-section-title">전체 자동 발행 (AUTO_PUBLISHING)</p>
          <div className="form-row">
            <label className="form-check">
              <input
                type="checkbox"
                checked={autoPubEnabled}
                disabled={!isAdmin}
                onChange={(e) => setAutoPubEnabled(e.target.checked)}
              />
              자동 발행 사용(enabled) — OFF면 Weekly Planner가 신규 예약을 생성하지 않습니다.
            </label>
          </div>
          <div className="form-actions">
            <button
              type="button"
              className="refresh-btn"
              onClick={handleSaveAutoPub}
              disabled={!isAdmin || autoPubSaving}
            >
              {autoPubSaving ? '저장 중...' : '💾 자동 발행 스위치 저장'}
            </button>
          </div>
          {autoPubMessage && <p className="status-card__success">{autoPubMessage}</p>}
          {autoPubError && <p className="status-card__error">⚠ {autoPubError}</p>}
          {!isAdmin && (
            <p className="status-card__hint">저장에는 관리자 권한이 필요합니다(조회는 누구나 가능).</p>
          )}

          <hr className="panel-divider" />
          <p className="panel-section-title">요일별 발행 설정 (timezone: Asia/Seoul)</p>

          {WEEKDAYS.map((day) => {
            const entry = weekdays[day] || emptyDayEntry()
            return (
              <div className="form-row form-row--slot" key={day}>
                <span className="form-label">{WEEKDAY_LABELS[day]}</span>
                <div className="form-row">
                  <label className="form-label" htmlFor={`pp-count-${day}`}>발행 개수</label>
                  <input
                    id={`pp-count-${day}`}
                    className="form-number"
                    type="number"
                    min={0}
                    max={10}
                    value={entry.count}
                    disabled={!isAdmin}
                    onChange={(e) => updateCount(day, e.target.value)}
                  />
                </div>
                {entry.count === 0 && <p className="status-card__hint">발행 없음</p>}
                {entry.time_ranges.map((range, i) => (
                  <div className="form-row form-row--slot" key={i}>
                    <span className="form-label">{i + 1}번째 글</span>
                    <div className="slot-inputs">
                      <input
                        type="time"
                        aria-label={`pp-${day}-${i}-start`}
                        className="form-time"
                        value={range.start}
                        disabled={!isAdmin}
                        onChange={(e) => updateRange(day, i, 'start', e.target.value)}
                      />
                      <span aria-hidden="true">—</span>
                      <input
                        type="time"
                        aria-label={`pp-${day}-${i}-end`}
                        className="form-time"
                        value={range.end}
                        disabled={!isAdmin}
                        onChange={(e) => updateRange(day, i, 'end', e.target.value)}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )
          })}

          <div className="form-row">
            <label className="form-label" htmlFor="pp-max-pending">
              동시 대기 가능한 예약 수 (max_pending_reservations)
            </label>
            <input
              id="pp-max-pending"
              className="form-number"
              type="number"
              min={1}
              max={100}
              value={maxPending}
              disabled={!isAdmin}
              onChange={(e) => setMaxPending(e.target.value)}
            />
          </div>

          <div className="form-actions">
            <button
              type="button"
              className="refresh-btn"
              onClick={handleSavePolicy}
              disabled={!isAdmin || saving}
            >
              {saving ? '저장 중...' : '💾 Publishing Policy 저장'}
            </button>
          </div>
          {saveMessage && <p className="status-card__success">{saveMessage}</p>}
          {saveError && <p className="status-card__error">⚠ {saveError}</p>}

          <hr className="panel-divider" />
          <p className="panel-section-title">🔍 미리보기 (저장된 정책 기준, 앞으로 7일)</p>
          <p className="status-card__hint">
            실제 예약을 생성하지 않으며 DB/WP/AI를 호출하지 않습니다. 편집 중인 값이
            아직 저장 전이면 마지막으로 저장된 정책 기준으로 계산됩니다.
          </p>
          <div className="form-actions">
            <button type="button" className="refresh-btn" onClick={handlePreview} disabled={previewLoading}>
              {previewLoading ? '계산 중...' : '🔄 미리보기'}
            </button>
          </div>
          {previewError && <p className="status-card__error">⚠ {previewError}</p>}
          {preview && (
            <ul className="today-list">
              {preview.days.filter((d) => d.slots.length > 0).length === 0 && (
                <li>이번 주(오늘부터 7일) 예정된 발행이 없습니다.</li>
              )}
              {preview.days.filter((d) => d.slots.length > 0).map((d) => (
                <li key={d.date}>
                  <strong>{WEEKDAY_LABELS[d.weekday]} ({d.date})</strong>
                  <ul>
                    {d.slots.map((slot, i) => (
                      <li key={i}>
                        {slot.scheduled_at} (범위 {slot.start}~{slot.end})
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}
