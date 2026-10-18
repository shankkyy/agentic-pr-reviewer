// Types mirror the backend Pydantic models (backend/app/schemas). Keep them in sync.

export type Category = "correctness" | "security" | "performance" | "testing";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type SourceType = "static_analysis" | "ast_check" | "llm_hypothesis";
export type VerificationStatus = "verified" | "rejected" | "needs_review" | "inconclusive";
export type TestStatus =
  | "not_generated"
  | "suggested_not_executed"
  | "passed"
  | "failed"
  | "error"
  | "timeout";
export type JobStatus = "queued" | "running" | "completed" | "partial" | "failed" | "cancelled";
export type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export const STAGE_ORDER = [
  "input_preparation",
  "deterministic_analysis",
  "correctness_review",
  "security_review",
  "deduplication",
  "verification",
  "report_assembly",
] as const;

export interface Finding {
  id: string;
  rule_id: string | null;
  tool: string | null;
  category: Category;
  severity: Severity;
  title: string;
  file_path: string;
  start_line: number | null;
  end_line: number | null;
  explanation: string;
  evidence: string[];
  suggested_fix: string;
  confidence: number;
  source_type: SourceType;
  reviewers: string[];
  related_rules: string[];
  code_excerpt: string | null;
  verification_status: VerificationStatus;
  verification_reason: string;
  test_status: TestStatus;
  suggested_test: string | null;
  suggested_test_behavior: string | null;
}

export interface ErrorInfo {
  code: string;
  message: string;
  stage?: string | null;
}

export interface StageRecord {
  stage: string;
  status: StageStatus;
  duration_ms: number;
  detail: string;
  error: string | null;
}

export interface SummaryCounts {
  total_findings: number;
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
  by_verification: Record<string, number>;
  by_source: Record<string, number>;
  duplicates_merged: number;
  tests_suggested: number;
}

export interface ReviewJobView {
  review_id: string;
  status: JobStatus;
  source_name: string;
  mock_mode: boolean;
  created_at: string;
  updated_at: string;
  current_stage: string | null;
  stages: StageRecord[];
  counts: SummaryCounts | null;
  error: ErrorInfo | null;
}

export interface ReviewListItem {
  review_id: string;
  status: JobStatus;
  source_name: string;
  mock_mode: boolean;
  created_at: string;
  completed_at: string | null;
  total_findings: number;
  by_severity: Record<string, number>;
}

export interface ReviewerRun {
  reviewer: string;
  status: string;
  attempts: number;
  llm_calls: number;
  findings_proposed: number;
  duration_ms: number;
  error_code: string | null;
  error_message: string | null;
  omitted_files: string[];
}

export interface ToolRunRecord {
  tool: string;
  status: string;
  duration_ms: number;
  diagnostics: number;
  message: string;
}

export interface UsageSummary {
  provider: string;
  model: string;
  mock_mode: boolean;
  llm_calls: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: number | null;
  cost_note: string;
}

export interface FileSummary {
  path: string;
  status: string;
  hunks: number;
  added_lines: number;
  deleted_lines: number;
  analyzed: boolean;
  reason: string;
}

export interface ReviewReport {
  review_id: string;
  status: JobStatus;
  source_name: string;
  created_at: string;
  completed_at: string | null;
  duration_ms: number | null;
  input_sha256: string;
  size_bytes: number;
  mock_mode: boolean;
  provider: string;
  model: string;
  counts: SummaryCounts;
  findings: Finding[];
  stages: StageRecord[];
  reviewers: ReviewerRun[];
  tools: ToolRunRecord[];
  usage: UsageSummary;
  files: FileSummary[];
  limitations: string[];
  warnings: string[];
  error: ErrorInfo | null;
}

export interface CreateReviewResponse {
  review_id: string;
  status: JobStatus;
  status_url: string;
  report_url: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  mock_mode: boolean;
  llm_provider: string;
  llm_model: string;
  static_tools_enabled: string[];
}
