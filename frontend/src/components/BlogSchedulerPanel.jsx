import { useCallback, useEffect, useState } from 'react'
import {
  getBlogSchedulerStatus,
  getBlogSchedulerConfig,
  getBlogSchedulerToday,
  getBlogSchedulerHistory,
  getBlogSchedulerOneoff,
  patchBlogSchedulerConfig,
  runBlogSchedulerOnce,
} from '../api/client.js'

function emptySlot() {
  return { start: '06:00', end: '06:30' }
}

// 📝 Blog Schedule 기능 이식 (STEP 18-E). 조회 + 설정 저장 + 수동 1회 실행만 제공한다.
export default function BlogSchedulerPanel() {
  const [status, setStatus] = useState(null)
  const [config, setConfig] = useState(null)
  const [today, setToday] = useState(null)
  const [history, setHistory] = useState(null)
  // CALCMATE-DASHBOARD-ONEOFF-SCHEDULER-VIEW-IMPLEMENT-01: One-off 예약 목록.
  // 이 영역의 조회 실패는 별도 state(oneoffError)로만 표시하고, loadError(기존
  // Golden10 4개 API 기준)에는 포함하지 않는다 — One-off API 오류가 기존
  // Dashboard 전체를 빈 화면으로 만들지 않기 위함.
  const [oneoff, setOneoff] = useState(null)
  const [oneoffError, setOneoffError] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)

  const [form, setForm] = useState({
    enabled: false,
    mode: 'draft',
    slots: [emptySlot()],
    weekdayOnly: false,
  })

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
    ]).then(([s, c, t, h, o]) => {
      setStatus(s)
      setConfig(c)
      setToday(t)
      setHistory(h)
      setOneoff(o)
      if (c?.success && c.data) {
        setForm({
          enabled: Boolean(c.data.enabled),
          mode: c.data.mode || 'draft',
          slots: Array.isArray(c.data.publish_slots) && c.data.publish_slots.length > 0
            ? c.data.publish_slots.map((s2) => ({ start: s2.start, end: s2.end }))
            : [emptySlot()],
          weekdayOnly: Boolean(c.data.weekday_only),
        })
      }
      // One-off 조회 실패는 별도 상태로만 표시하고 기존 loadError에는 포함하지
      // 않는다(위 state 선언부 주석 참고).
      setLoadError(!s?.success || !c?.success || !t?.success || !h?.success)
      setOneoffError(!o?.success)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  function updateSlotCount(nextCount) {
    setForm((f) => {
      const slots = [...f.slots]
      while (slots.length < nextCount) slots.push(emptySlot())
      while (slots.length > nextCount) slots.pop()
      return { ...f, slots }
    })
  }

  function updateSlot(index, field, value) {
    setForm((f) => {
      const slots = f.slots.map((s, i) => (i === index ? { ...s, [field]: value } : s))
      return { ...f, slots }
    })
  }

  async function handleSave() {
    setSaving(true)
    setSaveMessage(null)
    setSaveError(null)
    const res = await patchBlogSchedulerConfig({
      enabled: form.enabled,
      mode: form.mode,
      publish_slots: form.slots,
      weekday_only: form.weekdayOnly,
    })
    setSaving(false)
    if (res.success) {
      setSaveMessage('저장되었습니다.')
      load()
    } else {
      setSaveError(res.error?.message || '저장 실패')
    }
  }

  async function handleRunOnce() {
    setRunning(true)
    setRunMessage(null)
    setRunError(null)
    const res = await runBlogSchedulerOnce()
    setRunning(false)
    if (res.success) {
      setRunMessage(`실행 완료 (생성 ${res.data?.produced ?? 0}건)`)
      load()
    } else {
      setRunError(res.error?.message || '실행 실패')
    }
  }

  const canRunOnce = !running && form.enabled && !loading

  return (
    <div className="status-card blog-panel">
      <h3 className="status-card__title">Blog Scheduler</h3>

      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {!loading && loadError && <p className="status-card__error">⚠ API 연결 실패</p>}

      {!loading && !loadError && (
        <>
          <div className="form-row">
            <label className="form-check">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
              />
              Enabled
            </label>
          </div>

          <div className="form-row">
            <label className="form-label" htmlFor="blog-mode">Mode</label>
            <select
              id="blog-mode"
              className="form-select"
              value={form.mode}
              onChange={(e) => setForm((f) => ({ ...f, mode: e.target.value }))}
            >
              <option value="draft">draft</option>
              <option value="publish">publish</option>
            </select>
          </div>

          <div className="form-row">
            <label className="form-label" htmlFor="blog-count">Daily Count</label>
            <input
              id="blog-count"
              className="form-number"
              type="number"
              min={1}
              max={10}
              value={form.slots.length}
              onChange={(e) => updateSlotCount(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
            />
          </div>

          {form.slots.map((slot, i) => (
            <div className="form-row form-row--slot" key={i}>
              <span className="form-label">Slot {i + 1}</span>
              <div className="slot-inputs">
                <input
                  type="time"
                  aria-label={`slot-${i}-start`}
                  className="form-time"
                  value={slot.start}
                  onChange={(e) => updateSlot(i, 'start', e.target.value)}
                />
                <span aria-hidden="true">—</span>
                <input
                  type="time"
                  aria-label={`slot-${i}-end`}
                  className="form-time"
                  value={slot.end}
                  onChange={(e) => updateSlot(i, 'end', e.target.value)}
                />
              </div>
            </div>
          ))}

          <div className="form-row">
            <label className="form-check">
              <input
                type="checkbox"
                checked={form.weekdayOnly}
                onChange={(e) => setForm((f) => ({ ...f, weekdayOnly: e.target.checked }))}
              />
              평일만(weekday_only)
            </label>
          </div>

          <div className="form-actions">
            <button type="button" className="refresh-btn" onClick={handleSave} disabled={saving}>
              {saving ? '저장 중...' : 'Save'}
            </button>
          </div>
          {saveMessage && <p className="status-card__success">{saveMessage}</p>}
          {saveError && <p className="status-card__error">⚠ {saveError}</p>}

          <hr className="panel-divider" />

          {/* STEP 18-I-A: 위 Configuration의 Enabled(설정값)와 실제 워커 실행 여부는
              서로 다른 의미다 — 설정이 켜져 있어도 이 화면(FastAPI 프로세스)에서 실제
              워커 스레드가 기동되어 있지 않으면 Worker는 Stopped로 표시되며, 이는
              오류가 아니다. running/thread_alive는 동일한 실측 신호(§9)라 하나로 합친다. */}
          <p className="panel-section-title">Worker Status</p>
          <dl className="kv-list">
            <div className="kv-list__row">
              <dt>Worker</dt>
              <dd>
                <span className={`badge ${status?.data?.running ? 'badge--on' : 'badge--off'}`}>
                  {status?.data?.running ? 'Running' : 'Stopped'}
                </span>
              </dd>
            </div>
          </dl>

          <hr className="panel-divider" />

          <p className="panel-section-title">Today's Schedule</p>
          {Array.isArray(today?.data?.schedule) && today.data.schedule.length > 0 ? (
            <ul className="today-list">
              {today.data.schedule.map((entry, i) => (
                <li key={i}>
                  {entry.scheduled_time} · {entry.status}
                </li>
              ))}
            </ul>
          ) : (
            <p className="status-card__hint">오늘 예정된 일정이 없습니다.</p>
          )}

          <hr className="panel-divider" />

          <div className="form-actions">
            <button type="button" className="refresh-btn" onClick={handleRunOnce} disabled={!canRunOnce}>
              {running ? '실행 중...' : '▶ Blog 1회 실행'}
            </button>
          </div>
          {!form.enabled && (
            <p className="status-card__hint">Enabled가 꺼져 있어 실행할 수 없습니다.</p>
          )}
          {runMessage && <p className="status-card__success">{runMessage}</p>}
          {runError && <p className="status-card__error">⚠ {runError}</p>}

          <hr className="panel-divider" />

          <p className="panel-section-title">Recent History</p>
          {Array.isArray(history?.data?.records) && history.data.records.length > 0 ? (
            <ul className="history-list">
              {history.data.records.slice().reverse().map((rec, i) => (
                <li key={i}>
                  {rec.date} {rec.actual_time || rec.scheduled_time} · {rec.status} · {rec.result}
                </li>
              ))}
            </ul>
          ) : (
            <p className="status-card__hint">최근 실행 이력이 없습니다.</p>
          )}

          <hr className="panel-divider" />

          {/* CALCMATE-DASHBOARD-ONEOFF-SCHEDULER-VIEW-IMPLEMENT-01: 위 Golden10
              recurring 영역과 시각적으로 구분되는 별도 섹션. 실행 프로세스
              상태(RUNNING/STOPPED)는 표시하지 않는다 — One-off Scheduler는
              Windows Task Scheduler → 별도 BAT → 별도 Python 프로세스로
              실행되며, 이 FastAPI 프로세스 내부의 WorkerManager(threading.
              enumerate() 기반)로는 그 실제 상태를 알 수 없다(추정 금지).
              여기서는 오직 oneoff_schedule.json에 기록된 예약 자체의 상태
              (pending/completed/failed)만 있는 그대로 표시한다. */}
          <p className="panel-section-title">1회 예약 스케줄</p>
          {oneoffError ? (
            <>
              <p className="status-card__error">⚠ 예약 정보를 불러오지 못했습니다.</p>
              <div className="form-actions">
                <button type="button" className="refresh-btn" onClick={load}>다시 시도</button>
              </div>
            </>
          ) : (
            (() => {
              const reservations = Array.isArray(oneoff?.data?.reservations)
                ? oneoff.data.reservations
                : []
              if (reservations.length === 0) {
                return <p className="status-card__hint">현재 예약된 1회 실행이 없습니다.</p>
              }
              return (
                <ul className="today-list">
                  {reservations.map((res) => {
                    const target = res.topic_id ? `Topic Pool(${res.topic_id})` : 'Golden10'
                    const wpPostId = res.result?.wp_post_id
                      ?? res.result?.results?.[0]?.wp_post_id
                      ?? null
                    return (
                      <li key={res.id}>
                        {res.id} · {res.scheduled_at} · {target} · {res.mode} · {res.status}
                        {wpPostId != null && <> · wp_post_id={wpPostId}</>}
                        {res.duplicate && <> · 중복</>}
                      </li>
                    )
                  })}
                </ul>
              )
            })()
          )}
        </>
      )}
    </div>
  )
}
