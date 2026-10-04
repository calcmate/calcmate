function Badge({ value }) {
  return (
    <span className={`badge ${value ? 'badge--on' : 'badge--off'}`}>
      {value ? 'ON' : 'OFF'}
    </span>
  )
}

// 이번 STEP은 조회 전용이다 — ON/OFF·실행 버튼은 만들지 않는다.
// STEP 18-I-A: Enabled(설정값)와 Worker(실제 스레드 실행 여부)는 서로 다른 의미이므로
// 별도 표시한다. running과 thread_alive는 동일한 실측 신호(§9)이므로 하나로 합쳐 보여준다.
export default function SchedulerCard({ title, data, loading, failed }) {
  return (
    <div className="status-card">
      <h3 className="status-card__title">{title}</h3>
      {loading && <p className="status-card__hint">불러오는 중...</p>}
      {!loading && failed && <p className="status-card__error">⚠ API 연결 실패</p>}
      {!loading && !failed && data && (
        <dl className="kv-list">
          <div className="kv-list__row">
            <dt>Enabled</dt>
            <dd><Badge value={data.enabled} /></dd>
          </div>
          <div className="kv-list__row">
            <dt>Worker</dt>
            <dd>
              <span className={`badge ${data.running ? 'badge--on' : 'badge--off'}`}>
                {data.running ? 'Running' : 'Stopped'}
              </span>
            </dd>
          </div>
        </dl>
      )}
    </div>
  )
}
