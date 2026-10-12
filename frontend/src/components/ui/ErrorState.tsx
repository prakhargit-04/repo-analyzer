"use client";

import React from "react";

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3 px-4">
      <div className="bg-rose-950/60 border border-rose-800 rounded-xl p-6 max-w-lg w-full text-center">
        <p className="text-rose-300 font-semibold mb-2">Failed to load data</p>
        <p className="text-rose-200 text-sm font-mono break-all">{message}</p>
        {onRetry && (
          <button
            onClick={onRetry}
            className="mt-4 px-4 py-2 bg-rose-900 hover:bg-rose-800 border border-rose-700 text-rose-200 text-sm rounded-lg transition-colors"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
