"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ModeBadge from "@/components/ModeBadge";
import UploadPanel from "@/components/UploadPanel";
import ProgressPanel from "@/components/ProgressPanel";
import FindingsDashboard from "@/components/FindingsDashboard";
import FindingDetail from "@/components/FindingDetail";
import HistoryPanel from "@/components/HistoryPanel";
import { Alert, Card, JobBadge, formatTime } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type {
  CreateReviewResponse,
  HealthResponse,
  ReviewJobView,
  ReviewListItem,
  ReviewReport,
} from "@/lib/types";

type View = "new" | "history" | "review";
const TERMINAL = new Set(["completed", "partial", "failed", "cancelled"]);
const POLL_INTERVAL_MS = 1200;

function messageOf(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  return "An unexpected error occurred in the dashboard.";
}

export default function Home() {
  const [view, setView] = useState<View>("new");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [job, setJob] = useState<ReviewJobView | null>(null);
  const [report, setReport] = useState<ReviewReport | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [history, setHistory] = useState<ReviewListItem[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);

  // Health check: shows whether the backend is reachable and whether mock mode is active.
  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((err: unknown) => setHealthError(messageOf(err)));
  }, []);

  // Hash routing (#review=<id>) so a review can be reopened from its URL.
  const openReview = useCallback((id: string) => {
    window.location.hash = `review=${id}`;
  }, []);

  useEffect(() => {
    function sync() {
      const match = window.location.hash.match(/^#review=(rev_[A-Za-z0-9]+)$/);
      if (match) {
        setActiveId(match[1]);
        setJob(null);
        setReport(null);
        setSelectedId(null);
        setPollError(null);
        setView("review");
      }
    }
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  // Poll the status endpoint until the job is terminal, then load the full report.
  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function tick() {
      if (!activeId) return;
      try {
        const current = await api.getReview(activeId);
        if (cancelled) return;
        setJob(current);
        setPollError(null);
        if (TERMINAL.has(current.status)) {
          try {
            const full = await api.getReport(activeId);
            if (!cancelled) setReport(full);
          } catch (err: unknown) {
            if (!cancelled) setPollError(messageOf(err));
          }
          return;
        }
      } catch (err: unknown) {
        if (cancelled) return;
        setPollError(messageOf(err));
        if (err instanceof ApiError && err.status === 404) return;
      }
      if (!cancelled) timer = setTimeout(tick, POLL_INTERVAL_MS);
    }

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [activeId]);

  const loadHistory = useCallback(() => {
    setHistoryError(null);
    api
      .listReviews()
      .then(setHistory)
      .catch((err: unknown) => setHistoryError(messageOf(err)));
  }, []);

  useEffect(() => {
    if (view === "history") loadHistory();
  }, [view, loadHistory]);

  async function startReview(run: () => Promise<CreateReviewResponse>) {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const created = await run();
      setSelectedId(null);
      openReview(created.review_id);
    } catch (err: unknown) {
      setSubmitError(messageOf(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelActive() {
    if (!activeId) return;
    setCancelling(true);
    try {
      const updated = await api.cancelReview(activeId);
      setJob(updated);
    } catch (err: unknown) {
      setPollError(messageOf(err));
    } finally {
      setCancelling(false);
    }
  }

  const selectedFinding = useMemo(
    () => report?.findings.find((f) => f.id === selectedId) ?? null,
    [report, selectedId],
  );

  const navItem = (id: View, label: string, disabled = false) => (
    <button
      key={id}
      disabled={disabled}
      onClick={() => setView(id)}
      className={`w-full rounded-lg px-3 py-2 text-left text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        view === id
          ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900"
          : "text-slate-700 hover:bg-slate-200/70 dark:text-slate-300 dark:hover:bg-slate-800"
      }`}
    >
      {label}
    </button>
  );

  const isActive = job !== null && (job.status === "queued" || job.status === "running");

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <aside className="border-b border-slate-200 bg-white px-4 py-4 lg:w-60 lg:border-b-0 lg:border-r dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-4">
          <p className="text-sm font-semibold tracking-tight">Agentic PR Reviewer</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">Diff review with verified findings</p>
        </div>
        <nav className="flex gap-2 lg:flex-col" aria-label="Main">
          {navItem("new", "New review")}
          {navItem("history", "Review history")}
          {navItem("review", "Current review", !activeId)}
        </nav>
        <div className="mt-6 hidden text-xs text-slate-500 lg:block dark:text-slate-400">
          <p className="mb-2">
            <ModeBadge health={health} error={healthError} />
          </p>
          <p>Backend: {process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}</p>
        </div>
      </aside>

      <main className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-6xl space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h1 className="text-xl font-semibold tracking-tight">
              {view === "new" ? "New review" : view === "history" ? "Review history" : "Review"}
            </h1>
            <div className="lg:hidden">
              <ModeBadge health={health} error={healthError} />
            </div>
          </div>

          {healthError && (
            <Alert tone="error">
              The backend is not reachable ({healthError}). Start it with the commands in the README, then reload.
            </Alert>
          )}

          {view === "new" && (
            <UploadPanel
              submitting={submitting}
              submitError={submitError}
              onSubmitPaste={(diffText, name) =>
                startReview(() => api.createPasteReview(diffText, name))
              }
              onSubmitFile={(file) => startReview(() => api.createUploadReview(file))}
            />
          )}

          {view === "history" && (
            <HistoryPanel
              items={history}
              error={historyError}
              onOpen={openReview}
              onRefresh={loadHistory}
            />
          )}

          {view === "review" && (
            <>
              {!activeId && (
                <Card>
                  <p className="text-sm text-slate-500 dark:text-slate-400">No review is open. Start one or pick one from history.</p>
                </Card>
              )}
              {activeId && (
                <>
                  <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600 dark:text-slate-300">
                    {job && <JobBadge status={job.status} />}
                    <span className="font-mono">{activeId}</span>
                    {job && <span>Created {formatTime(job.created_at)}</span>}
                    {isActive && (
                      <button
                        onClick={cancelActive}
                        disabled={cancelling}
                        className="ml-auto rounded-md border border-slate-300 px-3 py-1 font-medium text-slate-700 hover:bg-white disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800"
                      >
                        {cancelling ? "Cancelling…" : "Cancel review"}
                      </button>
                    )}
                  </div>

                  {(!report || isActive) && (
                    <ProgressPanel job={job} error={pollError} />
                  )}

                  {report && (
                    <>
                      {report.error && <Alert tone="error">{report.error.message}</Alert>}
                      {report.warnings.length > 0 && (
                        <Alert tone="warning">
                          <ul className="list-inside list-disc space-y-0.5">
                            {report.warnings.map((w, i) => (
                              <li key={i}>{w}</li>
                            ))}
                          </ul>
                        </Alert>
                      )}
                      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                        <FindingsDashboard
                          findings={report.findings}
                          report={report}
                          selectedId={selectedId}
                          onSelect={setSelectedId}
                        />
                        <div className="xl:sticky xl:top-6 xl:self-start">
                          <FindingDetail finding={selectedFinding} />
                        </div>
                      </div>
                      <RunDetails report={report} />
                    </>
                  )}
                </>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function RunDetails({ report }: { report: ReviewReport }) {
  return (
    <Card title="Run details">
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-3 text-xs">
          <h3 className="font-semibold text-slate-700 dark:text-slate-200">Reviewers</h3>
          <ul className="space-y-1">
            {report.reviewers.map((r) => (
              <li key={r.reviewer} className="flex flex-wrap gap-x-2">
                <span className="font-medium">{r.reviewer}</span>
                <span>{r.status}</span>
                <span className="text-slate-500">
                  {r.findings_proposed} proposed · {r.llm_calls} call(s) · {r.duration_ms.toFixed(0)} ms
                </span>
                {r.error_code && <span className="font-mono text-red-700 dark:text-red-300">{r.error_code}</span>}
                {r.omitted_files.length > 0 && <span className="text-amber-700">{r.omitted_files.length} file(s) omitted</span>}
              </li>
            ))}
            {report.reviewers.length === 0 && <li className="text-slate-500">No reviewer ran for this diff.</li>}
          </ul>
          <h3 className="pt-2 font-semibold text-slate-700 dark:text-slate-200">Analysis tools</h3>
          <ul className="space-y-1">
            {report.tools.map((t) => (
              <li key={t.tool} className="flex flex-wrap gap-x-2">
                <span className="font-medium">{t.tool}</span>
                <span>{t.status}</span>
                <span className="text-slate-500">{t.diagnostics} diagnostic(s)</span>
                {t.message && <span className="text-slate-500">· {t.message}</span>}
              </li>
            ))}
          </ul>
        </div>
        <div className="space-y-3 text-xs">
          <h3 className="font-semibold text-slate-700 dark:text-slate-200">Usage and cost</h3>
          <p>
            {report.usage.provider} / {report.usage.model} · {report.usage.llm_calls} LLM call(s) · {report.usage.input_tokens} in /{" "}
            {report.usage.output_tokens} out tokens
          </p>
          <p className="text-slate-500">
            Estimated cost: {report.usage.estimated_cost_usd === null ? "not measured" : `$${report.usage.estimated_cost_usd.toFixed(6)}`}.{" "}
            {report.usage.cost_note}
          </p>
          <h3 className="pt-2 font-semibold text-slate-700 dark:text-slate-200">Files</h3>
          <ul className="max-h-56 space-y-1 overflow-y-auto">
            {report.files.map((f) => (
              <li key={f.path} className="flex flex-wrap gap-x-2">
                <span className="font-mono">{f.path}</span>
                <span className="text-slate-500">
                  {f.status} · +{f.added_lines} / −{f.deleted_lines} · {f.reason}
                </span>
              </li>
            ))}
          </ul>
          <h3 className="pt-2 font-semibold text-slate-700 dark:text-slate-200">Limitations</h3>
          <ul className="list-inside list-disc space-y-0.5 text-slate-600 dark:text-slate-300">
            {report.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  );
}
