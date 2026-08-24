import { useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { Outlet, useParams } from "react-router-dom";

import Sidebar from "../components/workspace/Sidebar";

const WIDTH_STORAGE_KEY = "notes_app_sidebar_width";
const MIN_WIDTH = 200;
const MAX_WIDTH = 640;
const DEFAULT_WIDTH = 280;

function loadStoredWidth(): number {
  const stored = Number(localStorage.getItem(WIDTH_STORAGE_KEY));
  return stored >= MIN_WIDTH && stored <= MAX_WIDTH ? stored : DEFAULT_WIDTH;
}

export default function ProjectWorkspacePage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [width, setWidth] = useState(loadStoredWidth);
  const widthRef = useRef(width);
  const resizing = useRef(false);
  const [isResizing, setIsResizing] = useState(false);

  useEffect(() => {
    function onMouseMove(e: globalThis.MouseEvent) {
      if (!resizing.current) return;
      const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, e.clientX));
      widthRef.current = next;
      setWidth(next);
    }
    function onMouseUp() {
      if (!resizing.current) return;
      resizing.current = false;
      setIsResizing(false);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      localStorage.setItem(WIDTH_STORAGE_KEY, String(widthRef.current));
    }
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, []);

  function startResize(e: ReactMouseEvent) {
    e.preventDefault();
    resizing.current = true;
    setIsResizing(true);
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  if (!projectId) return null;

  return (
    <div className="workspace">
      <aside className="workspace-sidebar" style={{ width }}>
        <Sidebar projectId={projectId} />
      </aside>
      <div
        className={`sidebar-resize-handle${isResizing ? " active" : ""}`}
        onMouseDown={startResize}
      />
      <div className="workspace-content">
        <Outlet />
      </div>
    </div>
  );
}
