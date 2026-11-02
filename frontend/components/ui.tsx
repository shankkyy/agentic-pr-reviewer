import type { ReactNode } from "react";
import type { JobStatus, Severity, StageStatus, VerificationStatus } from "@/lib/types";

// Monochrome: status is shown through fill, outline, dash and weight rather than hue.
const SEVERITY_STYLES: Record<Severity, string> = {
  critical: "border-black bg-black text-white",
  high: "border-black text-black font-semibold",
  medium: "border-black/60 text-black",
  low: "border-black/30 text-neutral-600",
  info: "border-transparent bg-neutral-100 text-neutral-500",
};

export const SEVERITY_RANK: Record<Severity, number> = {
  critical: 5,
  high: 4,
  medium: 3,
  low: 2,
  info: 1,
};

const VERIFICATION_STYLES: Record<VerificationStatus, string> = {
  verified: "border-black bg-black text-white",
  rejected: "border-dashed border-black/30 text-neutral-400 line-through",
  needs_review: "border-black text-black",
  inconclusive: "border-black/20 text-neutral-500",
};

const JOB_STYLES: Record<JobStatus, string> = {
  queued: "border-black/20 text-neutral-500",
  running: "border-black text-black",
  completed: "border-black bg-black text-white",
  partial: "border-black text-black",
  failed: "border-2 border-black font-semibold text-black",
  cancelled: "border-dashed border-black/30 text-neutral-500",
};

const pill =
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap transition-all duration-300 ease-out";

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`${pill} ${SEVERITY_STYLES[severity]}`}>{severity}</span>;
}

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  return <span className={`${pill} ${VERIFICATION_STYLES[status]}`}>{status.replace("_", " ")}</span>;
}

export function JobBadge({ status }: { status: JobStatus }) {
  return (
    <span className={`${pill} ${JOB_STYLES[status]}`}>
      {status === "running" && <span className="h-1.5 w-1.5 animate-pulse-line rounded-full bg-black" aria-hidden="true" />}
      {status}
    </span>
  );
}

export function StageDot({ status }: { status: StageStatus | "pending" }) {
  const color: Record<string, string> = {
    pending: "border border-black/20 bg-white",
    running: "bg-black animate-pulse-line",
    completed: "bg-black",
    failed: "border-2 border-black bg-white",
    skipped: "bg-black/20",
  };
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full transition-colors duration-500 ${color[status] ?? color.pending}`}
      aria-hidden="true"
    />
  );
}

export function Card({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="animate-fade-up rounded-2xl border border-black/10 bg-white">
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-black/10 px-5 py-3.5">
          {title && <h2 className="text-sm font-semibold tracking-tight text-black">{title}</h2>}
          {actions}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Alert({ tone, children }: { tone: "error" | "warning" | "info"; children: ReactNode }) {
  const styles = {
    error: "border-black bg-black text-white",
    warning: "border-dashed border-black/40 bg-neutral-50 text-black",
    info: "border-black/10 bg-neutral-50 text-black",
  };
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`animate-fade-in rounded-xl border px-4 py-2.5 text-sm ${styles[tone]}`}
    >
      {children}
    </div>
  );
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}
