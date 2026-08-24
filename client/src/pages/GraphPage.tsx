import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

import { useEdgeSummary, useGraph, useKeywordSummary, useRebuildGraph } from "../api/hooks";
import CitationLink from "../components/chat/CitationLink";
import GraphView from "../components/graph/GraphView";

type Selection =
  | { type: "node"; id: string; label: string }
  | { type: "edge"; source: string; target: string; sourceLabel: string; targetLabel: string };

export default function GraphPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const queryClient = useQueryClient();
  const [significance, setSignificance] = useState(0.3);
  const { data: graph, isLoading } = useGraph(projectId, significance);
  const [selection, setSelection] = useState<Selection | null>(null);
  const rebuildGraph = useRebuildGraph(projectId);
  const [rebuildQueued, setRebuildQueued] = useState(false);

  function handleRebuild() {
    rebuildGraph.mutate(undefined, {
      onSuccess: () => {
        setRebuildQueued(true);
        setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: ["graph", projectId] });
          setRebuildQueued(false);
        }, 5000);
      },
    });
  }

  const nodeSel = selection?.type === "node" ? selection : null;
  const edgeSel = selection?.type === "edge" ? selection : null;
  const keywordSummary = useKeywordSummary(projectId, nodeSel?.id);
  const edgeSummary = useEdgeSummary(projectId, edgeSel?.source, edgeSel?.target);
  const activeSummary = nodeSel ? keywordSummary : edgeSel ? edgeSummary : null;

  if (!projectId) return null;

  const fallbackTitle = nodeSel?.label ?? (edgeSel ? `${edgeSel.sourceLabel} <-> ${edgeSel.targetLabel}` : "");

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
        <button type="button" onClick={handleRebuild} disabled={rebuildGraph.isPending || rebuildQueued}>
          {rebuildQueued ? "Queued — refreshing shortly…" : "Regenerate graph"}
        </button>
      </div>

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
                  <button
                    className="icon-btn"
                    title="Regenerate"
                    disabled={activeSummary?.isFetching}
                    onClick={() => activeSummary?.refetch()}
                  >
                    {activeSummary?.isFetching ? "…" : "⟳"}
                  </button>
                  <button className="icon-btn" title="Close" onClick={() => setSelection(null)}>✕</button>
                </div>

                {activeSummary?.isLoading && <p className="muted">Generating summary…</p>}
                {activeSummary?.isError && <p className="error">Couldn't generate a summary. Try again.</p>}
                {activeSummary?.data && (
                  <>
                    <p style={{ whiteSpace: "pre-wrap" }}>{activeSummary.data.content}</p>
                    {activeSummary.data.citations.length > 0 && (
                      <div className="citation-list">
                        {activeSummary.data.citations.map((c) => (
                          <CitationLink key={c.ordinal} projectId={projectId} citation={c} />
                        ))}
                      </div>
                    )}
                  </>
                )}
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
