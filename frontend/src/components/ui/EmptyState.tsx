"use client";

import React from "react";

interface EmptyStateProps {
  title: string;
  description?: string;
}

export function EmptyState({ title, description }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-2 text-center px-4">
      <div className="w-12 h-12 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center mb-2 text-slate-500 text-xl">
        ∅
      </div>
      <p className="text-slate-300 font-medium">{title}</p>
      {description && (
        <p className="text-slate-500 text-sm max-w-md">{description}</p>
      )}
    </div>
  );
}
