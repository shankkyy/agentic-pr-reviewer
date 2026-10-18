import type { ReactNode } from "react";
import type { Finding } from "@/lib/types";
import { Card, SeverityBadge, VerificationBadge } from "./ui";

const SOURCE_TEXT: Record<string, string> = {
  static_analysis: "Static analysis tool output (pattern match on a changed line)",
  ast_check: "Focused AST check (deterministic pattern on a changed line)",
  llm_hypothesis: "LLM hypothesis (requires corroboration to be verified)",
};

export default function FindingDetail({ finding }: { finding: Finding | null }) {
  if (!finding) {
    return (
      <Card title="Finding details">
        <p className="text-sm text-slate-500 dark:text-slate-400">Select a finding to see its evidence, remediation, and verification.</p>
      </Card>
    );
  }
  const lineRange =
    finding.start_line === null
      ? "no line reference"
      : finding.end_line && finding.end_line !== finding.start_line
        ? `lines ${finding.start_line}–${finding.end_line}`
        : `line ${finding.start_line}`;

  return (
    <Card
      title="Finding details"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={finding.severity} />
          <VerificationBadge status={finding.verification_status} />
        </div>
      }
    >
      <div className="space-y-5 text-sm">
        <div>
          <h3 className="text-base font-semibold text-slate-900 dark:text-white">{finding.title}</h3>
          <p className="mt-1 font-mono text-xs text-slate-600 dark:text-slate-300">
            {finding.file_path} · {lineRange}
          </p>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            Category: {finding.category} · Confidence: {Math.round(finding.confidence * 100)}% · Source:{" "}
            {SOURCE_TEXT[finding.source_type] ?? finding.source_type}
          </p>
        </div>

        {finding.code_excerpt && (
          <Section title="Changed code (from the diff)">
            <pre className="overflow-x-auto rounded-lg bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-100">
              {finding.code_excerpt}
            </pre>
          </Section>
        )}

        <Section title="Explanation">
          <p className="whitespace-pre-wrap text-slate-700 dark:text-slate-200">{finding.explanation || "No explanation provided."}</p>
        </Section>

        <Section title="Evidence">
          {finding.evidence.length === 0 ? (
            <p className="text-slate-500 dark:text-slate-400">No evidence recorded.</p>
          ) : (
            <ul className="list-inside list-disc space-y-1 font-mono text-xs text-slate-700 dark:text-slate-200">
              {finding.evidence.map((item, i) => (
                <li key={i} className="break-words">
                  {item}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Suggested remediation">
          <p className="whitespace-pre-wrap text-slate-700 dark:text-slate-200">{finding.suggested_fix || "No remediation proposed."}</p>
        </Section>

        <Section title="Rule references">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs text-slate-700 dark:text-slate-200">
            <dt className="font-medium">Tool</dt>
            <dd>{finding.tool ?? "—"}</dd>
            <dt className="font-medium">Rule ID</dt>
            <dd className="font-mono">{finding.rule_id ?? "— (model finding)"}</dd>
            <dt className="font-medium">Reviewers / tools</dt>
            <dd>{finding.reviewers.join(", ") || "—"}</dd>
            <dt className="font-medium">Merged duplicates</dt>
            <dd className="font-mono break-words">{finding.related_rules.join(", ") || "none"}</dd>
          </dl>
        </Section>

        <Section title="Verification">
          <p className="text-slate-700 dark:text-slate-200">
            <span className="font-medium">{finding.verification_status.replace("_", " ")}</span>
            {finding.verification_reason ? ` — ${finding.verification_reason}` : ""}
          </p>
        </Section>

        {finding.suggested_test && (
          <Section title="Suggested regression test">
            <div className="mb-2 inline-flex rounded-md bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-900 dark:bg-amber-950 dark:text-amber-200">
              SUGGESTED — NOT EXECUTED
            </div>
            <pre className="overflow-x-auto rounded-lg bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-100">
              {finding.suggested_test}
            </pre>
            {finding.suggested_test_behavior && (
              <p className="mt-2 text-xs text-slate-600 dark:text-slate-300">
                <span className="font-medium">Expected behavior:</span> {finding.suggested_test_behavior}
              </p>
            )}
          </Section>
        )}
        {!finding.suggested_test && finding.test_status === "error" && (
          <Section title="Suggested regression test">
            <p className="text-xs text-slate-500 dark:text-slate-400">The test engineer could not produce a valid suggestion for this finding.</p>
          </Section>
        )}
      </div>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">{title}</h4>
      {children}
    </div>
  );
}
