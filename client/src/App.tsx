import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";

import { useSettings } from "./api/hooks";
import ChatPage from "./pages/ChatPage";
import GraphPage from "./pages/GraphPage";
import NoteViewerPage from "./pages/NoteViewerPage";
import ProjectSettingsPage from "./pages/ProjectSettingsPage";
import ProjectWorkspacePage from "./pages/ProjectWorkspacePage";
import ProjectsPage from "./pages/ProjectsPage";
import SearchPage from "./pages/SearchPage";
import SettingsPage from "./pages/SettingsPage";
import WorkspaceEmptyState from "./pages/WorkspaceEmptyState";

const ANALYSIS_PORT = 8090;

// Link to the optional analysis_ai add-on (its own service on another port).
// Only shown while that service is actually reachable, so the app looks exactly
// as before when the add-on isn't running. no-cors: we only need to know
// whether something answered, not read the response.
function AnalysisLink() {
  const base = `${window.location.protocol}//${window.location.hostname}:${ANALYSIS_PORT}`;
  const [up, setUp] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const probe = () => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2000);
      fetch(`${base}/api/ping`, { mode: "no-cors", signal: controller.signal })
        .then(() => !cancelled && setUp(true))
        .catch(() => !cancelled && setUp(false))
        .finally(() => clearTimeout(timer));
    };
    probe();
    const interval = setInterval(probe, 60_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [base]);

  if (!up) return null;
  return (
    <a href={base} style={{ marginRight: "1rem" }}>
      Analysis
    </a>
  );
}

export default function App() {
  const location = useLocation();
  const isWorkspace = /^\/projects\/[^/]+/.test(location.pathname);
  const { data: settings } = useSettings();
  const appName = settings?.app_name || "notes_app";

  useEffect(() => {
    document.title = appName;
  }, [appName]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <NavLink to="/" className="brand" end>
          {appName}
        </NavLink>
        <nav className="nav-links">
          <AnalysisLink />
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </header>
      <main className={`app-main${isWorkspace ? " app-main-full" : ""}`}>
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectWorkspacePage />}>
            <Route index element={<WorkspaceEmptyState />} />
            <Route path="notes/:noteId" element={<NoteViewerPage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="graph" element={<GraphPage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="settings" element={<ProjectSettingsPage />} />
          </Route>
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
