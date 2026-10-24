import { useCallback, useEffect, useRef, useState } from "react";
import { STATUS_LABELS } from "../domain/application.js";
import { Button as CoreButton } from "@alfalab/core-components-button";
import { Toast as CoreToast } from "@alfalab/core-components-toast";

export function Button({ children, variant = "primary", busy, disabled, className = "", ...props }) {
  const views = { primary: "accent", secondary: "secondary", ghost: "text" };
  return <CoreButton
    className={`app-button app-button--${variant} ${className}`.trim()}
    view={views[variant] || "accent"}
    shape="rounded"
    size={48}
    loading={busy}
    disabled={busy || disabled}
    {...props}
  >{children}</CoreButton>;
}

export function Alert({ type = "info", children, title }) {
  return <div className={`alert alert--${type}`} role={type === "error" ? "alert" : "status"}>
    {title ? <strong>{title}</strong> : null}<span>{children}</span>
  </div>;
}

export function Toast({ message, onClose, type = "success", position = "right" }) {
  const [open, setOpen] = useState(Boolean(message));
  const closing = useRef(false);
  const exitTimer = useRef(null);
  const close = useCallback(() => {
    if (closing.current) return;
    closing.current = true;
    setOpen(false);
    exitTimer.current = window.setTimeout(onClose, 180);
  }, [onClose]);

  useEffect(() => {
    if (!message) return undefined;
    closing.current = false;
    setOpen(true);
    const timer = window.setTimeout(close, 5000);
    return () => {
      window.clearTimeout(timer);
      window.clearTimeout(exitTimer.current);
    };
  }, [message, close]);

  if (!message) return null;
  const badgeByType = {
    success: "positive-checkmark",
    error: "negative-alert",
    info: "neutral-information",
  };
  return <CoreToast
    className={`app-toast ${position === "center" ? "app-toast--center" : ""}`.trim()}
    open={open}
    title={message}
    badge={badgeByType[type] || badgeByType.info}
    autoCloseDelay={5000}
    bottomOffset={24}
    closeWithClickOutside={false}
    closerProps={{ hasCloser: true }}
    style={position === "center"
      ? { left: "50%", right: "auto", width: "min(420px, calc(100vw - 32px))" }
      : { right: 24, width: "min(420px, calc(100vw - 32px))" }}
    onClose={close}
  />;
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
