import type { HealthResponse } from "@/lib/types";

const base = "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-all duration-300 ease-out";

export default function ModeBadge({ health, error }: { health: HealthResponse | null; error: string | null }) {
  if (error) {
    return (
      <span className={`${base} border-2 border-black font-semibold text-black`}>
        <span className="h-1.5 w-1.5 rounded-full border border-black" aria-hidden="true" />
        Backend offline
      </span>
    );
  }
  if (!health) {
    return (
      <span className={`${base} border-black/20 text-neutral-500`}>
        <span className="h-1.5 w-1.5 animate-pulse-line rounded-full bg-neutral-400" aria-hidden="true" />
        Checking backend…
      </span>
    );
  }
  if (health.mock_mode) {
    return (
      <span
        title="The deterministic mock provider is active. No external AI API is called and model findings are pattern-based."
        className={`${base} border-dashed border-black font-medium text-black`}
      >
        Mock mode · no API calls
      </span>
    );
  }
  return (
    <span className={`${base} border-black bg-black font-medium text-white`}>
      <span className="h-1.5 w-1.5 rounded-full bg-white" aria-hidden="true" />
      Live · {health.llm_provider} / {health.llm_model}
    </span>
  );
}
