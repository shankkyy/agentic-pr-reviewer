import type { ReviewJobView, StageRecord } from "@/lib/types";
import { STAGE_ORDER } from "@/lib/types";
import { Alert, Card, JobBadge, StageDot, formatTime } from "./ui";

const LABELS: Record<string, string> = {
  input_preparation: "Input preparation",
  deterministic_analysis: "Deterministic analysis (Ruff, Bandit, AST)",
  correctness_review: "Correctness review",
  security_review: "Security review",
  deduplication: "Deduplication",
  verification: "Verification",
  report_assembly: "Report assembly",
};

export default function ProgressPanel({ job, error }: { job: ReviewJobView | null; error: string | null }) {
  if (!job) {
    return (
      <Card title="Review progress">
        {error ? <Alert tone="error">{error}</Alert> : <p className="animate-fade-in text-sm text-neutral-500">Loading review…</p>}
      </Card>
    );
  }
  const byStage = new Map<string, StageRecord>(job.stages.map((s) => [s.stage, s]));
  const running = job.status === "queued" || job.status === "running";

  return (
    <Card
      title="Review progress"
      actions={
        <div className="flex items-center gap-2">
          <JobBadge status={job.status} />
          {job.mock_mode && (
            <span className="rounded-full border border-dashed border-black px-2.5 py-0.5 text-xs font-medium text-black">
              mock mode
            </span>
          )}
        </div>
      }
    >
      <dl className="mb-5 grid grid-cols-1 gap-x-8 gap-y-2 text-xs text-neutral-600 sm:grid-cols-2">
        <div className="flex gap-2">
          <dt className="font-medium text-black">Review ID</dt>
          <dd className="font-mono">{job.review_id}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="font-medium text-black">Source</dt>
          <dd className="truncate">{job.source_name}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="font-medium text-black">Created</dt>
          <dd>{formatTime(job.created_at)}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="font-medium text-black">Current stage</dt>
          <dd>{running ? job.current_stage ?? "waiting for a worker" : "—"}</dd>
        </div>
      </dl>

      <ol className="space-y-2">
        {STAGE_ORDER.map((name, i) => {
          const record = byStage.get(name);
          const status = record?.status ?? (running && job.current_stage === name ? "running" : "pending");
          const isCurrent = status === "running";
          return (
            <li
              key={name}
              style={{ animationDelay: `${i * 40}ms` }}
              className={`animate-fade-up flex flex-wrap items-start gap-3 rounded-xl border px-4 py-3 transition-all duration-500 ease-out ${
                isCurrent ? "border-black" : "border-black/10"
              }`}
            >
              <div className="mt-1.5">
                <StageDot status={status} />
              </div>
              <div className="min-w-0 flex-1">
                <p className={`text-sm font-medium transition-colors duration-300 ${status === "pending" ? "text-neutral-400" : "text-black"}`}>
                  {LABELS[name] ?? name}
                </p>
                {record && (
                  <p className="text-xs text-neutral-500">
                    {record.status} · {record.duration_ms.toFixed(0)} ms{record.detail ? ` · ${record.detail}` : ""}
                    {record.error ? ` · error: ${record.error}` : ""}
                  </p>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {job.error && (
        <div className="mt-5">
          <Alert tone="error">
            {job.error.message} <span className="font-mono text-xs">({job.error.code})</span>
          </Alert>
        </div>
      )}
      {error && (
        <div className="mt-5">
          <Alert tone="error">{error}</Alert>
        </div>
      )}
    </Card>
  );
}
