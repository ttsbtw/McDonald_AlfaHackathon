import { STATUS_LABELS } from "../domain/application.js";

export function Button({ children, variant = "primary", busy, ...props }) {
  return <button className={`button button--${variant}`} disabled={busy || props.disabled} {...props}>
    {busy ? <span className="button__loader" aria-hidden="true" /> : null}
    {busy ? "Подождите…" : children}
  </button>;
}

export function Alert({ type = "info", children, title }) {
  return <div className={`alert alert--${type}`} role={type === "error" ? "alert" : "status"}>
    {title ? <strong>{title}</strong> : null}<span>{children}</span>
  </div>;
}

export function StatusBadge({ status }) {
  return <span className={`status status--${String(status).toLowerCase()}`}>
    <i aria-hidden="true" />{STATUS_LABELS[status] || status}
  </span>;
}

export function Field({ label, hint, error, children }) {
  return <label className={`field ${error ? "field--error" : ""}`}>
    <span className="field__label">{label}</span>
    {children}
    {error ? <span className="field__error">{error}</span> : hint ? <span className="field__hint">{hint}</span> : null}
  </label>;
}

export function EmptyState({ icon = "○", title, children, action }) {
  return <div className="empty-state">
    <span className="empty-state__icon" aria-hidden="true">{icon}</span>
    <h3>{title}</h3><p>{children}</p>{action}
  </div>;
}

export function Skeleton({ rows = 3 }) {
  return <div className="skeleton" aria-label="Загрузка">{Array.from({ length: rows }, (_, i) => <i key={i} />)}</div>;
}
