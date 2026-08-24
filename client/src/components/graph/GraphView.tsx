import cytoscape, { type Core } from "cytoscape";
import { useEffect, useRef } from "react";

import type { Graph } from "../../api/types";

interface Props {
  graph: Graph;
  onSelectNode?: (nodeId: string, label: string) => void;
  onSelectEdge?: (sourceId: string, targetId: string, sourceLabel: string, targetLabel: string) => void;
}

export default function GraphView({ graph, onSelectNode, onSelectEdge }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // Canvas fillStyle doesn't resolve CSS var() itself, so read the
    // computed value up front to stay theme-aware in both light and dark.
    const rootStyle = getComputedStyle(document.documentElement);
    const fgColor = rootStyle.getPropertyValue("--fg").trim() || "#1a1a1f";

    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...graph.nodes.map((n) => ({
          data: { id: n.id, label: n.label, significance: n.significance, noteCount: n.note_count },
        })),
        ...graph.edges.map((e) => ({
          data: { id: `${e.source}-${e.target}`, source: e.source, target: e.target, significance: e.significance },
        })),
      ],
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "font-size": 11,
            color: fgColor,
            "text-valign": "bottom",
            "text-margin-y": 4,
            width: "mapData(significance, 0, 1, 18, 55)",
            height: "mapData(significance, 0, 1, 18, 55)",
            "background-color": "mapData(significance, 0, 1, #a5b4fc, #6366f1)",
            "border-width": 1,
            "border-color": "#4338ca",
          },
        },
        {
          selector: "node:selected",
          style: { "border-width": 3, "border-color": "#f59e0b" },
        },
        {
          selector: "edge",
          style: {
            width: "mapData(significance, 0, 1, 1, 5)",
            "line-color": "mapData(significance, 0, 1, #d1d5db, #6366f1)",
            "curve-style": "haystack",
            opacity: 0.7,
          },
        },
        {
          selector: "edge:selected",
          style: { "line-color": "#f59e0b", opacity: 1 },
        },
      ],
      layout: { name: "cose", animate: false, padding: 30 },
      wheelSensitivity: 0.3,
    });

    if (onSelectNode) {
      cy.on("tap", "node", (evt) => {
        const node = evt.target;
        onSelectNode(node.id(), node.data("label"));
      });
    }

    if (onSelectEdge) {
      cy.on("tap", "edge", (evt) => {
        const edge = evt.target;
        onSelectEdge(edge.source().id(), edge.target().id(), edge.source().data("label"), edge.target().data("label"));
      });
    }

    const container = containerRef.current;
    cy.on("mouseover", "node, edge", () => {
      if (container) container.style.cursor = "pointer";
    });
    cy.on("mouseout", "node, edge", () => {
      if (container) container.style.cursor = "default";
    });

    cyRef.current = cy;
    return () => cy.destroy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  return <div ref={containerRef} style={{ width: "100%", height: "100%", borderRadius: 10 }} />;
}
