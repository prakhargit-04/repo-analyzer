"use client";

import React from "react";

const CONFIG: Record<string, { bg: string; text: string; border: string }> = {
  HIGH: {
    bg: "bg-rose-900/60",
    text: "text-rose-300",
    border: "border-rose-700",
  },
  MEDIUM: {
    bg: "bg-amber-900/60",
    text: "text-amber-300",
    border: "border-amber-700",
  },
  LOW: {
    bg: "bg-blue-900/60",
    text: "text-blue-300",
    border: "border-blue-700",
  },
  INFO: {
    bg: "bg-slate-800",
    text: "text-slate-400",
    border: "border-slate-700",
  },
};

interface SeverityBadgeProps {
  severity?: string | null;
}

export function SeverityBadge({ severity }: SeverityBadgeProps) {
  const key = (severity || "INFO").toUpperCase();
  const cfg = CONFIG[key] ?? CONFIG.INFO;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold border ${cfg.bg} ${cfg.text} ${cfg.border}`}
    >
      {key}
    </span>
  );
}
