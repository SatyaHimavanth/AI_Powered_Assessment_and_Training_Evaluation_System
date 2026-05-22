import { useEffect, useState } from "react";
import api from "../../api";

type Template = {
  id: string;
  title: string;
  role: string;
  experience_level: string;
  difficulty: string;
  duration_minutes: number;
  question_count: number;
  focus_areas: string[];
  default_questions_or_topics: string[];
  max_pauses_allowed: number;
  is_archived: boolean;
};

type RequestItem = {
  id: string;
  template_id: string;
  template_title: string;
  status: string;
  request_type: string;
  requested_at: string;
};

type SessionItem = {
  id: string;
  template_id: string;
  template_title: string;
  status: string;
  attempt_number: number;
  pause_count: number;
  max_pauses_allowed: number;
  started_at: string | null;
  completed_at: string | null;
  total_score: number | null;
};

type EvaluationItem = {
  turn_index: number;
  user_response: string | null;
  score: number | null;
  focus_area: string | null;
  strengths: string[];
  improvements: string[];
  feedback: string | null;
};

type TopicScore = {
  topic: string;
  avg_score: number;
  turns: number;
};

type SessionResultFull = {
  id: string;
  template_id: string;
  template_title: string;
  status: string;
  attempt_number: number;
  started_at: string | null;
  completed_at: string | null;
  pause_count: number;
  disconnect_count: number;
  total_score: number | null;
  summary: string | null;
  transcript: { role: string; content: string; timestamp: string }[];
  feedback: Record<string, any> | null;
  evaluations: EvaluationItem[];
  topic_scores: TopicScore[];
};

const card = "bg-white rounded-[var(--radius)] shadow-[var(--shadow)] border border-[var(--color-border)]";

interface InterviewsProps {
  onStartInterview?: (templateId: string) => void;
  onResumeInterview?: (sessionId: string) => void;
}

