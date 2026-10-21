import { useState } from "react";
import { api } from "../api/client.js";
import { Alert, Button, Field } from "../components/UI.jsx";

export default function LoginPage({ onLogin }) {
  const [username, setUsername] = useState("client1");
  const [password, setPassword] = useState("Client-one-demo-2026!");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await api.login(username, password);
      onLogin(await api.me());
    } catch (err) {
      setError(err.message);
    } finally { setBusy(false); }
  }

  return <main className="login-shell">
    <section className="login-story">
      <div className="brand brand--light"><b>А</b><span>Альфа Бизнес</span></div>
      <div className="login-story__copy">
        <span className="eyebrow">Умный кредитный кабинет</span>
        <h1>Финансирование<br />без банковского квеста</h1>
        <p>От потребности до понятного решения — в одном цифровом процессе.</p>
      </div>
      <div className="login-orbit" aria-hidden="true"><i /><i /><i /></div>
      <div className="login-story__footer"><span>01 — Подбор</span><span>02 — Заявка</span><span>03 — Решение</span></div>
    </section>
    <section className="login-panel">
      <form className="login-card" onSubmit={submit}>
        <span className="eyebrow eyebrow--red">Для действующих клиентов</span>
        <h2>Войти в кабинет</h2>
        <p className="muted">Используйте подготовленную демонстрационную учётную запись.</p>
        {error && <Alert type="error">{error}</Alert>}
        <Field label="Логин"><input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></Field>
        <Field label="Пароль"><input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
        <Button type="submit" busy={busy}>Продолжить</Button>
        <div className="demo-switch">
          <button type="button" onClick={() => { setUsername("client1"); setPassword("Client-one-demo-2026!"); }}>1-й клиент</button>
          <button type="button" onClick={() => { setUsername("client2"); setPassword("Client-two-demo-2026!"); }}>2-й клиент</button>
          <button type="button" onClick={() => { setUsername("employee"); setPassword("Employee-demo-2026!"); }}>Сотрудник</button>
        </div>
        <small>Только синтетические данные. Регистрация не требуется.</small>
      </form>
    </section>
  </main>;
}
