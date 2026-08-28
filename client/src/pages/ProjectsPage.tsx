import { useState, type DragEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { useCreateProject, useDeleteProject, useProjects, useReorderProjects } from "../api/hooks";
import type { Project } from "../api/types";

export default function ProjectsPage() {
  const { data: projects, isLoading, error } = useProjects();
  const createProject = useCreateProject();
  const deleteProject = useDeleteProject();
  const reorderProjects = useReorderProjects();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const [dragId, setDragId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    createProject.mutate(
      { name: name.trim(), description: description.trim() || undefined },
      { onSuccess: () => { setName(""); setDescription(""); } },
    );
  }

  function handleDragOver(e: DragEvent, targetId: string) {
    if (!dragId || dragId === targetId) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDropTargetId(targetId);
  }

  function handleDrop(e: DragEvent, targetId: string) {
    e.preventDefault();
    if (dragId && dragId !== targetId && projects) {
      const ids = projects.map((p: Project) => p.id);
      const fromIndex = ids.indexOf(dragId);
      const toIndex = ids.indexOf(targetId);
      if (fromIndex !== -1 && toIndex !== -1) {
        ids.splice(fromIndex, 1);
        ids.splice(toIndex, 0, dragId);
        reorderProjects.mutate(ids);
      }
    }
    setDragId(null);
    setDropTargetId(null);
  }

  return (
    <div className="page">
      <h1>Projects</h1>

      <form className="card form-inline" onSubmit={handleCreate}>
        <input
          placeholder="Project name (e.g. CS 401 - Distributed Systems)"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          placeholder="Description (optional)"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <button type="submit" disabled={createProject.isPending || !name.trim()}>
          New project
        </button>
      </form>

      {isLoading && <p>Loading…</p>}
      {error && <p className="error">{(error as Error).message}</p>}

      <ul className="project-list">
        {projects?.map((project) => (
          <li
            key={project.id}
            className={`card project-item${dragId === project.id ? " dragging" : ""}${dropTargetId === project.id ? " drop-target" : ""}`}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = "move";
              setDragId(project.id);
            }}
            onDragEnd={() => {
              setDragId(null);
              setDropTargetId(null);
            }}
            onDragOver={(e) => handleDragOver(e, project.id)}
            onDragLeave={() => setDropTargetId((current) => (current === project.id ? null : current))}
            onDrop={(e) => handleDrop(e, project.id)}
          >
            <span className="drag-handle" title="Drag to reorder">⠿</span>
            <Link to={`/projects/${project.id}`}>
              <strong>{project.name}</strong>
              {project.description && <span> — {project.description}</span>}
            </Link>
            <button
              className="project-delete-btn"
              title="Delete project"
              onClick={() => {
                if (confirm(`Delete "${project.name}" and everything in it?`)) {
                  deleteProject.mutate(project.id);
                }
              }}
            >
              Delete
            </button>
          </li>
        ))}
        {projects && projects.length === 0 && <p className="muted">No projects yet — create one above.</p>}
      </ul>
    </div>
  );
}
