"use client";

import React, { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";

interface GraphNodeData {
  id: string;
  type?: string;
  name?: string;
  file?: string;
  provenance?: string;
  [key: string]: unknown;
}

interface GraphEdgeData {
  source: string;
  target: string;
  relation?: string;
  confidence?: string;
  provenance?: string;
  [key: string]: unknown;
}


interface GraphViewProps {
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
}

export const GraphView: React.FC<GraphViewProps> = ({ nodes, edges }) => {
  const fileNodes = useMemo(() => {
    return nodes.filter((node) => node.type === "file");
  }, [nodes]);

  const fileNodeMap = useMemo(() => {
    const map = new Map<string, string>();
    nodes.forEach((node) => {
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
  }, [nodes]);

  const architectureEdges = useMemo(() => {
    const edgeSet = new Set<string>();

    return edges
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
  }, [edges, fileNodeMap]);

  const flowNodes = useMemo<Node[]>(() => {
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
              <div className="text-base font-semibold text-white truncate" title={node.id}>
                {node.id}
              </div>
              <div className="text-xs text-slate-400 mt-2">File</div>
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
  }, [fileNodes]);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
      <div className="h-[700px]">
        <ReactFlow
          nodes={flowNodes}
          edges={architectureEdges}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          attributionPosition="bottom-left"
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </div>
    </div>
  );
};
