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
        <p className="text-sm text-neutral-500">Select a finding to see its evidence, remediation, and verification.</p>
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
      <div className="space-y-6 text-sm">
        <div>
          <h3 className="text-base font-semibold tracking-tight text-black">{finding.title}</h3>
          <p className="mt-1.5 font-mono text-xs text-neutral-600">
            {finding.file_path} · {lineRange}
          </p>
          <p className="mt-2 text-xs text-neutral-500">
            Category: {finding.category} · Confidence: {Math.round(finding.confidence * 100)}% · Source:{" "}
            {SOURCE_TEXT[finding.source_type] ?? finding.source_type}
          </p>
        </div>

        {finding.code_excerpt && (
          <Section title="Changed code (from the diff)">
            <pre className="overflow-x-auto rounded-xl bg-black p-4 font-mono text-xs leading-relaxed text-white">
              {finding.code_excerpt}
            </pre>
          </Section>
        )}

        <Section title="Explanation">
          <p className="whitespace-pre-wrap text-neutral-800">{finding.explanation || "No explanation provided."}</p>
        </Section>

        <Section title="Evidence">
          {finding.evidence.length === 0 ? (
            <p className="text-neutral-500">No evidence recorded.</p>
          ) : (
            <ul className="list-inside list-disc space-y-1 font-mono text-xs text-neutral-800">
              {finding.evidence.map((item, i) => (
                <li key={i} className="break-words">
                  {item}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Suggested remediation">
          <p className="whitespace-pre-wrap text-neutral-800">{finding.suggested_fix || "No remediation proposed."}</p>
        </Section>

        <Section title="Rule references">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs text-neutral-800">
            <dt className="font-medium text-black">Tool</dt>
            <dd>{finding.tool ?? "—"}</dd>
            <dt className="font-medium text-black">Rule ID</dt>
            <dd className="font-mono">{finding.rule_id ?? "— (model finding)"}</dd>
            <dt className="font-medium text-black">Reviewers / tools</dt>
            <dd>{finding.reviewers.join(", ") || "—"}</dd>
            <dt className="font-medium text-black">Merged duplicates</dt>
            <dd className="font-mono break-words">{finding.related_rules.join(", ") || "none"}</dd>
          </dl>
        </Section>

        <Section title="Verification">
          <p className="text-neutral-800">
            <span className="font-medium text-black">{finding.verification_status.replace("_", " ")}</span>
            {finding.verification_reason ? ` — ${finding.verification_reason}` : ""}
          </p>
        </Section>

        {finding.suggested_test && (
          <Section title="Suggested regression test">
            <div className="mb-3 inline-flex rounded-full border border-dashed border-black px-2.5 py-0.5 text-[11px] font-semibold tracking-wider text-black">
              SUGGESTED — NOT EXECUTED
            </div>
            <pre className="overflow-x-auto rounded-xl bg-black p-4 font-mono text-xs leading-relaxed text-white">
              {finding.suggested_test}
            </pre>
            {finding.suggested_test_behavior && (
              <p className="mt-2.5 text-xs text-neutral-600">
                <span className="font-medium text-black">Expected behavior:</span> {finding.suggested_test_behavior}
              </p>
            )}
          </Section>
        )}
        {!finding.suggested_test && finding.test_status === "error" && (
          <Section title="Suggested regression test">
            <p className="text-xs text-neutral-500">The test engineer could not produce a valid suggestion for this finding.</p>
          </Section>
        )}
      </div>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div>
      <h4 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-neutral-500">{title}</h4>
      {children}
    </div>
  );
}
