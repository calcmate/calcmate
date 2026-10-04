import { useCallback, useEffect, useState } from 'react'
import {
  getPendingSync,
  getProcessingSync,
  getFailedSync,
  postRetrySync,
  postResumeSync,
} from '../api/client.js'

const STATUS_TABS = [
  { key: 'pending', label: '🟢 Pending', color: 'green' },
  { key: 'processing', label: '🟡 Processing', color: 'orange' },
  { key: 'failed', label: '🔴 Failed', color: 'red' },
]

function formatDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return iso
  }
}

function SyncRow({
  item,
  status,
  onRetry,
  onResume,
  retryLoading,
  resumeLoading,
  retryError,
  resumeError,
}) {
  const isPending = status === 'pending'
  const isProcessing = status === 'processing'
  const isFailed = status === 'failed'

  const showRetry = isPending || isFailed
  const showResume = isFailed

  const buildRetryMessage = (item) => {
    return (
      '이 동기화 항목을 다시 시도하시겠습니까?\n\n' +
      '• qid: ' + item.id + '\n' +
      '• 작업: ' + item.op + '\n' +
      '• 테이블: ' + item.table + '\n' +
      '• Row ID: ' + item.row_id + '\n' +
      '• 현재 재시도 횟수: ' + item.retry_count + '\n' +
      '• 현재 에러: ' + (item.error || '—')
    )
  }

  const buildResumeMessage = (item) => {
    return (
      '영구 실패 항목을 다시 대기 상태로 복구하시겠습니까?\n\n' +
      '• qid: ' + item.id + '\n' +
      '• 작업: ' + item.op + '\n' +
      '• 테이블: ' + item.table + '\n' +
      '• Row ID: ' + item.row_id + '\n' +
      '• 재시도 횟수: ' + item.retry_count + '\n' +
      '• 에러: ' + (item.error || '—')
    )
  }

  const handleRetryClick = (onRetry) => {
    if (!window.confirm(buildRetryMessage(item))) return
    onRetry(item.id)
  }

  const handleResumeClick = (onResume) => {
    if (!window.confirm(buildResumeMessage(item))) return
    onResume(item.id)
  }

  return (
    <tr className="sync-table__row">
      <td className="sync-table__cell sync-table__cell--id">{item.id}</td>
      <td className="sync-table__cell">{item.op}</td>
      <td className="sync-table__cell">{item.table}</td>
      <td className="sync-table__cell sync-table__cell--rowid">{item.row_id}</td>
      <td className="sync-table__cell">{item.direction || '—'}</td>
      <td className="sync-table__cell">{item.source_adapter || '—'}</td>
      <td className="sync-table__cell sync-table__cell--retry">{item.retry_count}</td>
      <td className="sync-table__cell">
        <span className={`badge badge--${item.status === 'pending' ? 'on' : item.status === 'processing' ? 'off' : 'failed'}`}>
          {item.status === 'pending' ? 'Pending' : item.status === 'processing' ? 'Processing' : 'Failed'}
        </span>
      </td>
      <td className="sync-table__cell sync-table__cell--error" title={item.error}>
        {item.error ? item.error.slice(0, 50) + (item.error.length > 50 ? '…' : '') : '—'}
      </td>
      <td className="sync-table__cell">{formatDate(item.created_at)}</td>
      <td className="sync-table__cell">{formatDate(item.last_attempt_at)}</td>
      <td className="sync-table__cell sync-table__cell--actions">
        {showRetry && (
          <button
            type="button"
            className="refresh-btn sync-table__btn"
            onClick={() => handleRetryClick(onRetry)}
            disabled={retryLoading === item.id}
            title="재시도"
          >
            {retryLoading === item.id ? '⏳' : '🔁'}
          </button>
        )}
        {showResume && (
          <button
            type="button"
            className="refresh-btn sync-table__btn"
            onClick={() => handleResumeClick(onResume)}
            disabled={resumeLoading === item.id}
            title="재개 (pending으로 복구)"
          >
            {resumeLoading === item.id ? '⏳' : '↩️'}
          </button>
        )}
{retryError && retryError.message && (
            <span className="sync-table__action-error">⚠ {retryError.message}</span>
          )}
          {resumeError && resumeError.message && (
            <span className="sync-table__action-error">⚠ {resumeError.message}</span>
          )}
      </td>
    </tr>
  )
}

