import { useCallback, useEffect, useState } from 'react'
import SchedulerCard from '../components/SchedulerCard.jsx'
import { getCalculatorSchedulerStatus } from '../api/client.js'

// /calculator-scheduler — STEP V1-OPS-04: 계산기 Scheduler를 Blog Scheduler와
// 분리된 하위탭으로 노출한다. 기존 Scheduler.jsx(/scheduler)가 쓰던
// SchedulerCard·getCalculatorSchedulerStatus()를 그대로 재사용한다(조회
// 전용 — 이번 STEP에서 새 기능/버튼을 추가하지 않는다).
export default function CalculatorScheduler() {
  const [calc, setCalc] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    getCalculatorSchedulerStatus().then((c) => {
      setCalc(c)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="page">
      <div className="page__header">
        <h1>🧮 계산기 Scheduler</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>
      <div className="card-grid">
        <SchedulerCard
          title="Calculator Scheduler"
          data={calc?.data}
          loading={loading}
          failed={!loading && !calc?.success}
        />
      </div>
    </div>
  )
}
