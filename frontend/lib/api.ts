import type {
  CreateReviewResponse,
  HealthResponse,
  ReviewJobView,
  ReviewListItem,
  ReviewReport,
} from "./types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export const MAX_UPLOAD_BYTES = 1024 * 1024;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    throw new ApiError(0, "network_error", `Cannot reach the backend at ${API_BASE_URL}. Is it running?`);
  }
  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed with status ${response.status}.`;
    try {
      const body = (await response.json()) as { error?: { code?: string; message?: string } };
      if (body?.error?.code) code = body.error.code;
      if (body?.error?.message) message = body.error.message;
    } catch {
      // Non-JSON error bodies are not shown to the user.
    }
    throw new ApiError(response.status, code, message);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<HealthResponse>("/health"),

  createPasteReview: (diffText: string, name?: string) =>
    request<CreateReviewResponse>("/api/reviews", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ diff_text: diffText, name: name ?? null }),
    }),

  createUploadReview: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<CreateReviewResponse>("/api/reviews", { method: "POST", body: form });
  },

  getReview: (reviewId: string) => request<ReviewJobView>(`/api/reviews/${encodeURIComponent(reviewId)}`),

  getReport: (reviewId: string) => request<ReviewReport>(`/api/reviews/${encodeURIComponent(reviewId)}/report`),

  listReviews: (limit = 50) => request<ReviewListItem[]>(`/api/reviews?limit=${limit}`),

  cancelReview: (reviewId: string) =>
    request<ReviewJobView>(`/api/reviews/${encodeURIComponent(reviewId)}/cancel`, { method: "POST" }),
};

/** Client-side hints only. The backend performs authoritative validation. */
export function quickValidateDiff(text: string): string | null {
  if (!text.trim()) return "The diff is empty.";
  if (new TextEncoder().encode(text).length > MAX_UPLOAD_BYTES) return "The diff is larger than 1 MB.";
  if (!/^(diff --git |--- |@@ )/m.test(text)) return "This does not look like a unified diff (no file or hunk headers found).";
  return null;
}