function SyncTable({ status, items, loading, error, onRetry, onResume, retryLoading, resumeLoading, retryErrors, resumeErrors, emptyMessage }) {
  if (loading) {
    return <p className="status-card__hint">불러오는 중...</p>
  }

  if (error) {
    return <p className="status-card__error">⚠ 목록 조회 실패: {error}</p>
  }

  if (!items || items.length === 0) {
    return <p className="status-card__hint">{emptyMessage}</p>
  }

  return (
    <div className="sync-table__wrap">
      <table className="sync-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>작업</th>
            <th>테이블</th>
            <th>Row ID</th>
            <th>방향</th>
            <th>어댑터</th>
            <th>재시도</th>
            <th>상태</th>
            <th>에러</th>
            <th>생성시각</th>
            <th>최종시도</th>
            <th>액션</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <SyncRow
              key={item.id}
              item={item}
              status={status}
              onRetry={onRetry}
              onResume={onResume}
              retryLoading={retryLoading}
              resumeLoading={resumeLoading}
              retryError={retryErrors[item.id]}
              resumeError={resumeErrors[item.id]}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function PendingSync() {
  const [activeTab, setActiveTab] = useState('pending')
  const [loading, setLoading] = useState({ pending: true, processing: true, failed: true })
  const [error, setError] = useState({ pending: null, processing: null, failed: null })
  const [items, setItems] = useState({ pending: [], processing: [], failed: [] })
  const [retryLoading, setRetryLoading] = useState(null)
  const [resumeLoading, setResumeLoading] = useState(null)
  const [retryErrors, setRetryErrors] = useState({})
  const [resumeErrors, setResumeErrors] = useState({})

  const loadTab = useCallback(async (tab) => {
    setLoading((l) => ({ ...l, [tab]: true }))
    setError((e) => ({ ...e, [tab]: null }))

    try {
      let res
      if (tab === 'pending') res = await getPendingSync()
      else if (tab === 'processing') res = await getProcessingSync()
      else res = await getFailedSync()

      if (res?.success) {
        setItems((i) => ({ ...i, [tab]: res.data || [] }))
      } else {
        setError((e) => ({ ...e, [tab]: res?.error?.message || '조회 실패' }))
        setItems((i) => ({ ...i, [tab]: [] }))
      }
    } catch (e) {
      setError((e) => ({ ...e, [tab]: e.message || '네트워크 오류' }))
      setItems((i) => ({ ...i, [tab]: [] }))
    } finally {
      setLoading((l) => ({ ...l, [tab]: false }))
    }
  }, [])

  useEffect(() => {
    loadTab(activeTab)
  }, [activeTab, loadTab])

  const handleRetry = useCallback(async (qid) => {
    setRetryLoading(qid)
    setRetryErrors((e) => ({ ...e, [qid]: null }))

    try {
      const res = await postRetrySync(qid)
      if (res?.success) {
        // 성공 시 현재 탭만 재조회
        loadTab(activeTab)
      } else {
        setRetryErrors((e) => ({ ...e, [qid]: { message: res?.error?.message || '재시도 실패' } }))
      }
    } catch (e) {
      setRetryErrors((e) => ({ ...e, [qid]: { message: e.message } }))
    } finally {
      setRetryLoading(null)
    }
  }, [activeTab, loadTab])

  const handleResume = useCallback(async (qid) => {
    setResumeLoading(qid)
    setResumeErrors((e) => ({ ...e, [qid]: null }))

    try {
      const res = await postResumeSync(qid)
      if (res?.success) {
        loadTab(activeTab)
      } else {
        setResumeErrors((e) => ({ ...e, [qid]: { message: res?.error?.message || '복구 실패' } }))
      }
    } catch (e) {
      setResumeErrors((e) => ({ ...e, [qid]: { message: e.message } }))
    } finally {
      setResumeLoading(null)
    }
  }, [activeTab, loadTab])

  const activeItems = items[activeTab]
  const activeLoading = loading[activeTab]
  const activeError = error[activeTab]

  const emptyMessages = {
    pending: '현재 대기 중인 동기화 항목이 없습니다.',
    processing: '현재 처리 중인 동기화 항목이 없습니다.',
    failed: '실패 확정된 항목이 없습니다.',
  }

  return (
    <div className="page pending-sync-page">
      <div className="page__header">
        <h1>🔁 동기화 복구</h1>
        <p className="page__hint">DualAdapter/SQLiteFirstAdapter가 편측 실패 시 적재한 재시도 큐입니다. Retry는 항목당 1회 호출 = 1회 재시도이며, 자동 반복/스케줄러는 없습니다.</p>
      </div>

      <div className="sync-tabs" role="tablist">
        {STATUS_TABS.map((tab) => (
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

      <div className="status-card">
        <SyncTable
          status={activeTab}
          items={items[activeTab]}
          loading={activeLoading}
          error={activeError}
          onRetry={handleRetry}
          onResume={handleResume}
          retryLoading={retryLoading}
          resumeLoading={resumeLoading}
          retryErrors={retryErrors}
          resumeErrors={resumeErrors}
          emptyMessage={emptyMessages[activeTab]}
        />
      </div>

      <div className="page__actions">
        <button type="button" className="refresh-btn" onClick={() => loadTab(activeTab)}>
          새로고침
        </button>
      </div>
    </div>
  )
}