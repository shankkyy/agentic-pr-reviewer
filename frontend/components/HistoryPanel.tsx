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
        <button onClick={onRefresh} className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400">
          Refresh
        </button>
      }
    >
      {error && <Alert tone="error">{error}</Alert>}
      {!error && items === null && <p className="text-sm text-slate-500">Loading history…</p>}
      {items && items.length === 0 && <p className="text-sm text-slate-500 dark:text-slate-400">No reviews yet. Start one from New review.</p>}
      {items && items.length > 0 && (
        <div className="-mx-4 overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead className="bg-slate-50 dark:bg-slate-800/50">
              <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">
                <th className="px-3 py-2">Created</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Findings</th>
                <th className="px-3 py-2">By severity</th>
                <th className="px-3 py-2"><span className="sr-only">Open</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {items.map((item) => (
                <tr key={item.review_id}>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-600 dark:text-slate-300">{formatTime(item.created_at)}</td>
                  <td className="px-3 py-2 font-mono text-xs">{item.source_name}</td>
                  <td className="px-3 py-2">
                    <JobBadge status={item.status} />
                    {item.mock_mode && <span className="ml-1 text-[10px] uppercase text-amber-700 dark:text-amber-300">mock</span>}
                  </td>
                  <td className="px-3 py-2 font-semibold">{item.total_findings}</td>
                  <td className="px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
                    {Object.entries(item.by_severity)
                      .map(([sev, n]) => `${sev}: ${n}`)
                      .join(" · ") || "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => onOpen(item.review_id)} className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400">
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
