import { useCallback, useEffect, useState } from 'react'
import SchedulerCard from '../components/SchedulerCard.jsx'
import BlogSchedulerPanel from '../components/BlogSchedulerPanel.jsx'
import PendingSync from '../components/PendingSync.jsx'
import { getCalculatorSchedulerStatus, getContentSyncStatus } from '../api/client.js'

// Scheduler(/scheduler) — Calculator/Content Sync는 조회 전용(STEP 18-D 그대로).
// Blog Scheduler만 STEP 18-E에서 관리 기능(조회+저장+수동 실행)으로 확장됐다.
// 🔁 동기화 복구(STEP 65): Pending/Processing/Failed 큐 조회 + Retry/Resume.
export default function Scheduler() {
  const [activeTab, setActiveTab] = useState('blog')
  const [calc, setCalc] = useState(null)
  const [sync, setSync] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([getCalculatorSchedulerStatus(), getContentSyncStatus()]).then(([c, s]) => {
      setCalc(c)
      setSync(s)
      setLoading(false)
    })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const tabs = [
    { key: 'blog', label: '📝 Blog Scheduler' },
    { key: 'calc', label: '🧮 Calculator Scheduler' },
    { key: 'sync', label: '🔄 Content Sync' },
    { key: 'pending', label: '🔁 동기화 복구' },
  ]

  const renderContent = () => {
    if (activeTab === 'blog') return <BlogSchedulerPanel />
    if (activeTab === 'calc') {
      return (
        <SchedulerCard
          title="Calculator Scheduler"
          data={calc?.data}
          loading={loading}
          failed={!loading && !calc?.success}
        />
      )
    }
    if (activeTab === 'sync') {
      return (
        <SchedulerCard
          title="Content Sync"
          data={sync?.data}
          loading={loading}
          failed={!loading && !sync?.success}
        />
      )
    }
    if (activeTab === 'pending') return <PendingSync />
    return null
  }

  return (
    <div className="page">
      <div className="page__header">
        <h1>Scheduler</h1>
        <button type="button" className="refresh-btn" onClick={load}>
          새로고침
        </button>
      </div>

      <div className="sync-tabs" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            role="tab"
            aria-selected={activeTab === tab.key}
            className={`sync-tab ${activeTab === tab.key ? 'sync-tab--active' : ''}`}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="card-grid">
        {renderContent()}
      </div>
    </div>
  )
}
