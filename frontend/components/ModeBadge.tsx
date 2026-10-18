import type { HealthResponse } from "@/lib/types";

export default function ModeBadge({ health, error }: { health: HealthResponse | null; error: string | null }) {
  if (error) {
    return (
      <span className="rounded-full bg-red-100 px-2.5 py-1 text-xs font-medium text-red-800 dark:bg-red-950 dark:text-red-200">
        Backend offline
      </span>
    );
  }
  if (!health) {
    return <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300">Checking backend…</span>;
  }
  if (health.mock_mode) {
    return (
      <span
        title="The deterministic mock provider is active. No external AI API is called and model findings are pattern-based."
        className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-900 dark:bg-amber-950 dark:text-amber-200"
      >
        MOCK MODE · no API calls
      </span>
    );
  }
  return (
    <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
      Live · {health.llm_provider} / {health.llm_model}
    </span>
  );
}
