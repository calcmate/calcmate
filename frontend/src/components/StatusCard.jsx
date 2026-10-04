export default function StatusCard({ title, children }) {
  return (
    <div className="status-card">
      <h3 className="status-card__title">{title}</h3>
      <div className="status-card__body">{children}</div>
    </div>
  )
}
