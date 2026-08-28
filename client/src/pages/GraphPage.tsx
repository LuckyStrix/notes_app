import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import {
  useEdgeSummary,
  useGenerateAllSummaries,
  useGenerateEdgeQualitySummary,
  useGenerateKeywordQualitySummary,
  useGraph,
  useKeywordSummary,
  useProject,
  useRebuildGraph,
  useSettings,
} from "../api/hooks";
import CitationLink from "../components/chat/CitationLink";
import GraphView from "../components/graph/GraphView";
import MarkdownContent from "../components/MarkdownContent";

type Selection =
  | { type: "node"; id: string; label: string }
  | { type: "edge"; source: string; target: string; sourceLabel: string; targetLabel: string };

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function GraphPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const queryClient = useQueryClient();
  const [significance, setSignificance] = useState(0.3);
  const { data: graph, isLoading } = useGraph(projectId, significance);
  const [selection, setSelection] = useState<Selection | null>(null);
  const rebuildGraph = useRebuildGraph(projectId);
  const generateAll = useGenerateAllSummaries(projectId);
  const { data: settings } = useSettings();

  // Poll the project row while a rebuild or a "Generate All" batch is in
  // flight (mirrors Note.status), instead of guessing how long either takes
  // with a fixed timer.
  const { data: project } = useProject(projectId);
  const rebuilding = project?.graph_status === "processing";
  const generatingAll = project?.summary_generation_status === "processing";
  const prevGraphStatus = useRef(project?.graph_status);
  const prevSummaryStatus = useRef(project?.summary_generation_status);
  useEffect(() => {
    if (prevGraphStatus.current === "processing" && project?.graph_status === "ready") {
      queryClient.invalidateQueries({ queryKey: ["graph", projectId] });
    }
    prevGraphStatus.current = project?.graph_status;
  }, [project?.graph_status, projectId, queryClient]);
  useEffect(() => {
    if (prevSummaryStatus.current === "processing" && project?.summary_generation_status === "ready") {
      queryClient.invalidateQueries({ queryKey: ["graph-summary"] });
    }
    prevSummaryStatus.current = project?.summary_generation_status;
  }, [project?.summary_generation_status, queryClient]);

  function handleRebuild() {
    rebuildGraph.mutate();
  }

  function handleGenerateAll() {
    generateAll.mutate();
  }

  const nodeSel = selection?.type === "node" ? selection : null;
  const edgeSel = selection?.type === "edge" ? selection : null;
  const keywordSummary = useKeywordSummary(projectId, nodeSel?.id);
  const edgeSummary = useEdgeSummary(projectId, edgeSel?.source, edgeSel?.target);
  const activeSummary = nodeSel ? keywordSummary : edgeSel ? edgeSummary : null;

  const generateKeywordQuality = useGenerateKeywordQualitySummary(projectId);
  const generateEdgeQuality = useGenerateEdgeQualitySummary(projectId);
  const qualityPending = nodeSel ? generateKeywordQuality.isPending : generateEdgeQuality.isPending;

  function handleHighQualitySummary() {
    if (nodeSel) generateKeywordQuality.mutate(nodeSel.id);
    else if (edgeSel) generateEdgeQuality.mutate({ source: edgeSel.source, target: edgeSel.target });
  }

  if (!projectId) return null;

  const fallbackTitle = nodeSel?.label ?? (edgeSel ? `${edgeSel.sourceLabel} <-> ${edgeSel.targetLabel}` : "");
  const fastModelConfigured = !!settings?.ollama_fast_model;

  return (
    <div className="page graph-page">
      <h1>Keyword graph</h1>

      <div className="card form-inline" style={{ alignItems: "center" }}>
        <label className="muted" htmlFor="sig-slider">Significance</label>
        <input
          id="sig-slider"
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={significance}
          onChange={(e) => setSignificance(parseFloat(e.target.value))}
          style={{ flex: 1 }}
        />
        <span className="muted">{significance.toFixed(2)}</span>
        <button type="button" onClick={handleRebuild} disabled={rebuildGraph.isPending || rebuilding}>
          {rebuilding ? "Rebuilding…" : "Regenerate graph"}
        </button>
        <button
          type="button"
          onClick={handleGenerateAll}
          disabled={generateAll.isPending || generatingAll || !fastModelConfigured}
          title={fastModelConfigured ? "Generate a basic summary for every topic and connection" : "Set a fast Ollama model in Settings first"}
        >
          {generatingAll
            ? `Generating… (${project?.summary_generation_progress ?? 0}/${project?.summary_generation_total ?? 0})`
            : "Generate all"}
        </button>
      </div>
      {project?.graph_status === "error" && project.graph_error && (
        <p className="error">Graph rebuild failed: {project.graph_error}</p>
      )}
      {project?.summary_generation_status === "error" && project.summary_generation_error && (
        <p className="error">Generate all failed: {project.summary_generation_error}</p>
      )}
      {!fastModelConfigured && (
        <p className="muted">
          "Generate all" needs a fast Ollama model configured in Settings before it can run.
        </p>
      )}

      {isLoading && !graph && <p>Loading…</p>}
      {graph && graph.nodes.length === 0 && (
        <p className="muted">No keywords at this significance level — try lowering the slider, or add more notes.</p>
      )}

      {graph && graph.nodes.length > 0 && (
        <>
          <div className="graph-layout">
            <div className="card graph-card">
              <GraphView
                graph={graph}
                onSelectNode={(id, label) => setSelection({ type: "node", id, label })}
                onSelectEdge={(source, target, sourceLabel, targetLabel) =>
                  setSelection({ type: "edge", source, target, sourceLabel, targetLabel })
                }
              />
            </div>

            {selection && (
              <div className="card graph-summary-panel">
                <div className="graph-summary-header">
                  <h3>{activeSummary?.data?.title ?? fallbackTitle}</h3>
                  <button className="icon-btn" title="Close" onClick={() => setSelection(null)}>✕</button>
                </div>

                {activeSummary?.isLoading && <p className="muted">Loading…</p>}
                {activeSummary?.isError && <p className="error">Couldn't load a summary. Try again.</p>}

                {activeSummary?.data && (
                  <>
                    {activeSummary.data.tier && (
                      <p className="muted graph-summary-meta">
                        {activeSummary.data.tier === "quality" ? "High quality" : "Basic"}
                        {activeSummary.data.generated_at && ` · ${formatTimestamp(activeSummary.data.generated_at)}`}
                      </p>
                    )}
                    {activeSummary.data.content ? (
                      <MarkdownContent content={activeSummary.data.content} />
                    ) : (
                      <p className="muted">No summary yet — click "High quality summary" below to generate one.</p>
                    )}
                    {activeSummary.data.citations.length > 0 && (
                      <div className="citation-list">
                        {activeSummary.data.citations.map((c) => (
                          <CitationLink key={c.ordinal} projectId={projectId} citation={c} />
                        ))}
                      </div>
                    )}
                  </>
                )}

                <button type="button" onClick={handleHighQualitySummary} disabled={qualityPending} style={{ marginTop: "0.75rem" }}>
                  {qualityPending ? "Generating…" : "High quality summary"}
                </button>
              </div>
            )}
          </div>

          <p className="muted" style={{ marginTop: "0.75rem" }}>
            {graph.nodes.length} keywords, {graph.edges.length} connections shown. Click a topic or connection for a summary.
          </p>
        </>
      )}
    </div>
  );
}
