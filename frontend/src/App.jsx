import { useEffect, useState } from "react";
import { api, clearToken, getToken } from "./api/client.js";
import AppShell from "./components/AppShell.jsx";
import { Skeleton } from "./components/UI.jsx";
import ClientWorkspace from "./pages/ClientWorkspace.jsx";
import EmployeeWorkspace from "./pages/EmployeeWorkspace.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import { useBrowserNavigation } from "./navigation.js";

export default function App() {
  const { pathname, navigate } = useBrowserNavigation();
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

  useEffect(() => {
    if (!user) return;
    const isClient = user.role === "CLIENT";
    const validPath = isClient
      ? pathname === "/client" || pathname === "/client/new" || pathname === "/client/new/application" || /^\/client\/applications\/[^/]+$/.test(pathname)
      : pathname === "/employee/queue" || /^\/employee\/applications\/[^/]+$/.test(pathname);
    if (!validPath) navigate(isClient ? "/client" : "/employee/queue", { replace: true });
  }, [user, pathname, navigate]);

  function logout() { clearToken(); setUser(null); navigate("/login", { replace: true }); }
  if (checking) return <div className="boot"><Skeleton rows={3} /></div>;
  if (!user) return <LoginPage onLogin={(nextUser) => { setUser(nextUser); navigate(nextUser.role === "CLIENT" ? "/client" : "/employee/queue", { replace: true }); }} />;
  const backPath = pathname === "/client/new/application" ? "/client/new"
    : pathname === "/client/new" || /^\/client\/applications\//.test(pathname) ? "/client"
      : /^\/employee\/applications\//.test(pathname) ? "/employee/queue" : null;
  return <AppShell user={user} onLogout={logout} area={user.role === "CLIENT" ? "Кредитный кабинет" : "Рассмотрение заявок"} onBack={backPath ? () => navigate(backPath, { replace: true }) : null}>
    {user.role === "CLIENT" ? <ClientWorkspace pathname={pathname} navigate={navigate} /> : <EmployeeWorkspace pathname={pathname} navigate={navigate} />}
  </AppShell>;
}
