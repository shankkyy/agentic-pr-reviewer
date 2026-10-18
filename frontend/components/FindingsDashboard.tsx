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
    <th scope="col" className="px-3 py-2 text-left">
      <button
        onClick={() => sortBy(key)}
        className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white"
        aria-label={`Sort by ${label}`}
      >
        {label}
        <span aria-hidden="true">{sortKey === key ? (descending ? "▼" : "▲") : "↕"}</span>
      </button>
    </th>
  );

  return (
    <div className="space-y-4">
      <Card title="Summary">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Total findings" value={report.counts.total_findings} />
          <Stat label="Verified" value={report.counts.by_verification.verified ?? 0} />
          <Stat label="Needs review" value={report.counts.by_verification.needs_review ?? 0} />
          <Stat label="Rejected" value={report.counts.by_verification.rejected ?? 0} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2 text-xs">
          {(["critical", "high", "medium", "low", "info"] as const).map((sev) => (
            <span key={sev} className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-2.5 py-1 dark:border-slate-700">
              <SeverityBadge severity={sev} />
              <span className="font-semibold text-slate-800 dark:text-slate-100">{report.counts.by_severity[sev] ?? 0}</span>
            </span>
          ))}
          <span className="ml-auto self-center text-slate-500 dark:text-slate-400">
            {report.counts.duplicates_merged} duplicate(s) merged · {report.counts.tests_suggested} test suggestion(s)
          </span>
        </div>
      </Card>

      <Card title={`Findings (${visible.length} shown)`}>
        <div className="mb-4 flex flex-wrap items-end gap-3 text-xs">
          <label className="flex flex-col gap-1">
            <span className="font-medium text-slate-600 dark:text-slate-300">Category</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as "all" | Category)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="font-medium text-slate-600 dark:text-slate-300">Verification</span>
            <select
              value={verification}
              onChange={(e) => setVerification(e.target.value as "all" | VerificationStatus)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-950"
            >
              {VERIFICATIONS.map((v) => (
                <option key={v} value={v}>
                  {v.replace("_", " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 pb-1.5 text-slate-700 dark:text-slate-200">
            <input
              type="checkbox"
              checked={showRejected}
              onChange={(e) => setShowRejected(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            Show rejected ({rejectedCount})
          </label>
        </div>

        {visible.length === 0 ? (
          <p className="py-6 text-center text-sm text-slate-500 dark:text-slate-400">
            {findings.length === 0
              ? "No findings. The analyzed changes produced no reportable issues."
              : "No findings match the current filters."}
          </p>
        ) : (
          <div className="-mx-4 overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
              <thead className="bg-slate-50 dark:bg-slate-800/50">
                <tr>
                  {header("severity", "Severity")}
                  {header("title", "Title")}
                  {header("file", "File")}
                  {header("line", "Line")}
                  {header("confidence", "Confidence")}
                  {header("verification", "Verification")}
                  <th scope="col" className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">
                    Source
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {visible.map((f) => (
                  <tr
                    key={f.id}
                    onClick={() => onSelect(f.id)}
                    className={`cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/60 ${
                      selectedId === f.id ? "bg-blue-50 dark:bg-blue-950/40" : ""
                    }`}
                  >
                    <td className="px-3 py-2">
                      <SeverityBadge severity={f.severity} />
                    </td>
                    <td className="max-w-xs px-3 py-2 font-medium text-slate-800 dark:text-slate-100">
                      <button className="text-left hover:underline" onClick={(e) => { e.stopPropagation(); onSelect(f.id); }}>
                        {f.title}
                      </button>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-slate-600 dark:text-slate-300">{f.file_path}</td>
                    <td className="px-3 py-2 font-mono text-xs">{f.start_line ?? "—"}</td>
                    <td className="px-3 py-2 text-xs">{Math.round(f.confidence * 100)}%</td>
                    <td className="px-3 py-2">
                      <VerificationBadge status={f.verification_status} />
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
                      {SOURCE_LABEL[f.source_type] ?? f.source_type}
                      {f.rule_id ? <span className="ml-1 font-mono text-slate-500">{f.rule_id}</span> : null}
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
    <div className="rounded-lg bg-slate-50 px-4 py-3 dark:bg-slate-800/60">
      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900 dark:text-white">{value}</p>
    </div>
  );
}
