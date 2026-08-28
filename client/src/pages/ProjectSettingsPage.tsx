import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { useProject, useSettings, useUpdateProject } from "../api/hooks";

export default function ProjectSettingsPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project } = useProject(projectId);
  const { data: settings } = useSettings();
  const updateProject = useUpdateProject();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [topKOverride, setTopKOverride] = useState(false);
  const [topK, setTopK] = useState(6);
  const [floorOverride, setFloorOverride] = useState(false);
  const [floor, setFloor] = useState(0.35);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!project || !settings) return;
    setName(project.name);
    setDescription(project.description ?? "");
    setTopKOverride(project.rag_top_k !== null);
    setTopK(project.rag_top_k ?? settings.default_rag_top_k);
    setFloorOverride(project.rag_similarity_floor !== null);
    setFloor(project.rag_similarity_floor ?? settings.default_rag_similarity_floor);
  }, [project, settings]);

  if (!projectId || !project || !settings) return <p className="page">Loading…</p>;

  function save() {
    setSaved(false);
    const trimmedName = name.trim();
    updateProject.mutate(
      {
        projectId: projectId!,
        payload: {
          name: trimmedName || project!.name,
          description: description.trim() || null,
          rag_top_k: topKOverride ? topK : null,
          rag_similarity_floor: floorOverride ? floor : null,
        },
      },
      { onSuccess: () => setSaved(true) },
    );
  }

  return (
    <div className="page">
      <Link to={`/projects/${projectId}`} className="sidebar-back">&larr; Back to {project.name}</Link>
      <h1>Project settings</h1>
      <p className="muted">
        Name, description, and AI-retrieval overrides for <strong>{project.name}</strong> only — everything else
        lives in the global <Link to="/settings">Settings</Link> page.
      </p>

      <section className="card">
        <h2>General</h2>
        <label className="muted">Name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={project.name} />
        <label className="muted">Description</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Optional"
          rows={3}
        />
      </section>

      <section className="card">
        <h2>Context chunk count</h2>
        <p className="muted">
          How many note excerpts get pulled into context per chat question. Global default:{" "}
          <strong>{settings.default_rag_top_k}</strong>. A project with a lot of scattered, distinct notes may need
          more; if chat starts saying it "can't find" something that's clearly in your notes, that's usually a sign
          the model is getting distracted by too much context at once — try fewer.
        </p>
        <label className="form-inline">
          <input type="checkbox" checked={topKOverride} onChange={(e) => setTopKOverride(e.target.checked)} />
          Override for this project
        </label>
        <input
          type="number"
          min={1}
          max={50}
          disabled={!topKOverride}
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value))}
        />
      </section>

      <section className="card">
        <h2>Relevance floor</h2>
        <p className="muted">
          How relevant (0-1 cosine similarity) an excerpt has to be to get included at all. Global default:{" "}
          <strong>{settings.default_rag_similarity_floor}</strong>. Raise it to cut out weakly-related noise; lower
          it if chat says it can't find something that should have matched.
        </p>
        <label className="form-inline">
          <input type="checkbox" checked={floorOverride} onChange={(e) => setFloorOverride(e.target.checked)} />
          Override for this project
        </label>
        <input
          type="number"
          min={0}
          max={1}
          step={0.05}
          disabled={!floorOverride}
          value={floor}
          onChange={(e) => setFloor(Number(e.target.value))}
        />
      </section>

      <button onClick={save} disabled={updateProject.isPending}>Save</button>
      {saved && <span className="muted" style={{ marginLeft: "0.75rem" }}>Saved.</span>}
    </div>
  );
}
