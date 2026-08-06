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

function parseRoute() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "projects" && parts[1]) return { section: "projects", page: "workspace", projectId: Number(parts[1]) };
  return { section: parts[0] || "dashboard", page: parts[1] || "" };
}

export default function App() {
  const [route, setRoute] = useState(parseRoute());
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");

  async function refreshStatus() {
    try { setStatus(await api("/api/status")); setError(""); }
    catch (nextError) { setError(nextError.message); }
  }

  useEffect(() => {
    const onHash = () => setRoute(parseRoute());
    window.addEventListener("hashchange", onHash);
    refreshStatus();
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  let page;
  if (route.section === "knowledge") page = <Knowledge initialTab={route.page} onChanged={refreshStatus} />;
  else if (route.section === "projects" && route.projectId) page = <ProjectWorkspace projectId={route.projectId} />;
  else if (route.section === "projects") page = <Projects />;
  else if (route.section === "assets") page = <Assets />;
  else if (route.section === "quality") page = <Quality />;
  else if (route.section === "settings") page = <SystemSettings />;
  else page = <Dashboard status={status} />;

  return <Shell route={route} status={status}>{error && <div className="global-error">{error}</div>}{page}</Shell>;
}
