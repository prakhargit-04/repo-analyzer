"use client";

import React from "react";

interface StatusBadgeProps {
  status?: string | null;
  /** Override the displayed text while keeping status-based colouring. */
  label?: string;
}

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const s = (status || "unknown").toLowerCase();

  let classes =
    "bg-slate-800 text-slate-400 border-slate-700"; // default / unknown

  if (s === "success" || s === "complete" || s === "completed") {
    classes = "bg-emerald-900/60 text-emerald-300 border-emerald-700";
  } else if (s === "partial") {
    classes = "bg-amber-900/60 text-amber-300 border-amber-700";
  } else if (s === "failed" || s === "error") {
    classes = "bg-rose-900/60 text-rose-300 border-rose-700";
  } else if (s === "skipped" || s === "unsupported") {
    classes = "bg-slate-800 text-slate-500 border-slate-700";
  } else if (s === "running") {
    classes = "bg-blue-900/60 text-blue-300 border-blue-700 animate-pulse";
  }

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${classes}`}
    >
      {label ?? status ?? "unknown"}
    </span>
  );
}
