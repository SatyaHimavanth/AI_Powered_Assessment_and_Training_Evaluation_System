import { useEffect, useState } from "react";
import api from "../../api";
import type { AssessmentListItem, BatchInfo } from "./types";
import { card, selectClass } from "./types";
import CircularProgress from "../../components/CircularProgress";

interface TopicPerformance {
  topic_name: string;
  total_questions: number;
  correct: number;
  percentage: number;
}

interface TopicScore {
  topic_name: string;
  percentage: number;
  correct: number;
  total: number;
}

interface UserAttemptResult {
  attempt_id: string | null;
  user_id: string;
  user_name: string;
  username: string;
  score: number | null;
  status: string;
  started_at: string | null;
  submitted_at: string | null;
  total_answered: number;
  evaluation_status: string | null;
  evaluation_job_id: string | null;
  evaluation_error: string | null;
  evaluation_error_category: string | null;
}

interface AssessmentResults {
  assessment_id: string;
  assessment_title: string;
  total_participants: number;
  completed_count: number;
  average_score: number | null;
  topic_performance: TopicPerformance[];
  user_results: UserAttemptResult[];
  total_user_results: number;
}

interface Props {
  batches: BatchInfo[];
}

interface AnswerReview {
  question_id: string;
  question_text: string;
  question_type: string;
  topic_name: string;
  your_answer: string;
  correct_answer: string;
  is_correct: boolean;
  score: number | null;
  suggestion?: string | null;
}

interface AttemptResults {
  assessment_title: string;
  status: string;
  score: number | null;
  evaluation_pending: boolean;
  total_questions: number;
  answered: number;
  correct_count: number;
  started_at: string | null;
  submitted_at: string | null;
  topic_scores: TopicScore[];
  answers: AnswerReview[];
}

