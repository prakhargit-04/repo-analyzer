"use client";

import { useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";

type GraphNode = {
  id: string;
  type?: string;
  name?: string;
  file?: string;
  start_line?: number;
  end_line?: number;
  class_owner?: string | null;
  provenance?: string;
};

type GraphEdge = {
  source: string;
  target: string;
  relation?: string;
  confidence?: string;
  raw_call?: string;
  reason?: string;
  provenance?: string;
  line?: number;
  alias?: string | null;
};

type AnalysisData = {
  repository: string;
  commit_sha: string;
  files_analyzed: number;
  knowledge_graph_summary: {
    total_nodes: number;
    total_edges: number;
    call_edges_total: number;
    call_edges_resolved_pct: number;
  };
  knowledge_graph: {
    nodes: GraphNode[];
    edges: GraphEdge[];
  };
  health_score: {
    composite_health_score: number;
    status: string;
    sub_scores: {
      complexity: number;
      maintainability: number;
      security: number;
    };
  };
};

export default function Home() {
  const [data, setData] = useState<AnalysisData | null>(null);

  useEffect(() => {
    fetch("/output.json")
      .then((response) => response.json())
      .then((result) => setData(result));
  }, []);

  const fileNodes = useMemo(() => {
    if (!data) {
      return [];
    }

    return data.knowledge_graph.nodes.filter(
      (node) => node.type === "file"
    );
  }, [data]);

  const fileNodeMap = useMemo(() => {
    const map = new Map<string, string>();

    if (!data) {
      return map;
    }

    data.knowledge_graph.nodes.forEach((node) => {
      if (node.type === "function" || node.type === "class") {
        if (node.file) {
          map.set(node.id, node.file);
        }
      }

      if (node.type === "file") {
        map.set(node.id, node.id);
      }
    });

    return map;
  }, [data]);

  const architectureEdges = useMemo(() => {
    if (!data) {
      return [];
    }

    const edgeSet = new Set<string>();

    return data.knowledge_graph.edges
      .filter((edge) => edge.relation === "calls")
      .map((edge) => {
        const sourceFile = fileNodeMap.get(edge.source);
        const targetFile = fileNodeMap.get(edge.target);

        if (!sourceFile || !targetFile || sourceFile === targetFile) {
          return null;
        }

        const key = `${sourceFile}->${targetFile}`;

        if (edgeSet.has(key)) {
          return null;
        }

        edgeSet.add(key);

        return {
          id: `architecture-${sourceFile}-${targetFile}`,
          source: sourceFile,
          target: targetFile,
          animated: true,
          label: "calls",
          style: {
            strokeWidth: 2,
          },
        };
      })
      .filter(Boolean) as Edge[];
  }, [data, fileNodeMap]);

  const flowNodes = useMemo<Node[]>(() => {
    if (!data) {
      return [];
    }

    const columns = 3;

    return fileNodes.map((node, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);

      return {
        id: node.id,
        position: {
          x: column * 420,
          y: row * 220,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: (
            <div className="w-[250px]">
              <div className="text-base font-semibold text-white">
                {node.id}
              </div>

              <div className="text-xs text-slate-400 mt-2">
                File
              </div>

              <div className="text-xs text-slate-500 mt-1">
                {node.provenance || "filesystem-walk"}
              </div>
            </div>
          ),
        },
        style: {
          background: "#0f172a",
          border: "1px solid #475569",
          borderRadius: "12px",
          color: "white",
          padding: "14px",
          width: 280,
        },
      };
    });
  }, [data, fileNodes]);

  if (!data) {
    return (
      <main className="min-h-screen bg-slate-950 text-white flex items-center justify-center">
        Loading analyzer results...
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 text-white p-8">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-4xl font-bold">
          GitHub Project Analyzer
        </h1>

        <p className="text-slate-400 mt-2">
          Repository intelligence dashboard
        </p>

        <div className="mt-8 bg-slate-900 border border-slate-800 rounded-xl p-6">
          <p className="text-slate-400 text-sm">
            Repository
          </p>

          <p className="text-lg mt-1">
            {data.repository}
          </p>

          <p className="text-slate-400 text-sm mt-4">
            Commit
          </p>

          <p className="text-sm mt-1 font-mono break-all">
            {data.commit_sha}
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-5 mt-6">
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <p className="text-slate-400">
              Health Score
            </p>

            <p className="text-4xl font-bold mt-2">
              {data.health_score.composite_health_score}
            </p>

            <p className="text-sm text-slate-400 mt-2">
              {data.health_score.status}
            </p>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <p className="text-slate-400">
              Files
            </p>

            <p className="text-4xl font-bold mt-2">
              {data.files_analyzed}
            </p>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <p className="text-slate-400">
              Graph Nodes
            </p>

            <p className="text-4xl font-bold mt-2">
              {data.knowledge_graph_summary.total_nodes}
            </p>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <p className="text-slate-400">
              Graph Edges
            </p>

            <p className="text-4xl font-bold mt-2">
              {data.knowledge_graph_summary.total_edges}
            </p>
          </div>
        </div>

        <div className="mt-8">
          <h2 className="text-2xl font-bold">
            Health Breakdown
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mt-4">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
              <p className="text-slate-400">
                Complexity
              </p>

              <p className="text-3xl font-bold mt-2">
                {data.health_score.sub_scores.complexity}
              </p>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
              <p className="text-slate-400">
                Maintainability
              </p>

              <p className="text-3xl font-bold mt-2">
                {data.health_score.sub_scores.maintainability}
              </p>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
              <p className="text-slate-400">
                Security
              </p>

              <p className="text-3xl font-bold mt-2">
                {data.health_score.sub_scores.security}
              </p>
            </div>
          </div>
        </div>

        <div className="mt-8 bg-slate-900 border border-slate-800 rounded-xl p-6">
          <h2 className="text-2xl font-bold">
            Knowledge Graph Summary
          </h2>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-5 mt-5">
            <div>
              <p className="text-slate-400">
                Total Nodes
              </p>

              <p className="text-2xl font-bold">
                {data.knowledge_graph_summary.total_nodes}
              </p>
            </div>

            <div>
              <p className="text-slate-400">
                Total Edges
              </p>

              <p className="text-2xl font-bold">
                {data.knowledge_graph_summary.total_edges}
              </p>
            </div>

            <div>
              <p className="text-slate-400">
                Call Edges
              </p>

              <p className="text-2xl font-bold">
                {data.knowledge_graph_summary.call_edges_total}
              </p>
            </div>

            <div>
              <p className="text-slate-400">
                Resolved
              </p>

              <p className="text-2xl font-bold">
                {data.knowledge_graph_summary.call_edges_resolved_pct}%
              </p>
            </div>
          </div>
        </div>

        <div className="mt-8">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-2xl font-bold">
                Repository Architecture
              </h2>

              <p className="text-slate-400 text-sm mt-1">
                High-level file relationships
              </p>
            </div>

            <div className="text-sm text-slate-400">
              {fileNodes.length} files
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <div className="h-[700px]">
              <ReactFlow
                nodes={flowNodes}
                edges={architectureEdges}
                fitView
                fitViewOptions={{
                  padding: 0.2,
                }}
                attributionPosition="bottom-left"
              >
                <Background />
                <Controls />
                <MiniMap />
              </ReactFlow>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
