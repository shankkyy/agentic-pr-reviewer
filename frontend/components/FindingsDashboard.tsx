"use client";

import { useMemo, useState } from "react";
import type { Category, Finding, ReviewReport, VerificationStatus } from "@/lib/types";
import { Card, SEVERITY_RANK, SeverityBadge, VerificationBadge } from "./ui";

type SortKey = "severity" | "file" | "line" | "confidence" | "verification" | "title";

interface Props {
  findings: Finding[];
  report: ReviewReport;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

const CATEGORIES: ("all" | Category)[] = ["all", "correctness", "security", "performance", "testing"];
const VERIFICATIONS: ("all" | VerificationStatus)[] = ["all", "verified", "needs_review", "inconclusive", "rejected"];
const SOURCE_LABEL: Record<string, string> = {
  static_analysis: "Static analysis",
  ast_check: "AST check",
  llm_hypothesis: "LLM hypothesis",
};

const selectClass =
  "rounded-lg border border-black/15 bg-white px-3 py-1.5 text-sm text-black transition-all duration-200 focus:border-black focus:outline-none focus:ring-4 focus:ring-black/5";

export default function FindingsDashboard({ findings, report, selectedId, onSelect }: Props) {
  const [category, setCategory] = useState<"all" | Category>("all");
  const [verification, setVerification] = useState<"all" | VerificationStatus>("all");
  const [sortKey, setSortKey] = useState<SortKey>("severity");
  const [descending, setDescending] = useState(true);
  const [showRejected, setShowRejected] = useState(false);

  const visible = useMemo(() => {
    const filtered = findings.filter(
      (f) =>
        (category === "all" || f.category === category) &&
        (verification === "all" || f.verification_status === verification) &&
        (showRejected || f.verification_status !== "rejected" || verification === "rejected"),
    );
    const key = (f: Finding): number | string => {
      switch (sortKey) {
        case "severity":
          return SEVERITY_RANK[f.severity];
        case "file":
          return f.file_path;
        case "line":
          return f.start_line ?? 0;
        case "confidence":
          return f.confidence;
        case "verification":
          return f.verification_status;
        case "title":
          return f.title.toLowerCase();
      }
    };
    const sorted = [...filtered].sort((a, b) => {
      const ka = key(a);
      const kb = key(b);
      const cmp =
        typeof ka === "number" && typeof kb === "number"
          ? ka - kb
          : String(ka).localeCompare(String(kb));
      return descending ? -cmp : cmp;
    });
    return sorted;
  }, [findings, category, verification, sortKey, descending, showRejected]);

  const rejectedCount = findings.filter((f) => f.verification_status === "rejected").length;

  function sortBy(key: SortKey) {
    if (sortKey === key) setDescending((d) => !d);
    else {
      setSortKey(key);
      setDescending(key === "severity" || key === "confidence");
    }
  }

  const header = (key: SortKey, label: string) => (
    <th scope="col" className="px-3 py-2.5 text-left">
      <button
        onClick={() => sortBy(key)}
        className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-neutral-500 transition-colors duration-200 hover:text-black"
        aria-label={`Sort by ${label}`}
      >
        {label}
        <span aria-hidden="true" className="inline-block w-3 text-center transition-transform duration-300">
          {sortKey === key ? (descending ? "▼" : "▲") : "↕"}
        </span>
      </button>
    </th>
  );

  return (
    <div className="space-y-6">
      <Card title="Summary">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Total findings" value={report.counts.total_findings} />
          <Stat label="Verified" value={report.counts.by_verification.verified ?? 0} />
          <Stat label="Needs review" value={report.counts.by_verification.needs_review ?? 0} />
          <Stat label="Rejected" value={report.counts.by_verification.rejected ?? 0} />
        </div>
        <div className="mt-5 flex flex-wrap gap-2 text-xs">
          {(["critical", "high", "medium", "low", "info"] as const).map((sev) => (
            <span key={sev} className="inline-flex items-center gap-2 rounded-full border border-black/10 py-1 pl-1 pr-3">
              <SeverityBadge severity={sev} />
              <span className="font-semibold text-black">{report.counts.by_severity[sev] ?? 0}</span>
            </span>
          ))}
          <span className="ml-auto self-center text-neutral-500">
            {report.counts.duplicates_merged} duplicate(s) merged · {report.counts.tests_suggested} test suggestion(s)
          </span>
        </div>
      </Card>

      <Card title={`Findings (${visible.length} shown)`}>
        <div className="mb-5 flex flex-wrap items-end gap-4 text-xs">
          <label className="flex flex-col gap-1.5">
            <span className="font-medium text-neutral-500">Category</span>
            <select value={category} onChange={(e) => setCategory(e.target.value as "all" | Category)} className={selectClass}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="font-medium text-neutral-500">Verification</span>
            <select
              value={verification}
              onChange={(e) => setVerification(e.target.value as "all" | VerificationStatus)}
              className={selectClass}
            >
              {VERIFICATIONS.map((v) => (
                <option key={v} value={v}>
                  {v.replace("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex cursor-pointer items-center gap-2 pb-2 text-black">
            <input
              type="checkbox"
              checked={showRejected}
              onChange={(e) => setShowRejected(e.target.checked)}
              className="h-4 w-4 accent-black"
            />
            Show rejected ({rejectedCount})
          </label>
        </div>

        {visible.length === 0 ? (
          <p className="animate-fade-in py-8 text-center text-sm text-neutral-500">
            {findings.length === 0
              ? "No findings. The analyzed changes produced no reportable issues."
              : "No findings match the current filters."}
          </p>
        ) : (
          <div className="-mx-5 overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="border-y border-black/10">
                <tr>
                  {header("severity", "Severity")}
                  {header("title", "Title")}
                  {header("file", "File")}
                  {header("line", "Line")}
                  {header("confidence", "Confidence")}
                  {header("verification", "Verification")}
                  <th scope="col" className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-neutral-500">
                    Source
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((f, i) => (
                  <tr
                    key={f.id}
                    onClick={() => onSelect(f.id)}
                    style={{ animationDelay: `${Math.min(i, 15) * 30}ms` }}
                    className={`animate-fade-up cursor-pointer border-b border-black/5 transition-colors duration-200 last:border-0 hover:bg-neutral-50 ${
                      selectedId === f.id ? "bg-neutral-100 shadow-[inset_2px_0_0_#000]" : ""
                    }`}
                  >
                    <td className="px-3 py-3">
                      <SeverityBadge severity={f.severity} />
                    </td>
                    <td className="max-w-xs px-3 py-3 font-medium text-black">
                      <button
                        className="text-left underline-offset-4 transition-all hover:underline"
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelect(f.id);
                        }}
                      >
                        {f.title}
                      </button>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-neutral-600">{f.file_path}</td>
                    <td className="px-3 py-3 font-mono text-xs">{f.start_line ?? "—"}</td>
                    <td className="px-3 py-3 text-xs tabular-nums">{Math.round(f.confidence * 100)}%</td>
                    <td className="px-3 py-3">
                      <VerificationBadge status={f.verification_status} />
                    </td>
                    <td className="px-3 py-3 text-xs text-neutral-600">
                      {SOURCE_LABEL[f.source_type] ?? f.source_type}
                      {f.rule_id ? <span className="ml-1 font-mono text-neutral-400">{f.rule_id}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-black/10 px-4 py-3.5 transition-colors duration-300 hover:border-black">
      <p className="text-xs font-medium text-neutral-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-black">{value}</p>
    </div>
  );
}