export default function Results({ batches }: Props) {
  const [selectedBatch, setSelectedBatch] = useState("");
  const [assessments, setAssessments] = useState<AssessmentListItem[]>([]);
  const [selectedAssessment, setSelectedAssessment] = useState("");
  const [results, setResults] = useState<AssessmentResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [resettingAttemptId, setResettingAttemptId] = useState<string | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
  const [errorModalUser, setErrorModalUser] = useState<UserAttemptResult | null>(null);
  const [showTopicModal, setShowTopicModal] = useState(false);
  const [selectedUserTopics, setSelectedUserTopics] = useState<{ userName: string; topics: TopicScore[] } | null>(null);
  const [loadingTopics, setLoadingTopics] = useState(false);
  const [viewingAttempt, setViewingAttempt] = useState<string | null>(null);
  const [attemptResults, setAttemptResults] = useState<AttemptResults | null>(null);
  const [loadingAttemptResults, setLoadingAttemptResults] = useState(false);
  const [exportingAttemptId, setExportingAttemptId] = useState<string | null>(null);
  const [exportingAll, setExportingAll] = useState(false);

  // Status filter and sorting for individual results
  const [statusFilter, setStatusFilter] = useState("");
  const [sortField, setSortField] = useState<"name" | "username" | "score" | "status" | "">("");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  // Pagination
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  // Load all assessments on mount
  useEffect(() => {
    const load = async () => {
      try {
        const res = await api.get("/assessments/");
        const data = res.data;
        setAssessments(data.items ?? data);
      } catch {
        // ignore
      }
    };
    load();
  }, []);

  // Filter assessments by batch
  const filteredAssessments = selectedBatch
    ? assessments.filter((a) =>
        a.batch_names.some((bn) => {
          const batch = batches.find((b) => b.id === selectedBatch);
          return batch && bn === batch.name;
        })
      )
    : assessments;

  const selectedBatchName = selectedBatch
    ? batches.find((b) => b.id === selectedBatch)?.name || "Selected Batch"
    : "All Batches";
  const selectedAssessmentName = selectedAssessment
    ? assessments.find((a) => a.id === selectedAssessment)?.title || "Selected Assessment"
    : "";

  const downloadBlobResponse = (data: BlobPart, disposition: string | undefined, fallbackName: string) => {
    const blobUrl = window.URL.createObjectURL(new Blob([data]));
    const link = document.createElement("a");
    const filename = disposition?.split("filename=")[1]?.replace(/"/g, "")?.trim();
    link.href = blobUrl;
    link.download = filename || fallbackName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(blobUrl);
  };

  const loadResults = async (assessmentId: string, pg?: number, ps?: number, sf?: string) => {
    if (!assessmentId) {
      setResults(null);
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("page", String(pg ?? page));
      params.set("page_size", String(ps ?? pageSize));
      const currentStatusFilter = sf !== undefined ? sf : statusFilter;
      if (selectedBatch) params.set("batch_id", selectedBatch);
      if (currentStatusFilter) params.set("status_filter", currentStatusFilter);
      const res = await api.get(`/assessments/${assessmentId}/results?${params.toString()}`);
      setResults(res.data);
    } catch {
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  const handleAssessmentChange = (id: string) => {
    setSelectedAssessment(id);
    setPage(1);
    loadResults(id, 1);
  };

  const handleResetAttempt = async (attemptId: string | null, userName: string) => {
    if (!attemptId) return;
    if (!window.confirm(`Re-enable test for ${userName}? They will be able to retake this assessment.`)) {
      return;
    }

    setResettingAttemptId(attemptId);
    try {
      await api.post(`/admin/reset-attempt/${attemptId}`);
      // Reload results to refresh the table
      if (selectedAssessment) {
        await loadResults(selectedAssessment);
      }
    } catch (err: unknown) {
      console.error(err);
      alert("Failed to reset attempt");
    } finally {
      setResettingAttemptId(null);
    }
  };

  const handleRetryEvaluation = async (jobId: string) => {
    setRetryingJobId(jobId);
    try {
      await api.post(`/admin/evaluations/${jobId}/retry`);
      if (selectedAssessment) {
        await loadResults(selectedAssessment);
      }
    } catch (err: unknown) {
      console.error(err);
      alert("Failed to retry evaluation");
    } finally {
      setRetryingJobId(null);
    }
  };

  const handleViewTopics = async (attemptId: string, userName: string) => {
    setLoadingTopics(true);
    try {
      const res = await api.get(`/admin/attempt/${attemptId}/topics`);
      setSelectedUserTopics({
        userName,
        topics: res.data.topic_scores,
      });
      setShowTopicModal(true);
    } catch (err: unknown) {
      console.error(err);
      alert("Failed to load topic scores");
    } finally {
      setLoadingTopics(false);
    }
  };

  const handleViewAttemptResults = async (attemptId: string) => {
    if (!attemptId) return;
    setViewingAttempt(attemptId);
    setLoadingAttemptResults(true);
    try {
      const res = await api.get(`/admin/attempt/${attemptId}/results`);
      setAttemptResults(res.data);
    } catch (err: unknown) {
      console.error(err);
      alert("Failed to load attempt results");
      setAttemptResults(null);
    } finally {
      setLoadingAttemptResults(false);
    }
  };

  const handleExportAttemptResults = async (attemptId: string | null) => {
    if (!attemptId) return;
    setExportingAttemptId(attemptId);
    try {
      const res = await api.get(`/admin/attempt/${attemptId}/export`, {
        responseType: "blob",
      });
      downloadBlobResponse(res.data, res.headers["content-disposition"] as string | undefined, "attempt-results.xlsx");
    } catch (err: unknown) {
      console.error(err);
      alert("Failed to export attempt results");
    } finally {
      setExportingAttemptId(null);
    }
  };

  const handleExportAllResults = async () => {
    if (!selectedAssessment) return;
    setExportingAll(true);
    try {
      const params = new URLSearchParams();
      if (selectedBatch) params.set("batch_id", selectedBatch);
      if (statusFilter) params.set("status_filter", statusFilter);
      const qs = params.toString();
      const res = await api.get(`/assessments/${selectedAssessment}/results/export${qs ? `?${qs}` : ""}`, {
        responseType: "blob",
      });
      downloadBlobResponse(res.data, res.headers["content-disposition"] as string | undefined, "assessment-results.xlsx");
    } catch (err: unknown) {
      console.error(err);
      alert("Failed to export all results");
    } finally {
      setExportingAll(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Topic Scores Modal */}
      {showTopicModal && selectedUserTopics && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-white rounded-lg shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-auto">
            <div className="sticky top-0 bg-white px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-lg font-semibold">Topic-wise Performance</h3>
              <button
                onClick={() => setShowTopicModal(false)}
                className="text-gray-500 hover:text-gray-700"
              >
                ✕
              </button>
            </div>
            <div className="p-6">
              <p className="text-sm text-gray-600 mb-6">User: <span className="font-medium">{selectedUserTopics.userName}</span></p>
              {selectedUserTopics.topics.length > 0 ? (
                <div className="grid grid-cols-2 md:grid-cols-3 gap-6">
                  {selectedUserTopics.topics.map((topic: TopicScore, idx: number) => (
                    <div key={idx} className="flex flex-col items-center">
                      <CircularProgress
                        percentage={topic.percentage}
                        label={`${topic.topic_name}\n${topic.correct.toFixed(1)}/${topic.total}`}
                        size={140}
                        strokeWidth={10}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-center text-gray-500">No topic data available</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Attempt Results Modal (Admin) */}
      {viewingAttempt && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-[var(--radius)] shadow-xl w-full max-w-3xl max-h-[90vh] overflow-auto">
            <div className="sticky top-0 bg-white border-b border-[var(--color-border)] px-6 py-4 flex items-center justify-between">
              <h2 className="text-base font-semibold">{attemptResults?.assessment_title || "Results"}</h2>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleExportAttemptResults(viewingAttempt)}
                  disabled={!viewingAttempt || exportingAttemptId === viewingAttempt}
                  className="h-8 px-3 text-xs font-medium rounded bg-[var(--color-primary)] text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50 cursor-pointer"
                >
                  {exportingAttemptId === viewingAttempt ? "Exporting..." : "Export"}
                </button>
                <button
                  onClick={() => { setViewingAttempt(null); setAttemptResults(null); }}
                  className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-100 cursor-pointer text-lg"
                >
                  &times;
                </button>
              </div>
            </div>

            <div className="p-6 space-y-6">
              {loadingAttemptResults && (
                <p className="text-center text-sm text-[var(--color-text-secondary)]">Loading results...</p>
              )}

              {attemptResults && !loadingAttemptResults && (
                <>
                  <div className="grid grid-cols-3 gap-4">
                    <div className={`${card} p-4 text-center`}>
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Score</p>
                      <p className="text-2xl font-bold text-[var(--color-primary)]">
                        {attemptResults.evaluation_pending ? "Pending" : attemptResults.score !== null ? `${attemptResults.score}%` : "N/A"}
                      </p>
                    </div>
                    <div className={`${card} p-4 text-center`}>
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Answered</p>
                      <p className="text-2xl font-bold">{attemptResults.answered}/{attemptResults.total_questions}</p>
                    </div>
                    <div className={`${card} p-4 text-center`}>
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Status</p>
                      <p className={`text-lg font-bold ${attemptResults.status === "completed" ? "text-[var(--color-success)]" : attemptResults.status === "evaluating" ? "text-[var(--color-primary)]" : "text-[var(--color-danger)]"}`}>
                        {attemptResults.status}
                      </p>
                    </div>
                  </div>

                  {attemptResults.evaluation_pending && (
                    <div className="p-4 rounded-[var(--radius-sm)] border border-blue-200 bg-blue-50 text-sm text-[var(--color-primary)]">
                      Some subjective answers are still being evaluated. Results will update when evaluation completes.
                    </div>
                  )}

                  {attemptResults.topic_scores.length > 0 && (
                    <div className={`${card} p-5`}>
                      <h3 className="text-sm font-semibold mb-3">Topic Performance</h3>
                      <div className="space-y-3">
                        {attemptResults.topic_scores.map((ts) => (
                          <div key={ts.topic_name}>
                            <div className="flex justify-between text-xs mb-1">
                              <span className="font-medium">{ts.topic_name}</span>
                              <span className="text-[var(--color-text-secondary)]">{ts.correct}/{ts.total} ({ts.percentage}%)</span>
                            </div>
                            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                              <div className="h-full rounded-full" style={{ width: `${ts.percentage}%`, backgroundColor: ts.percentage >= 70 ? "var(--color-success)" : ts.percentage >= 40 ? "var(--color-warning)" : "var(--color-danger)" }} />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className={`${card} overflow-hidden`}>
                    <div className="px-5 py-4 border-b border-[var(--color-border)]">
                      <h3 className="text-sm font-semibold">Question Review</h3>
                    </div>
                    <div className="divide-y divide-[var(--color-border)]">
                      {attemptResults.answers.map((ans, idx) => (
                        <div key={ans.question_id} className="px-5 py-4">
                          <div className="flex items-start gap-3">
                            <span className={`mt-0.5 w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${ans.is_correct ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
                              {idx + 1}
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-start justify-between gap-3 mb-2">
                                <p className="text-sm font-medium">{ans.question_text}</p>
                                <span className={`shrink-0 inline-flex items-center px-2 py-1 rounded text-xs font-semibold ${ans.score === null ? "bg-gray-100 text-gray-600" : ans.score >= 0.999 ? "bg-green-50 text-green-700" : ans.score > 0 ? "bg-amber-50 text-amber-700" : "bg-red-50 text-red-700"}`}>
                                  Score: {ans.score === null ? "Pending" : `${ans.score} / 1`}
                                </span>
                              </div>
                              <p className="text-xs text-[var(--color-text-secondary)] mb-1">{ans.topic_name} • {ans.question_type}</p>
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                                <div className={`p-2 rounded ${ans.is_correct ? "bg-green-50" : "bg-red-50"}`}>
                                  <span className="font-medium">Your answer: </span>
                                  <span>{ans.your_answer || "—"}</span>
                                </div>
                                {!ans.is_correct && (
                                  <div className="p-2 rounded bg-green-50">
                                    <span className="font-medium">Correct: </span>
                                    <span>{ans.correct_answer || "—"}</span>
                                  </div>
                                )}
                              </div>
                              {ans.suggestion && (ans.question_type === "text" || ans.question_type === "coding") && (
                                <div className="mt-2 p-3 rounded bg-blue-50 border border-blue-100 text-xs text-[var(--color-primary)]">
                                  <span className="font-medium">Suggestion: </span>
                                  <span>{ans.suggestion}</span>
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Evaluation Error Modal */}
      {errorModalUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-white rounded-lg shadow-2xl max-w-lg w-full">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-lg font-semibold text-red-700">Evaluation Failed</h3>
              <button
                onClick={() => setErrorModalUser(null)}
                className="text-gray-500 hover:text-gray-700"
              >
                ✕
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <p className="text-xs text-gray-500 mb-1">User</p>
                <p className="font-medium">{errorModalUser.user_name} ({errorModalUser.username})</p>
              </div>
              <div>
                <p className="text-xs text-gray-500 mb-1">Error Category</p>
                <span className={`inline-flex px-2.5 py-1 text-xs font-semibold rounded-full ${
                  errorModalUser.evaluation_error_category === "content_filtered"
                    ? "bg-red-100 text-red-800"
                    : errorModalUser.evaluation_error_category === "auth_error"
                    ? "bg-yellow-100 text-yellow-800"
                    : errorModalUser.evaluation_error_category === "rate_limit"
                    ? "bg-orange-100 text-orange-800"
                    : "bg-gray-100 text-gray-800"
                }`}>
                  {errorModalUser.evaluation_error || "Unknown error"}
                </span>
              </div>
              <div>
                <p className="text-xs text-gray-500 mb-1">Recommended Action</p>
                <p className="text-sm text-gray-700">
                  {errorModalUser.evaluation_error_category === "content_filtered"
                    ? "The student's answer triggered Azure content filters (possible prompt injection or harmful content). Review the answer and Re-enable the test if needed."
                    : errorModalUser.evaluation_error_category === "auth_error"
                    ? "The API key or endpoint is invalid. Fix the credentials in .env and click Retry Eval."
                    : errorModalUser.evaluation_error_category === "rate_limit"
                    ? "The API rate limit was exceeded. Wait a few minutes and click Retry Eval."
                    : errorModalUser.evaluation_error_category === "timeout"
                    ? "The LLM request timed out. This is usually transient — click Retry Eval."
                    : "An unexpected error occurred. Check the server logs or click Retry Eval."}
                </p>
              </div>
              <div className="flex gap-2 pt-2 border-t border-gray-100">
                {errorModalUser.evaluation_error_category !== "content_filtered" && errorModalUser.evaluation_job_id && (
                  <button
                    onClick={() => { handleRetryEvaluation(errorModalUser.evaluation_job_id!); setErrorModalUser(null); }}
                    className="px-3 py-1.5 text-xs font-medium rounded bg-orange-100 text-orange-700 hover:bg-orange-200 cursor-pointer transition-colors"
                  >
                    Retry Eval
                  </button>
                )}
                <button
                  onClick={() => { handleResetAttempt(errorModalUser.attempt_id, errorModalUser.user_name); setErrorModalUser(null); }}
                  className="px-3 py-1.5 text-xs font-medium rounded bg-red-100 text-red-700 hover:bg-red-200 cursor-pointer transition-colors"
                >
                  Re-enable Test
                </button>
                <button
                  onClick={() => setErrorModalUser(null)}
                  className="px-3 py-1.5 text-xs font-medium rounded bg-gray-100 text-gray-600 hover:bg-gray-200 cursor-pointer transition-colors ml-auto"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className={`${card} p-5`}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
              Filter by Batch
            </label>
            <select
              className={`${selectClass} w-full`}
              value={selectedBatch}
              onChange={(e) => {
                setSelectedBatch(e.target.value);
                setSelectedAssessment("");
                setResults(null);
              }}
            >
              <option value="">All Batches</option>
              {batches.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">
              Select Assessment
            </label>
            <select
              className={`${selectClass} w-full`}
              value={selectedAssessment}
              onChange={(e) => handleAssessmentChange(e.target.value)}
            >
              <option value="">Select Assessment</option>
              {filteredAssessments.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {loading && (
        <div className="text-center py-8 text-[var(--color-text-secondary)] text-sm">
          Loading results...
        </div>
      )}

      {results && (
        <>
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
            <div>
              <p className="text-sm font-semibold">Results Summary</p>
              <p className="text-xs text-[var(--color-text-secondary)]">
                {selectedAssessmentName} - {selectedBatchName}
                {statusFilter ? ` - ${statusFilter}` : ""}
              </p>
            </div>
            <button
              onClick={handleExportAllResults}
              disabled={exportingAll || !selectedAssessment}
              className="h-9 px-4 bg-[var(--color-primary)] text-white text-sm font-medium rounded-[var(--radius-sm)] hover:bg-[var(--color-primary-hover)] disabled:opacity-50 cursor-pointer"
            >
              {exportingAll ? "Exporting..." : "Export All Users"}
            </button>
          </div>

          {/* Summary Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className={`${card} p-5`}>
              <p className="text-xs font-medium text-[var(--color-text-secondary)] mb-1">Average Score</p>
              <p className="text-2xl font-bold text-[var(--color-primary)]">
                {results.average_score !== null ? `${results.average_score}%` : "N/A"}
              </p>
            </div>
            <div className={`${card} p-5`}>
              <p className="text-xs font-medium text-[var(--color-text-secondary)] mb-1">Completion Rate</p>
              <p className="text-2xl font-bold text-[var(--color-success)]">
                {results.total_participants > 0
                  ? `${Math.round((results.completed_count / results.total_participants) * 100)}%`
                  : "0%"}
              </p>
            </div>
            <div className={`${card} p-5`}>
              <p className="text-xs font-medium text-[var(--color-text-secondary)] mb-1">Participants</p>
              <p className="text-2xl font-bold">
                {results.completed_count}/{results.total_participants}
              </p>
            </div>
          </div>

          {/* Topic Performance */}
          {results.topic_performance.length > 0 && (
            <div className={`${card} p-5`}>
              <h3 className="text-sm font-semibold mb-4">Topic Performance</h3>
              <div className="space-y-3">
                {results.topic_performance.map((tp) => (
                  <div key={tp.topic_name}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="font-medium">{tp.topic_name}</span>
                      <span className="text-[var(--color-text-secondary)]">
                        {tp.correct}/{tp.total_questions} correct ({tp.percentage}%)
                      </span>
                    </div>
                    <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${tp.percentage}%`,
                          backgroundColor:
                            tp.percentage >= 70
                              ? "var(--color-success)"
                              : tp.percentage >= 40
                              ? "var(--color-warning)"
                              : "var(--color-danger)",
                        }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Per-User Results Table */}
          <div className={`${card} overflow-hidden`}>
            <div className="px-5 py-4 border-b border-[var(--color-border)] flex items-center justify-between">
              <h3 className="text-sm font-semibold">Individual Results</h3>
              <div className="flex items-center gap-3">
                <select
                  className="border border-[var(--color-border)] rounded px-2 py-1.5 text-xs bg-white"
                  value={statusFilter}
                  onChange={(e) => { setStatusFilter(e.target.value); setPage(1); if (selectedAssessment) loadResults(selectedAssessment, 1, undefined, e.target.value); }}
                >
                  <option value="">All Statuses</option>
                  <option value="pending">Pending</option>
                  <option value="in_progress">In Progress</option>
                  <option value="completed">Completed</option>
                  <option value="evaluating">Evaluating</option>
                  <option value="missed">Missed</option>
                </select>
                <select
                  className="border border-[var(--color-border)] rounded px-2 py-1.5 text-xs bg-white"
                  value={pageSize}
                  onChange={(e) => { const ps = Number(e.target.value); setPageSize(ps); setPage(1); if (selectedAssessment) loadResults(selectedAssessment, 1, ps); }}
                >
                  <option value={10}>10 / page</option>
                  <option value={20}>20 / page</option>
                  <option value={50}>50 / page</option>
                </select>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left">
                  <tr>
                    <th className="px-5 py-3 font-medium text-[var(--color-text-secondary)] cursor-pointer select-none hover:text-[var(--color-text)]" onClick={() => { if (sortField === "name") setSortDir(d => d === "asc" ? "desc" : "asc"); else { setSortField("name"); setSortDir("asc"); } }}>Name {sortField === "name" ? (sortDir === "asc" ? "↑" : "↓") : "↕"}</th>
                    <th className="px-5 py-3 font-medium text-[var(--color-text-secondary)] cursor-pointer select-none hover:text-[var(--color-text)]" onClick={() => { if (sortField === "username") setSortDir(d => d === "asc" ? "desc" : "asc"); else { setSortField("username"); setSortDir("asc"); } }}>Username {sortField === "username" ? (sortDir === "asc" ? "↑" : "↓") : "↕"}</th>
                    <th className="px-5 py-3 font-medium text-[var(--color-text-secondary)] cursor-pointer select-none hover:text-[var(--color-text)]" onClick={() => { if (sortField === "score") setSortDir(d => d === "asc" ? "desc" : "asc"); else { setSortField("score"); setSortDir("desc"); } }}>Score {sortField === "score" ? (sortDir === "asc" ? "↑" : "↓") : "↕"}</th>
                    <th className="px-5 py-3 font-medium text-[var(--color-text-secondary)] cursor-pointer select-none hover:text-[var(--color-text)]" onClick={() => { if (sortField === "status") setSortDir(d => d === "asc" ? "desc" : "asc"); else { setSortField("status"); setSortDir("asc"); } }}>Status {sortField === "status" ? (sortDir === "asc" ? "↑" : "↓") : "↕"}</th>
                    <th className="px-5 py-3 font-medium text-[var(--color-text-secondary)]">Answered</th>
                    <th className="px-5 py-3 font-medium text-[var(--color-text-secondary)]">Submitted</th>
                    <th className="px-5 py-3 font-medium text-[var(--color-text-secondary)]">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border)]">
                  {(() => {
                    let items = [...results.user_results];
                    if (sortField) {
                      items.sort((a, b) => {
                        const dir = sortDir === "asc" ? 1 : -1;
                        if (sortField === "name") return (a.user_name || "").localeCompare(b.user_name || "") * dir;
                        if (sortField === "username") return (a.username || "").localeCompare(b.username || "") * dir;
                        if (sortField === "score") return ((a.score ?? -1) - (b.score ?? -1)) * dir;
                        if (sortField === "status") return (a.status || "").localeCompare(b.status || "") * dir;
                        return 0;
                      });
                    }
                    return items;
                  })().map((ur) => (
                    <tr key={ur.user_id} className="hover:bg-gray-50">
                      <td className="px-5 py-3 font-medium">{ur.user_name}</td>
                      <td className="px-5 py-3 text-[var(--color-text-secondary)]">{ur.username}</td>
                      <td className="px-5 py-3">
                        <span
                          className={`font-semibold ${
                            ur.score !== null && ur.score >= 70
                              ? "text-[var(--color-success)]"
                              : ur.score !== null && ur.score >= 40
                              ? "text-[var(--color-warning)]"
                              : "text-[var(--color-danger)]"
                          }`}
                        >
                          {ur.score !== null ? `${ur.score}%` : "—"}
                        </span>
                      </td>
                      <td className="px-5 py-3">
                        <span
                          className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${
                            ur.status === "completed"
                              ? "bg-green-50 text-green-700"
                              : ur.status === "missed"
                              ? "bg-red-50 text-red-700"
                              : ur.status === "evaluating"
                              ? "bg-blue-50 text-blue-700"
                              : ur.status === "pending"
                              ? "bg-purple-50 text-purple-700"
                              : "bg-yellow-50 text-yellow-700"
                          }`}
                        >
                          {ur.status}
                        </span>
                        {ur.evaluation_status === "failed" && (
                          <span
                            className="inline-flex ml-1 px-2 py-0.5 text-xs font-medium rounded-full bg-red-50 text-red-700 cursor-pointer hover:bg-red-100 transition-colors"
                            title={ur.evaluation_error || "Evaluation failed"}
                            onClick={() => setErrorModalUser(ur)}
                          >
                            eval failed ⓘ
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-[var(--color-text-secondary)]">{ur.total_answered}</td>
                      <td className="px-5 py-3 text-[var(--color-text-secondary)] text-xs">
                        {ur.submitted_at
                          ? new Date(ur.submitted_at).toLocaleString()
                          : "—"}
                      </td>
                      <td className="px-5 py-3">
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleViewAttemptResults(ur.attempt_id || "")}
                            disabled={!ur.attempt_id}
                            className="px-2 py-1.5 text-xs font-medium rounded bg-[var(--color-primary)] text-white hover:bg-[var(--color-primary-hover)] disabled:opacity-50 cursor-pointer transition-colors"
                          >
                            View
                          </button>
                          <button
                            onClick={() => ur.attempt_id && handleViewTopics(ur.attempt_id, ur.user_name)}
                            disabled={loadingTopics || !ur.attempt_id}
                            className="px-2 py-1.5 text-xs font-medium rounded bg-purple-100 text-purple-700 hover:bg-purple-200 disabled:opacity-50 cursor-pointer transition-colors"
                          >
                            Topics
                          </button>
                          {(ur.status === "missed" || ur.status === "in_progress" || ur.status === "completed") && (
                            <button
                              onClick={() => handleResetAttempt(ur.attempt_id, ur.user_name)}
                              disabled={resettingAttemptId === ur.attempt_id}
                              className="px-2 py-1.5 text-xs font-medium rounded bg-blue-100 text-blue-700 hover:bg-blue-200 disabled:opacity-50 cursor-pointer transition-colors"
                            >
                              {resettingAttemptId === ur.attempt_id ? "Resetting..." : "Re-enable"}
                            </button>
                          )}
                          {ur.evaluation_status === "failed" && ur.evaluation_job_id && (
                            <>
                              {ur.evaluation_error_category !== "content_filtered" && (
                                <button
                                  onClick={() => ur.evaluation_job_id && handleRetryEvaluation(ur.evaluation_job_id)}
                                  disabled={retryingJobId === ur.evaluation_job_id}
                                  className="px-2 py-1.5 text-xs font-medium rounded bg-orange-100 text-orange-700 hover:bg-orange-200 disabled:opacity-50 cursor-pointer transition-colors"
                                >
                                  {retryingJobId === ur.evaluation_job_id ? "Retrying..." : "Retry Eval"}
                                </button>
                              )}
                              <button
                                onClick={() => handleResetAttempt(ur.attempt_id, ur.user_name)}
                                disabled={resettingAttemptId === ur.attempt_id}
                                className="px-2 py-1.5 text-xs font-medium rounded bg-red-100 text-red-700 hover:bg-red-200 disabled:opacity-50 cursor-pointer transition-colors"
                              >
                                {resettingAttemptId === ur.attempt_id ? "Resetting..." : "Re-enable"}
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {results.user_results.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-5 py-8 text-center text-[var(--color-text-secondary)]">
                        No attempts yet
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {results.total_user_results > 0 && (() => {
              const totalFiltered = results.total_user_results;
              const totalPages = Math.max(1, Math.ceil(totalFiltered / pageSize));
              return (
                <div className="px-5 py-3 border-t border-[var(--color-border)] flex items-center justify-between">
                  <span className="text-xs text-[var(--color-text-secondary)]">
                    Showing {Math.min((page - 1) * pageSize + 1, totalFiltered)}–{Math.min(page * pageSize, totalFiltered)} of {totalFiltered}
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => { const p = Math.max(1, page - 1); setPage(p); loadResults(selectedAssessment, p); }}
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
                          onClick={() => { setPage(pageNum); loadResults(selectedAssessment, pageNum); }}
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
                      onClick={() => { const p = Math.min(totalPages, page + 1); setPage(p); loadResults(selectedAssessment, p); }}
                      disabled={page === totalPages}
                      className="px-2.5 py-1.5 text-xs rounded border border-[var(--color-border)] disabled:opacity-40 hover:bg-gray-50 cursor-pointer disabled:cursor-default"
                    >
                      Next →
                    </button>
                  </div>
                </div>
              );
            })()}
          </div>
        </>
      )}

      {!results && !loading && selectedAssessment && (
        <div className="text-center py-8 text-[var(--color-text-secondary)] text-sm">
          No results available for this assessment
        </div>
      )}

      {!selectedAssessment && !loading && (
        <div className={`${card} p-12 text-center`}>
          <svg className="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
          </svg>
          <p className="text-sm text-[var(--color-text-secondary)]">
            Select an assessment to view results
          </p>
        </div>
      )}
    </div>
  );
}
