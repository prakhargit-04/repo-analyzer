"use client";

import React from "react";

interface LoadingSpinnerProps {
  label?: string;
}

export function LoadingSpinner({ label = "Loading…" }: LoadingSpinnerProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3">
      <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      <p className="text-slate-400 text-sm">{label}</p>
    </div>
  );
}
