import { useEffect } from "react";
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
