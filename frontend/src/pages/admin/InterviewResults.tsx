import { useEffect, useState } from "react";
import api from "../../api";

interface InterviewResult {
  id: string;
  template_id: string;
  template_title: string;
  user_id: string;
  user_name: string;
  username: string;
  status: string;
  attempt_number: number;
  pause_count: number;
  max_pauses_allowed: number;
  started_at: string | null;
  completed_at: string | null;
  total_score: number | null;
}

interface Template {
  id: string;
  title: string;
}

interface SessionDetail {
  id: string;
  template_title: string;
  status: string;
  total_score: number | null;
  summary: string | null;
  transcript: { role: string; content: string; timestamp: string }[];
  evaluations: { turn_index: number; user_response: string; score: number | null; focus_area: string; strengths: string[]; improvements: string[]; feedback: string }[];
  topic_scores: { topic: string; avg_score: number; turns: number }[];
}

const STATUS_OPTIONS = [
  { value: "", label: "All Statuses" },
  { value: "assigned", label: "Assigned (Yet to attend)" },
  { value: "started", label: "Started" },
  { value: "in_progress", label: "In Progress" },
  { value: "paused", label: "Paused" },
  { value: "completed", label: "Completed" },
  { value: "abandoned", label: "Abandoned" },
  { value: "missed", label: "Missed" },
];

type SortField = "user_name" | "username" | "score" | "status" | "started_at";
type SortDir = "asc" | "desc";

const PAGE_SIZE_OPTIONS = [10, 20, 50];

