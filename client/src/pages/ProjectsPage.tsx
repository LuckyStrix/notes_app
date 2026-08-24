import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { useCreateProject, useDeleteProject, useProjects } from "../api/hooks";

export default function ProjectsPage() {
  const { data: projects, isLoading, error } = useProjects();
  const createProject = useCreateProject();
  const deleteProject = useDeleteProject();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    createProject.mutate(
      { name: name.trim(), description: description.trim() || undefined },
      { onSuccess: () => { setName(""); setDescription(""); } },
    );
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
          <li key={project.id} className="card project-item">
            <Link to={`/projects/${project.id}`}>
              <strong>{project.name}</strong>
              {project.description && <p className="muted">{project.description}</p>}
            </Link>
            <button
              className="danger-link"
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