export default function Interviews({ onStartInterview, onResumeInterview }: InterviewsProps) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [requests, setRequests] = useState<RequestItem[]>([]);
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [resultsModal, setResultsModal] = useState<SessionResultFull | null>(null);

  useEffect(() => {
    reload();
  }, []);

  async function reload() {
    try {
      const [tRes, rRes, sRes] = await Promise.all([
        api.get("/interviews/templates"),
        api.get("/interviews/my-requests"),
        api.get("/interviews/my-sessions"),
      ]);
      setTemplates(Array.isArray(tRes.data) ? tRes.data : []);
      setRequests(Array.isArray(rRes.data) ? rRes.data : []);
      setSessions(Array.isArray(sRes.data) ? sRes.data : []);
    } catch {
      // ignore
    }
  }

  async function requestAccess(templateId: string) {
    setLoadingId(templateId);
    setMessage("");
    try {
      const res = await api.post("/interviews/request-access", { template_id: templateId });
      setMessage(res.data?.message || "Request submitted");
      reload();
    } catch (err: any) {
      setMessage(err?.response?.data?.detail || "Failed to submit request");
    } finally {
      setLoadingId(null);
    }
  }

  async function requestRetry(templateId: string) {
    setLoadingId(`retry-${templateId}`);
    setMessage("");
    try {
      const res = await api.post("/interviews/request-retry", { template_id: templateId });
      setMessage(res.data?.message || "Retry request submitted");
      reload();
    } catch (err: any) {
      setMessage(err?.response?.data?.detail || "Failed to submit retry request");
    } finally {
      setLoadingId(null);
    }
  }

  function handleStart(templateId: string) {
    setMessage("");
    if (onStartInterview) {
      onStartInterview(templateId);
    }
  }

  function allTurnsEvaluated(templateId: string): boolean {
    // Check if the completed/missed session for this template has a score (meaning evaluation is done)
    const session = sessions.find(
      (s) => s.template_id === templateId && (s.status === "completed" || s.status === "missed")
    );
    return session ? session.total_score !== null : true;
  }

  function handleResume(sessionId: string) {
    if (onResumeInterview) {
      onResumeInterview(sessionId);
    }
  }

  async function openResults(sessionId: string) {
    setLoadingId(`results-${sessionId}`);
    try {
      const res = await api.get(`/interviews/${sessionId}/results`);
      setResultsModal(res.data);
    } catch (err: any) {
      setMessage(err?.response?.data?.detail || "Failed to load results");
    } finally {
      setLoadingId(null);
    }
  }

  const approvedTemplateIds = new Set(
    requests.filter((r) => r.status === "approved").map((r) => r.template_id)
  );
  const pendingTemplateIds = new Set(
    requests.filter((r) => r.status === "pending").map((r) => r.template_id)
  );
  // Check if there's an approved retry request for a template
  const approvedRetryTemplateIds = new Set(
    requests.filter((r) => r.status === "approved" && r.request_type === "retry").map((r) => r.template_id)
  );

  return (
    <div className="space-y-6">
      {message && (
        <div className={`${card} p-4 text-sm`}>{message}</div>
      )}

      {/* Available Interview Templates */}
      <div className={`${card} overflow-hidden`}>
        <div className="px-5 py-4 border-b border-[var(--color-border)]">
          <h3 className="text-sm font-semibold">Available Interview Templates</h3>
          <p className="text-xs text-[var(--color-text-secondary)] mt-1">Request access to available templates</p>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] bg-gray-50/50">
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Title</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Role</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Level</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Difficulty</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Duration</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Questions</th>
              <th className="text-right px-5 py-3 font-medium text-[var(--color-text-secondary)]">Action</th>
            </tr>
          </thead>
          <tbody>
            {templates.map((t) => {
              const hasApproved = approvedTemplateIds.has(t.id);
              const hasPending = pendingTemplateIds.has(t.id);
              const hasMissedOrCompleted = sessions.some(
                (s) => s.template_id === t.id && (s.status === "missed" || s.status === "completed")
              );

              return (
                <tr key={t.id} className="border-b border-[var(--color-border)] last:border-0">
                  <td className="px-5 py-3.5 font-medium">{t.title}</td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.role}</td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.experience_level}</td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.difficulty}</td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.duration_minutes} min</td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.question_count}</td>
                  <td className="px-5 py-3.5 text-right space-x-2">
                    {!hasApproved && !hasPending && (
                      <button
                        onClick={() => requestAccess(t.id)}
                        disabled={loadingId === t.id}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-blue-50 text-[var(--color-primary)] hover:bg-blue-100 cursor-pointer transition-colors disabled:opacity-50"
                      >
                        Request Access
                      </button>
                    )}
                    {hasPending && (
                      <span className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-amber-50 text-amber-700">
                        Pending Approval
                      </span>
                    )}
                    {hasApproved && !hasMissedOrCompleted && (
                      <button
                        onClick={() => handleStart(t.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-green-50 text-green-700 hover:bg-green-100 cursor-pointer transition-colors"
                      >
                        Start Interview
                      </button>
                    )}
                    {hasMissedOrCompleted && approvedRetryTemplateIds.has(t.id) && (
                      <button
                        onClick={() => handleStart(t.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-green-50 text-green-700 hover:bg-green-100 cursor-pointer transition-colors"
                      >
                        Start Interview
                      </button>
                    )}
                    {hasMissedOrCompleted && !approvedRetryTemplateIds.has(t.id) && !pendingTemplateIds.has(t.id) && (
                      <button
                        onClick={() => requestRetry(t.id)}
                        disabled={loadingId === `retry-${t.id}` || !allTurnsEvaluated(t.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-gray-100 text-[var(--color-text)] hover:bg-gray-200 cursor-pointer transition-colors disabled:opacity-50"
                        title={!allTurnsEvaluated(t.id) ? "Wait for evaluation to complete" : ""}
                      >
                        Request Retry
                      </button>
                    )}
                    {hasMissedOrCompleted && !approvedRetryTemplateIds.has(t.id) && pendingTemplateIds.has(t.id) && (
                      <span className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-amber-50 text-amber-700">
                        Retry Pending
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
            {templates.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-8 text-center text-[var(--color-text-secondary)]">No active interview templates available.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* My Interview Sessions */}
      <div className={`${card} overflow-hidden`}>
        <div className="px-5 py-4 border-b border-[var(--color-border)]">
          <h3 className="text-sm font-semibold">My Interview Sessions</h3>
          <p className="text-xs text-[var(--color-text-secondary)] mt-1">Your interview sessions and results</p>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] bg-gray-50/50">
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Template</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Status</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Attempt</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Pauses</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Score</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Started</th>
              <th className="text-right px-5 py-3 font-medium text-[var(--color-text-secondary)]">Action</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => {
              const statusLabel = s.status.replace(/_/g, " ");
              return (
                <tr key={s.id} className="border-b border-[var(--color-border)] last:border-0">
                  <td className="px-5 py-3.5 font-medium">{s.template_title}</td>
                  <td className="px-5 py-3.5">
                    <span className={`inline-flex items-center h-6 px-2 text-xs font-medium rounded-full ${
                      s.status === "completed" ? "bg-green-50 text-green-700" :
                      s.status === "missed" ? "bg-red-50 text-red-700" :
                      s.status === "in_progress" || s.status === "started" ? "bg-blue-50 text-blue-700" :
                      s.status === "paused" ? "bg-amber-50 text-amber-700" :
                      "bg-gray-100 text-gray-700"
                    }`}>
                      {statusLabel}
                    </span>
                  </td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{s.attempt_number}</td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{s.pause_count}/{s.max_pauses_allowed}</td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">
                    {s.total_score != null ? `${s.total_score}%` : "-"}
                  </td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)] text-xs">
                    {s.started_at ? new Date(s.started_at).toLocaleString() : "-"}
                  </td>
                  <td className="px-5 py-3.5 text-right">
                    {s.status === "started" && (
                      <button
                        onClick={() => handleStart(s.template_id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-green-50 text-green-700 hover:bg-green-100 cursor-pointer transition-colors"
                      >
                        Start
                      </button>
                    )}
                    {(s.status === "in_progress" || s.status === "paused") && (
                      <button
                        onClick={() => handleResume(s.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-blue-50 text-blue-700 hover:bg-blue-100 cursor-pointer transition-colors"
                      >
                        Resume
                      </button>
                    )}
                    {s.status === "completed" && (
                      <button
                        onClick={() => openResults(s.id)}
                        disabled={loadingId === `results-${s.id}`}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-purple-50 text-purple-700 hover:bg-purple-100 cursor-pointer transition-colors disabled:opacity-50"
                      >
                        {loadingId === `results-${s.id}` ? "Loading..." : "View Results"}
                      </button>
                    )}
                    {s.status === "missed" && (
                      <span className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-red-50 text-red-700">
                        Missed
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
            {sessions.length === 0 && (
              <tr>
                <td colSpan={7} className="px-5 py-8 text-center text-[var(--color-text-secondary)]">No interview sessions yet. Request access to a template to get started.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Results Modal */}
      {resultsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white rounded-xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold">Interview Results</h2>
                <p className="text-sm text-gray-600">{resultsModal.template_title}</p>
              </div>
              <button
                onClick={() => setResultsModal(null)}
                className="h-8 w-8 flex items-center justify-center rounded-full hover:bg-gray-100 transition-colors"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="flex-1 overflow-auto p-6 space-y-6">
              {/* Summary Stats */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <div className="bg-blue-50 rounded-lg p-3 text-center">
                  <div className="text-xs uppercase tracking-wide text-blue-900 font-semibold mb-1">Overall Score</div>
                  <div className="text-2xl font-bold text-blue-900">
                    {resultsModal.total_score != null ? `${resultsModal.total_score}%` : "N/A"}
                  </div>
                </div>
                <div className="bg-green-50 rounded-lg p-3 text-center">
                  <div className="text-xs uppercase tracking-wide text-green-900 font-semibold mb-1">Status</div>
                  <div className="text-lg font-bold text-green-900 capitalize">{resultsModal.status.replace(/_/g, " ")}</div>
                </div>
                <div className="bg-purple-50 rounded-lg p-3 text-center">
                  <div className="text-xs uppercase tracking-wide text-purple-900 font-semibold mb-1">Attempt</div>
                  <div className="text-2xl font-bold text-purple-900">{resultsModal.attempt_number}</div>
                </div>
                <div className="bg-orange-50 rounded-lg p-3 text-center">
                  <div className="text-xs uppercase tracking-wide text-orange-900 font-semibold mb-1">Pauses</div>
                  <div className="text-2xl font-bold text-orange-900">{resultsModal.pause_count}</div>
                </div>
              </div>

              {/* Topic-wise Scoring */}
              {resultsModal.topic_scores && resultsModal.topic_scores.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold mb-3">Topic-wise Scores</h3>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {resultsModal.topic_scores.map((ts) => (
                      <div key={ts.topic} className="border border-gray-200 rounded-lg p-3">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-medium capitalize">{ts.topic}</span>
                          <span className={`text-sm font-bold ${ts.avg_score >= 7 ? "text-green-700" : ts.avg_score >= 4 ? "text-amber-700" : "text-red-700"}`}>
                            {ts.avg_score}/10
                          </span>
                        </div>
                        <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${ts.avg_score >= 7 ? "bg-green-500" : ts.avg_score >= 4 ? "bg-amber-500" : "bg-red-500"}`}
                            style={{ width: `${(ts.avg_score / 10) * 100}%` }}
                          />
                        </div>
                        <div className="text-xs text-gray-500 mt-1">{ts.turns} question(s)</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Per-Turn Evaluations */}
              {resultsModal.evaluations && resultsModal.evaluations.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold mb-3">Detailed Evaluation</h3>
                  <div className="space-y-4">
                    {resultsModal.evaluations.map((ev) => (
                      <div key={ev.turn_index} className="border border-gray-200 rounded-lg p-4">
                        <div className="flex items-center justify-between mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-gray-500 uppercase">Turn {ev.turn_index}</span>
                            {ev.focus_area && (
                              <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-700 rounded-full">{ev.focus_area}</span>
                            )}
                          </div>
                          <span className={`text-sm font-bold ${
                            (ev.score ?? 0) >= 7 ? "text-green-700" : (ev.score ?? 0) >= 4 ? "text-amber-700" : "text-red-700"
                          }`}>
                            {ev.score != null ? `${ev.score}/10` : "N/A"}
                          </span>
                        </div>

                        {ev.user_response && (
                          <div className="mb-2">
                            <div className="text-xs font-medium text-gray-500 mb-1">Your Response:</div>
                            <p className="text-sm text-gray-700 bg-gray-50 rounded p-2">{ev.user_response}</p>
                          </div>
                        )}

                        {ev.strengths && ev.strengths.length > 0 && (
                          <div className="mb-2">
                            <div className="text-xs font-medium text-green-700 mb-1">Strengths:</div>
                            <ul className="list-disc list-inside text-sm text-gray-700 space-y-0.5">
                              {ev.strengths.map((s, i) => <li key={i}>{s}</li>)}
                            </ul>
                          </div>
                        )}

                        {ev.improvements && ev.improvements.length > 0 && (
                          <div className="mb-2">
                            <div className="text-xs font-medium text-amber-700 mb-1">Areas for Improvement:</div>
                            <ul className="list-disc list-inside text-sm text-gray-700 space-y-0.5">
                              {ev.improvements.map((s, i) => <li key={i}>{s}</li>)}
                            </ul>
                          </div>
                        )}

                        {ev.feedback && (
                          <div>
                            <div className="text-xs font-medium text-blue-700 mb-1">Feedback:</div>
                            <p className="text-sm text-gray-700">{ev.feedback}</p>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {resultsModal.summary && (
                <div>
                  <h3 className="text-sm font-semibold mb-2">Summary</h3>
                  <p className="text-sm text-gray-700 bg-gray-50 rounded-lg p-4">{resultsModal.summary}</p>
                </div>
              )}
            </div>

            <div className="px-6 py-4 border-t border-gray-200 flex justify-end">
              <button
                onClick={() => setResultsModal(null)}
                className="h-9 px-4 text-sm font-medium rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