const card = "bg-white rounded-[var(--radius-md)] border border-[var(--color-border)] shadow-[var(--shadow-sm)]";
const inputClass = "w-full border border-[var(--color-border)] rounded-[var(--radius-sm)] px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]";
const selectClass = "w-full border border-[var(--color-border)] rounded-[var(--radius-sm)] px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--color-primary)]/20 focus:border-[var(--color-primary)]";

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    assigned: "bg-purple-50 text-purple-700 border-purple-200",
    completed: "bg-green-50 text-green-700 border-green-200",
    started: "bg-blue-50 text-blue-700 border-blue-200",
    in_progress: "bg-yellow-50 text-yellow-700 border-yellow-200",
    paused: "bg-orange-50 text-orange-700 border-orange-200",
    abandoned: "bg-red-50 text-red-700 border-red-200",
    missed: "bg-gray-50 text-gray-700 border-gray-200",
  };
  return (
    <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full border ${colors[status] || "bg-gray-50 text-gray-700 border-gray-200"}`}>
      {status.replace("_", " ")}
    </span>
  );
}

export default function InterviewResults({ setMessage }: { setMessage: (m: string) => void }) {
  const [results, setResults] = useState<InterviewResult[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(false);
  const [viewDetail, setViewDetail] = useState<SessionDetail | null>(null);

  // Filters
  const [filterTemplate, setFilterTemplate] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");

  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // Sorting
  const [sortField, setSortField] = useState<SortField | "">("")
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  useEffect(() => {
    loadTemplates();
  }, []);

  useEffect(() => {
    setPage(1);
    loadResults(1);
  }, [filterTemplate, filterStatus, filterDateFrom, filterDateTo]);

  async function loadTemplates() {
    try {
      const res = await api.get("/admin/interviews/templates");
      setTemplates(Array.isArray(res.data) ? res.data : []);
    } catch { /* ignore */ }
  }

  async function loadResults(pg?: number, ps?: number) {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterTemplate) params.set("template_id", filterTemplate);
      if (filterStatus) params.set("status", filterStatus);
      if (filterDateFrom) params.set("date_from", filterDateFrom);
      if (filterDateTo) params.set("date_to", filterDateTo);
      params.set("page", String(pg ?? page));
      params.set("page_size", String(ps ?? pageSize));
      const res = await api.get(`/admin/interviews/results?${params.toString()}`);
      const data = res.data;
      if (data && typeof data === "object" && "items" in data) {
        setResults(Array.isArray(data.items) ? data.items : []);
        setTotalCount(data.total_count ?? 0);
      } else {
        setResults(Array.isArray(data) ? data : []);
        setTotalCount(Array.isArray(data) ? data.length : 0);
      }
    } catch {
      setMessage("Failed to load interview results");
    } finally {
      setLoading(false);
    }
  }

  async function viewResultDetail(sessionId: string) {
    try {
      const res = await api.get(`/admin/interviews/results/${sessionId}`);
      setViewDetail(res.data);
    } catch {
      setMessage("Failed to load session details");
    }
  }

  function formatDate(d: string | null) {
    if (!d) return "—";
    return new Date(d).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  function clearFilters() {
    setFilterTemplate("");
    setFilterStatus("");
    setFilterDateFrom("");
    setFilterDateTo("");
  }

  const hasFilters = filterTemplate || filterStatus || filterDateFrom || filterDateTo;

  // Sorting
  function toggleSort(field: SortField) {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("asc");
    }
    setPage(1);
  }

  const sortedResults = [...results].sort((a, b) => {
    if (!sortField) return 0;
    const dir = sortDir === "asc" ? 1 : -1;
    if (sortField === "user_name") return (a.user_name || "").localeCompare(b.user_name || "") * dir;
    if (sortField === "username") return (a.username || "").localeCompare(b.username || "") * dir;
    if (sortField === "score") return ((a.total_score ?? -1) - (b.total_score ?? -1)) * dir;
    if (sortField === "status") return (a.status || "").localeCompare(b.status || "") * dir;
    if (sortField === "started_at") return ((a.started_at || "").localeCompare(b.started_at || "")) * dir;
    return 0;
  });

  // Pagination computed values
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const paginatedResults = sortedResults;

  function sortIcon(field: SortField) {
    if (sortField !== field) return "↕";
    return sortDir === "asc" ? "↑" : "↓";
  }

  // Detail modal
  if (viewDetail) {
    return (
      <div className="space-y-6">
        <button
          onClick={() => setViewDetail(null)}
          className="text-sm text-[var(--color-primary)] hover:underline cursor-pointer flex items-center gap-1"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back to Results
        </button>

        <div className={`${card} p-5`}>
          <h3 className="text-sm font-semibold mb-2">{viewDetail.template_title}</h3>
          <div className="flex gap-4 text-xs text-[var(--color-text-secondary)] mb-4">
            <span>Status: {statusBadge(viewDetail.status)}</span>
            <span>Score: <strong className="text-[var(--color-text)]">{viewDetail.total_score != null ? viewDetail.total_score.toFixed(1) : "—"}</strong></span>
          </div>
          {viewDetail.summary && (
            <div className="bg-gray-50 rounded-[var(--radius-sm)] p-3 text-xs text-[var(--color-text)] mb-4">
              <strong className="block mb-1">Summary</strong>
              {viewDetail.summary}
            </div>
          )}
        </div>

        {/* Topic Scores */}
        {viewDetail.topic_scores.length > 0 && (
          <div className={`${card} p-5`}>
            <h4 className="text-sm font-semibold mb-3">Topic Scores</h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {viewDetail.topic_scores.map((ts) => (
                <div key={ts.topic} className="bg-gray-50 rounded-[var(--radius-sm)] p-3">
                  <div className="text-xs font-medium capitalize">{ts.topic}</div>
                  <div className="text-lg font-bold text-[var(--color-primary)]">{ts.avg_score.toFixed(1)}</div>
                  <div className="text-xs text-[var(--color-text-secondary)]">{ts.turns} turn(s)</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Per-turn Evaluations */}
        {viewDetail.evaluations.length > 0 && (
          <div className={`${card} p-5`}>
            <h4 className="text-sm font-semibold mb-3">Turn-by-Turn Evaluation</h4>
            <div className="space-y-4">
              {viewDetail.evaluations.map((ev) => (
                <div key={ev.turn_index} className="border border-[var(--color-border)] rounded-[var(--radius-sm)] p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium">Turn {ev.turn_index + 1}{ev.focus_area ? ` — ${ev.focus_area}` : ""}</span>
                    <span className="text-xs font-bold text-[var(--color-primary)]">{ev.score != null ? `${ev.score}/10` : "—"}</span>
                  </div>
                  {ev.user_response && (
                    <div className="text-xs text-[var(--color-text-secondary)] mb-2 bg-blue-50 rounded p-2">
                      <strong>Response:</strong> {ev.user_response}
                    </div>
                  )}
                  {ev.strengths.length > 0 && (
                    <div className="text-xs mb-1">
                      <strong className="text-green-700">Strengths:</strong>{" "}
                      {ev.strengths.join(", ")}
                    </div>
                  )}
                  {ev.improvements.length > 0 && (
                    <div className="text-xs mb-1">
                      <strong className="text-orange-700">Improvements:</strong>{" "}
                      {ev.improvements.join(", ")}
                    </div>
                  )}
                  {ev.feedback && (
                    <div className="text-xs text-[var(--color-text-secondary)] mt-1">{ev.feedback}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Transcript */}
        {viewDetail.transcript && viewDetail.transcript.length > 0 && (
          <div className={`${card} p-5`}>
            <h4 className="text-sm font-semibold mb-3">Transcript</h4>
            <div className="space-y-2 max-h-96 overflow-auto">
              {viewDetail.transcript.map((msg, i) => (
                <div key={i} className={`text-xs p-2 rounded ${msg.role === "user" ? "bg-blue-50 ml-8" : "bg-gray-50 mr-8"}`}>
                  <strong className="capitalize">{msg.role}:</strong> {msg.content}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className={`${card} p-5`}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold">Filters</h3>
          {hasFilters && (
            <button
              onClick={clearFilters}
              className="text-xs text-[var(--color-primary)] hover:underline cursor-pointer"
            >
              Clear all filters
            </button>
          )}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Template</label>
            <select className={selectClass} value={filterTemplate} onChange={(e) => setFilterTemplate(e.target.value)}>
              <option value="">All Templates</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Status</label>
            <select className={selectClass} value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}>
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">From Date</label>
            <input type="date" className={inputClass} value={filterDateFrom} onChange={(e) => setFilterDateFrom(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">To Date</label>
            <input type="date" className={inputClass} value={filterDateTo} onChange={(e) => setFilterDateTo(e.target.value)} />
          </div>
        </div>
      </div>

      {/* Results Table */}
      <div className={`${card} overflow-hidden`}>
        <div className="px-5 py-4 border-b border-[var(--color-border)] flex items-center justify-between">
          <h3 className="text-sm font-semibold">Interview Results ({results.length})</h3>
          <div className="flex items-center gap-3">
            {loading && <span className="text-xs text-[var(--color-text-secondary)]">Loading...</span>}
            <label className="flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)]">
              Show
              <select
                className="border border-[var(--color-border)] rounded px-1.5 py-1 text-xs bg-white"
                value={pageSize}
                onChange={(e) => { const ps = Number(e.target.value); setPageSize(ps); setPage(1); loadResults(1, ps); }}
              >
                {PAGE_SIZE_OPTIONS.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
              per page
            </label>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-50 border-b border-[var(--color-border)]">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-[var(--color-text-secondary)] cursor-pointer select-none hover:text-[var(--color-text)]" onClick={() => toggleSort("user_name")}>User {sortIcon("user_name")}</th>
                <th className="text-left px-4 py-3 font-medium text-[var(--color-text-secondary)]">Template</th>
                <th className="text-left px-4 py-3 font-medium text-[var(--color-text-secondary)] cursor-pointer select-none hover:text-[var(--color-text)]" onClick={() => toggleSort("status")}>Status {sortIcon("status")}</th>
                <th className="text-center px-4 py-3 font-medium text-[var(--color-text-secondary)]">Attempt</th>
                <th className="text-center px-4 py-3 font-medium text-[var(--color-text-secondary)] cursor-pointer select-none hover:text-[var(--color-text)]" onClick={() => toggleSort("score")}>Score {sortIcon("score")}</th>
                <th className="text-center px-4 py-3 font-medium text-[var(--color-text-secondary)]">Pauses</th>
                <th className="text-left px-4 py-3 font-medium text-[var(--color-text-secondary)] cursor-pointer select-none hover:text-[var(--color-text)]" onClick={() => toggleSort("started_at")}>Started {sortIcon("started_at")}</th>
                <th className="text-left px-4 py-3 font-medium text-[var(--color-text-secondary)]">Completed</th>
                <th className="text-center px-4 py-3 font-medium text-[var(--color-text-secondary)]">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {paginatedResults.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50/50">
                  <td className="px-4 py-3">
                    <div className="font-medium text-[var(--color-text)]">{r.user_name}</div>
                    <div className="text-[var(--color-text-secondary)]">{r.username}</div>
                  </td>
                  <td className="px-4 py-3 text-[var(--color-text)]">{r.template_title}</td>
                  <td className="px-4 py-3">{statusBadge(r.status)}</td>
                  <td className="px-4 py-3 text-center">{r.attempt_number}</td>
                  <td className="px-4 py-3 text-center font-medium">
                    {r.total_score != null ? `${r.total_score.toFixed(1)}` : "—"}
                  </td>
                  <td className="px-4 py-3 text-center">{r.pause_count}/{r.max_pauses_allowed}</td>
                  <td className="px-4 py-3 text-[var(--color-text-secondary)]">{formatDate(r.started_at)}</td>
                  <td className="px-4 py-3 text-[var(--color-text-secondary)]">{formatDate(r.completed_at)}</td>
                  <td className="px-4 py-3 text-center">
                    {r.status !== "assigned" ? (
                      <button
                        onClick={() => viewResultDetail(r.id)}
                        className="text-xs text-[var(--color-primary)] hover:underline cursor-pointer font-medium"
                      >
                        View
                      </button>
                    ) : (
                      <span className="text-xs text-[var(--color-text-secondary)]">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {results.length === 0 && !loading && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-[var(--color-text-secondary)]">
                    No interview results found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalCount > 0 && (
          <div className="px-5 py-3 border-t border-[var(--color-border)] flex items-center justify-between">
            <span className="text-xs text-[var(--color-text-secondary)]">
              Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, totalCount)} of {totalCount}
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => { const p = Math.max(1, page - 1); setPage(p); loadResults(p); }}
                disabled={page === 1}
                className="px-2.5 py-1.5 text-xs rounded border border-[var(--color-border)] disabled:opacity-40 hover:bg-gray-50 cursor-pointer disabled:cursor-default"
              >
                ← Prev
              </button>
              {totalPages > 1 && Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                let pageNum: number;
                if (totalPages <= 5) {
                  pageNum = i + 1;
                } else if (page <= 3) {
                  pageNum = i + 1;
                } else if (page >= totalPages - 2) {
                  pageNum = totalPages - 4 + i;
                } else {
                  pageNum = page - 2 + i;
                }
                return (
                  <button
                    key={pageNum}
                    onClick={() => { setPage(pageNum); loadResults(pageNum); }}
                    className={`px-2.5 py-1.5 text-xs rounded border cursor-pointer ${
                      page === pageNum
                        ? "bg-[var(--color-primary)] text-white border-[var(--color-primary)]"
                        : "border-[var(--color-border)] hover:bg-gray-50"
                    }`}
                  >
                    {pageNum}
                  </button>
                );
              })}
              <button
                onClick={() => { const p = Math.min(totalPages, page + 1); setPage(p); loadResults(p); }}
                disabled={page === totalPages}
                className="px-2.5 py-1.5 text-xs rounded border border-[var(--color-border)] disabled:opacity-40 hover:bg-gray-50 cursor-pointer disabled:cursor-default"
              >
                Next →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
