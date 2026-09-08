import React, { useEffect, useState } from "react";
import { api } from "./api";
import Shell from "./Shell";
import Dashboard from "./pages/Dashboard";
import Knowledge from "./pages/Knowledge";
import Projects from "./pages/Projects";
import ProjectWorkspace from "./pages/ProjectWorkspace";
import Assets from "./pages/Assets";
import Quality from "./pages/Quality";
import SystemSettings from "./pages/SystemSettings";
import Login from "./pages/Login";

function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "projects" && parts[1]) return { section: "projects", page: "workspace", projectId: Number(parts[1]) };
  return { section: parts[0] || "dashboard", page: parts[1] || "" };
}

export default function App() {
  const [route, setRoute] = useState(parseRoute());
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [auth, setAuth] = useState({ loading: true, enabled: false, user: null, oidc_enabled: false });

  async function refreshAuth() {
    try {
      const config = await api("/api/auth/config");
      if (!config.enabled) { setAuth({ loading: false, ...config, user: null }); return; }
      try {
        const session = await api("/api/auth/me");
        setAuth({ loading: false, ...config, user: session.user });
      } catch {
        setAuth({ loading: false, ...config, user: null });
      }
    } catch { setAuth({ loading: false, enabled: false, user: null, oidc_enabled: false }); }
  }

  async function refreshStatus() {
    try { setStatus(await api("/api/status")); setError(""); }
    catch (nextError) { setError(nextError.message); }
  }

  useEffect(() => {
    const onHash = () => setRoute(parseRoute());
    window.addEventListener("hashchange", onHash);
    refreshStatus();
    refreshAuth();
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  if (auth.loading) return null;
  if (auth.enabled && !auth.user) return <Login oidcEnabled={auth.oidc_enabled} onLogin={refreshAuth} />;

  let page;
  if (route.section === "knowledge") page = <Knowledge initialTab={route.page} onChanged={refreshStatus} />;
  else if (route.section === "projects" && route.projectId) page = <ProjectWorkspace projectId={route.projectId} />;
  else if (route.section === "projects") page = <Projects />;
  else if (route.section === "assets") page = <Assets />;
  else if (route.section === "quality") page = <Quality />;
  else if (route.section === "settings") page = <SystemSettings />;
  else page = <Dashboard status={status} />;

  return <Shell route={route} status={status} user={auth.user} onLogout={async () => { await postLogout(); await refreshAuth(); }}>{error && <div className="global-error">{error}</div>}{page}</Shell>;
}

async function postLogout() {
  await api("/api/auth/logout", { method: "POST", body: "{}" });
}
