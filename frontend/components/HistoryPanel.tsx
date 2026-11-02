import type { ReviewListItem } from "@/lib/types";
import { Alert, Card, JobBadge, formatTime } from "./ui";

interface Props {
  items: ReviewListItem[] | null;
  error: string | null;
  onOpen: (reviewId: string) => void;
  onRefresh: () => void;
}

export default function HistoryPanel({ items, error, onOpen, onRefresh }: Props) {
  return (
    <Card
      title="Review history"
      actions={
        <button
          onClick={onRefresh}
          className="rounded-full border border-black/20 px-3 py-1 text-xs font-medium text-black transition-all duration-200 hover:border-black hover:bg-black hover:text-white active:scale-[0.97]"
        >
          Refresh
        </button>
      }
    >
      {error && <Alert tone="error">{error}</Alert>}
      {!error && items === null && <p className="animate-fade-in text-sm text-neutral-500">Loading history…</p>}
      {items && items.length === 0 && (
        <p className="animate-fade-in text-sm text-neutral-500">No reviews yet. Start one from New review.</p>
      )}
      {items && items.length > 0 && (
        <div className="-mx-5 overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="border-y border-black/10">
              <tr className="text-left text-xs font-semibold uppercase tracking-wider text-neutral-500">
                <th className="px-3 py-2.5">Created</th>
                <th className="px-3 py-2.5">Source</th>
                <th className="px-3 py-2.5">Status</th>
                <th className="px-3 py-2.5">Findings</th>
                <th className="px-3 py-2.5">By severity</th>
                <th className="px-3 py-2.5">
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, i) => (
                <tr
                  key={item.review_id}
                  style={{ animationDelay: `${Math.min(i, 15) * 30}ms` }}
                  className="animate-fade-up border-b border-black/5 transition-colors duration-200 last:border-0 hover:bg-neutral-50"
                >
                  <td className="whitespace-nowrap px-3 py-3 text-xs text-neutral-600">{formatTime(item.created_at)}</td>
                  <td className="px-3 py-3 font-mono text-xs">{item.source_name}</td>
                  <td className="px-3 py-3">
                    <JobBadge status={item.status} />
                    {item.mock_mode && <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider text-neutral-500">mock</span>}
                  </td>
                  <td className="px-3 py-3 font-semibold tabular-nums">{item.total_findings}</td>
                  <td className="px-3 py-3 text-xs text-neutral-600">
                    {Object.entries(item.by_severity)
                      .map(([sev, n]) => `${sev}: ${n}`)
                      .join(" · ") || "—"}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <button
                      onClick={() => onOpen(item.review_id)}
                      className="rounded-full px-3 py-1 text-xs font-medium text-black underline-offset-4 transition-all duration-200 hover:bg-black hover:text-white"
                    >
                      Open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
