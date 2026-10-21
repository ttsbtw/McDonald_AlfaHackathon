export default function AppShell({ user, onLogout, children, area, onBack }) {
  return <div className="app-shell">
    <header className="topbar">
      <div className="topbar__left">{onBack && <button className="topbar__back" onClick={onBack}>← Назад</button>}<div className="brand"><b>А</b><span>Альфа Бизнес</span></div></div>
      <div className="topbar__area">{area}</div>
      <div className="user-menu"><div><strong>{user.full_name}</strong><span>{user.role === "CLIENT" ? "Клиент" : "Сотрудник банка"}</span></div><button onClick={onLogout} aria-label="Выйти">↗</button></div>
    </header>
    {children}
  </div>;
}
