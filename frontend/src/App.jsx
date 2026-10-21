import { useEffect, useState } from "react";
import { api, clearToken, getToken } from "./api/client.js";
import AppShell from "./components/AppShell.jsx";
import { Skeleton } from "./components/UI.jsx";
import ClientWorkspace from "./pages/ClientWorkspace.jsx";
import EmployeeWorkspace from "./pages/EmployeeWorkspace.jsx";
import LoginPage from "./pages/LoginPage.jsx";

export default function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(Boolean(getToken()));

  useEffect(() => {
    if (!getToken()) return;
    api.me().then(setUser).catch(clearToken).finally(() => setChecking(false));
  }, []);

  useEffect(() => {
    const expire = () => setUser(null);
    window.addEventListener("auth-expired", expire);
    return () => window.removeEventListener("auth-expired", expire);
  }, []);

  function logout() { clearToken(); setUser(null); }
  if (checking) return <div className="boot"><Skeleton rows={3} /></div>;
  if (!user) return <LoginPage onLogin={setUser} />;
  return <AppShell user={user} onLogout={logout} area={user.role === "CLIENT" ? "Кредитный кабинет" : "Рассмотрение заявок"}>
    {user.role === "CLIENT" ? <ClientWorkspace /> : <EmployeeWorkspace />}
  </AppShell>;
}
