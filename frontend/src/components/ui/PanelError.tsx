import React from "react";
import { formatPanelErrorMessage } from "@/lib/api-errors";

interface PanelErrorProps {
  /** An ApiError, Error, string, or anything thrown by an API call. */
  error: unknown;
}

/** Shared error banner for the Assistant and Semantic Search panels. */
export function PanelError({ error }: PanelErrorProps) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className="bg-red-950/60 border border-red-800 text-red-300 text-xs p-3 rounded-lg"
    >
      {formatPanelErrorMessage(error)}
    </div>
  );
}
