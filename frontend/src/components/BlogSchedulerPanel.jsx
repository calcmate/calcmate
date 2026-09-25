import { useCallback, useEffect, useState } from 'react'
import {
  getBlogSchedulerStatus,
  getBlogSchedulerConfig,
  getBlogSchedulerToday,
  getBlogSchedulerHistory,
  getBlogSchedulerOneoff,
  patchBlogSchedulerConfig,
  runBlogSchedulerOnce,
  runBlogSchedulerOnceOneoff,
  getPublishingPolicy,
  patchPublishingPolicy,
  getCurrentUser,
} from '../api/client.js'

const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
const WEEKDAY_LABELS = {
  mon: '월', tue: '화', wed: '수', thu: '목',
  fri: '금', sat: '토', sun: '일',
}

function emptyRange() {
  return { start: '09:00', end: '18:00' }
}

function emptyDayEntry() {
  return { count: 0, time_ranges: [] }
}

function emptySlot() {
  return { start: '06:00', end: '06:30' }
}

export default function BlogSchedulerPanel() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)

  const [status, setStatus] = useState(null)
  const [config, setConfig] = useState(null)
  const [today, setToday] = useState(null)
  const [history, setHistory] = useState(null)
  const [oneoff, setOneoff] = useState(null)
  const [oneoffError, setOneoffError] = useState(false)

  const [weekdays, setWeekdays] = useState({})
  const [recurringMode, setRecurringMode] = useState('draft')
  const [oneoffMode, setOneoffMode] = useState('draft')

  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState(null)
  const [saveError, setSaveError] = useState(null)

  const [running, setRunning] = useState(false)
  const [runMessage, setRunMessage] = useState(null)
  const [runError, setRunError] = useState(null)

