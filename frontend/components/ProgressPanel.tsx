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
        {error ? <Alert tone="error">{error}</Alert> : <p className="text-sm text-slate-500">Loading review…</p>}
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
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950 dark:text-amber-200">
              mock mode
            </span>
          )}
        </div>
      }
    >
      <dl className="mb-4 grid grid-cols-1 gap-x-6 gap-y-1 text-xs text-slate-600 sm:grid-cols-2 dark:text-slate-300">
        <div className="flex gap-2">
          <dt className="font-medium">Review ID</dt>
          <dd className="font-mono">{job.review_id}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="font-medium">Source</dt>
          <dd className="truncate">{job.source_name}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="font-medium">Created</dt>
          <dd>{formatTime(job.created_at)}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="font-medium">Current stage</dt>
          <dd>{running ? job.current_stage ?? "waiting for a worker" : "—"}</dd>
        </div>
      </dl>

      <ol className="space-y-2">
        {STAGE_ORDER.map((name) => {
          const record = byStage.get(name);
          const status = record?.status ?? (running && job.current_stage === name ? "running" : "pending");
          return (
            <li key={name} className="flex flex-wrap items-start gap-3 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
              <StageDot status={status} />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-800 dark:text-slate-100">{LABELS[name] ?? name}</p>
                {record && (
                  <p className="text-xs text-slate-500 dark:text-slate-400">
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
        <div className="mt-4">
          <Alert tone="error">
            {job.error.message} <span className="font-mono text-xs">({job.error.code})</span>
          </Alert>
        </div>
      )}
      {error && (
        <div className="mt-4">
          <Alert tone="error">{error}</Alert>
        </div>
      )}
    </Card>
  );
}