const load = useCallback(() => {
    setLoading(true)
    setLoadError(false)
    setOneoffError(false)
    Promise.all([
      getBlogSchedulerStatus(),
      getBlogSchedulerConfig(),
      getBlogSchedulerToday(),
      getBlogSchedulerHistory(),
      getBlogSchedulerOneoff(),
      getPublishingPolicy(),
      getCurrentUser(),
    ]).then(([s, c, t, h, o, p, u]) => {
      setStatus(s)
      setConfig(c)
      setToday(t)
      setHistory(h)
      setOneoff(o)
      setIsAdmin(Boolean(u?.success && u.data?.role === 'admin'))

      if (c?.success && c.data) {
        setRecurringMode(c.data.mode || 'draft')
      }
      if (p?.success && p.data) {
        setWeekdays(p.data.weekdays || {})
      }
      setLoadError(!s?.success || !c?.success || !t?.success || !h?.success || !p?.success)
      setOneoffError(!o?.success)
      setLoading(false)
    })
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

  function getPublishSlotsFromPolicy() {
    const slots = []
    WEEKDAYS.forEach((day) => {
      const entry = weekdays[day] || emptyDayEntry()
      if (entry.count > 0 && entry.time_ranges.length > 0) {
        entry.time_ranges.forEach((range) => {
          slots.push({ start: range.start, end: range.end })
        })
      }
    })
    return slots.length > 0 ? slots : [emptySlot()]
  }

  async function handleSaveSchedule() {
    setSaving(true)
    setSaveMessage(null)
    setSaveError(null)

    const publishSlots = getPublishSlotsFromPolicy()
    const hasAnyCount = Object.values(weekdays).some((entry) => entry.count > 0)

    try {
      const [blogRes, policyRes] = await Promise.all([
        patchBlogSchedulerConfig({
          enabled: hasAnyCount,
          mode: recurringMode,
          publish_slots: publishSlots,
          weekday_only: false,
        }),
        patchPublishingPolicy({
          timezone: 'Asia/Seoul',
          weekdays,
          max_pending_reservations: 10,
        }),
      ])

      setSaving(false)
      if (blogRes.success && policyRes.success) {
        setSaveMessage('스케줄이 저장되었습니다.')
        load()
      } else {
        setSaveError((blogRes.error?.message || '') + (policyRes.error?.message || ''))
      }
    } catch (err) {
      setSaving(false)
      setSaveError(err.message || '저장 실패')
    }
  }

  async function handleRunOnce(mode) {
    setRunning(true)
    setRunMessage(null)
    setRunError(null)
    try {
      const res = await runBlogSchedulerOnceOneoff(mode)
      setRunning(false)
      if (res.success) {
        setRunMessage(`1회 생성 완료 (생성 ${res.data?.produced ?? 0}건)`)
        load()
      } else {
        setRunError(res.error?.message || '실행 실패')
      }
    } catch (err) {
      setRunning(false)
      setRunError(err.message || '실행 실패')
    }
  }

  async function handleRunRecurringOnce() {
    setRunning(true)
    setRunMessage(null)
    setRunError(null)
    try {
      const res = await runBlogSchedulerOnce()
      setRunning(false)
      if (res.success) {
        setRunMessage(`반복 실행 완료 (생성 ${res.data?.produced ?? 0}건)`)
        load()
      } else {
        setRunError(res.error?.message || '실행 실패')
      }
    } catch (err) {
      setRunning(false)
      setRunError(err.message || '실행 실패')
    }
  }

  const canRunRecurring = !running && config?.data?.enabled && !loading
  const canRunOneoff = !running && !loading

  const nextSchedule = today?.data?.schedule?.find?.(
    (entry) => entry.status === 'pending' || entry.status === 'retry'
  )

  const pendingCount = oneoff?.data?.reservations?.filter?.(
    (r) => r.status === 'pending'
  ).length ?? 0

  const runningCount = oneoff?.data?.reservations?.filter?.(
    (r) => r.status === 'running' || r.status === 'generating'
  ).length ?? 0

  const completedCount = oneoff?.data?.reservations?.filter?.(
    (r) => r.status === 'completed'
  ).length ?? 0

  const failedCount = oneoff?.data?.reservations?.filter?.(
    (r) => r.status === 'failed'
  ).length ?? 0

  return (
    <div className="status-card blog-panel">
      <h3 className="status-card__title">블로그 스케줄</h3>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {!loading && loadError && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !loadError && (
        <>
          {/* 반복 발행 섹션 */}
          <section className="schedule-section">
            <h4 className="section-title">반복 발행</h4>

            <div className="form-row form-row--toggle">
              <label className="form-check form-check--switch">
                <input
                  type="checkbox"
                  checked={config?.data?.enabled ?? false}
                  onChange={(e) => {
                    const newEnabled = e.target.checked
                    setConfig((c) => c?.success ? { ...c, data: { ...c.data, enabled: newEnabled } } : c)
                    setWeekdays((w) => {
                      const hasAny = Object.values(w).some((entry) => entry.count > 0)
                      if (!hasAny && newEnabled) {
                        const newW = { ...w }
                        WEEKDAYS.forEach((day, i) => {
                          if (i % 2 === 0) {
                            newW[day] = { count: 1, time_ranges: [emptyRange()] }
                          }
                        })
                        return newW
                      }
                      return w
                    })
                  }}
                />
                <span className="switch-label">
                  <span className={`switch-badge ${config?.data?.enabled ? 'on' : 'off'}`}>
                    {config?.data?.enabled ? 'ON' : 'OFF'}
                  </span>
                  스케줄
                </span>
              </label>
            </div>

            <div className="weekday-grid">
              <div className="weekday-header">
                {WEEKDAYS.map((day) => (
                  <div key={day} className="weekday-cell header">{WEEKDAY_LABELS[day]}</div>
                ))}
              </div>
              <div className="weekday-row count-row">
                {WEEKDAYS.map((day) => {
                  const entry = weekdays[day] || emptyDayEntry()
                  return (
                    <div key={day} className="weekday-cell">
                      <input
                        type="number"
                        className="form-number"
                        min={0}
                        max={10}
                        value={entry.count}
                        onChange={(e) => updateCount(day, e.target.value)}
                        aria-label={`${WEEKDAY_LABELS[day]} 개수`}
                      />
                    </div>
                  )
                })}
              </div>
              <div className="weekday-row time-row">
                {WEEKDAYS.map((day) => {
                  const entry = weekdays[day] || emptyDayEntry()
                  if (entry.count === 0 || entry.time_ranges.length === 0) {
                    return <div key={day} className="weekday-cell empty">-</div>
                  }
                  return (
                    <div key={day} className="weekday-cell">
                      {entry.time_ranges.map((range, i) => (
                        <div key={i} className="time-range">
                          <input
                            type="time"
                            className="form-time"
                            value={range.start}
                            onChange={(e) => updateRange(day, i, 'start', e.target.value)}
                            aria-label={`${WEEKDAY_LABELS[day]} 시작`}
                          />
                          <span aria-hidden="true">~</span>
                          <input
                            type="time"
                            className="form-time"
                            value={range.end}
                            onChange={(e) => updateRange(day, i, 'end', e.target.value)}
                            aria-label={`${WEEKDAY_LABELS[day]} 종료`}
                          />
                        </div>
                      ))}
                    </div>
                  )
                })}
              </div>
            </div>

            <div className="form-row form-row--mode">
              <label className="form-label">실행 방식</label>
              <div className="mode-options">
                <label className="mode-option">
                  <input
                    type="radio"
                    name="recurring-mode"
                    value="draft"
                    checked={recurringMode === 'draft'}
                    onChange={(e) => setRecurringMode(e.target.value)}
                  />
                  <span>Draft</span>
                </label>
                <label className="mode-option">
                  <input
                    type="radio"
                    name="recurring-mode"
                    value="publish"
                    checked={recurringMode === 'publish'}
                    onChange={(e) => setRecurringMode(e.target.value)}
                  />
                  <span>배포</span>
                </label>
              </div>
            </div>

            <div className="form-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleSaveSchedule}
                disabled={saving}
              >
                {saving ? '저장 중...' : '스케줄 저장'}
              </button>
            </div>
            {saveMessage && <p className="status-card__success">{saveMessage}</p>}
            {saveError && <p className="status-card__error">⚠ {saveError}</p>}
            {!isAdmin && <p className="status-card__hint">저장에는 관리자 권한이 필요합니다.</p>}
          </section>

          <hr className="panel-divider" />

          {/* 1회 생성 섹션 */}
          <section className="schedule-section">
            <h4 className="section-title">1회 생성</h4>
            <p className="section-hint">스케줄과 관계없이 글 1개를 생성합니다.</p>

            <div className="form-row form-row--mode">
              <label className="form-label">실행 방식</label>
              <div className="mode-options">
                <label className="mode-option">
                  <input
                    type="radio"
                    name="oneoff-mode"
                    value="draft"
                    checked={oneoffMode === 'draft'}
                    onChange={(e) => setOneoffMode(e.target.value)}
                  />
                  <span>Draft</span>
                </label>
                <label className="mode-option">
                  <input
                    type="radio"
                    name="oneoff-mode"
                    value="publish"
                    checked={oneoffMode === 'publish'}
                    onChange={(e) => setOneoffMode(e.target.value)}
                  />
                  <span>배포</span>
                </label>
              </div>
            </div>

            <div className="form-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => handleRunOnce(oneoffMode)}
                disabled={!canRunOneoff}
              >
                {running ? '실행 중...' : '1회 생성'}
              </button>
            </div>
            {runMessage && <p className="status-card__success">{runMessage}</p>}
            {runError && <p className="status-card__error">⚠ {runError}</p>}
          </section>

          <hr className="panel-divider" />

          {/* 진행 상황 섹션 */}
          <section className="schedule-section">
            <h4 className="section-title">진행 상황</h4>

            <div className="progress-grid">
              <div className="progress-card">
                <div className="progress-label">다음 예약</div>
                <div className="progress-value">
                  {nextSchedule
                    ? `${nextSchedule.scheduled_time} (글 ${nextSchedule.post_no})`
                    : '예약 없음'}
                </div>
              </div>
              <div className="progress-card">
                <div className="progress-label">예약된 글</div>
                <div className="progress-value">{pendingCount}</div>
              </div>
              <div className="progress-card">
                <div className="progress-label">생성 중</div>
                <div className="progress-value">{runningCount}</div>
              </div>
              <div className="progress-card">
                <div className="progress-label">완료</div>
                <div className="progress-value">{completedCount}</div>
              </div>
              <div className="progress-card">
                <div className="progress-label">실패</div>
                <div className="progress-value">{failedCount}</div>
              </div>
            </div>

            <div className="progress-details">
              <h5>최근 실행 이력</h5>
              {Array.isArray(history?.data?.records) && history.data.records.length > 0 ? (
                <ul className="history-list">
                  {history.data.records.slice().reverse().slice(0, 10).map((rec, i) => (
                    <li key={i}>
                      {rec.date} {rec.actual_time || rec.scheduled_time} · {rec.status} · {rec.result}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="status-card__hint">최근 실행 이력이 없습니다.</p>
              )}

              <h5>1회 예약 목록</h5>
              {oneoffError ? (
                <p className="status-card__error">⚠ 예약 정보를 불러오지 못했습니다.</p>
              ) : (
                Array.isArray(oneoff?.data?.reservations) && oneoff.data.reservations.length > 0 ? (
                  <ul className="history-list">
                    {oneoff.data.reservations.slice(0, 10).map((res) => (
                      <li key={res.id}>
                        {res.id} · {res.scheduled_at} · {res.mode} · {res.status}
                        {res.result?.wp_post_id && ` · wp_post_id=${res.result.wp_post_id}`}
                        {res.duplicate && ' · 중복'}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="status-card__hint">현재 예약된 1회 실행이 없습니다.</p>
                )
              )}
            </div>
          </section>
        </>
      )}
    </div>
  )
}