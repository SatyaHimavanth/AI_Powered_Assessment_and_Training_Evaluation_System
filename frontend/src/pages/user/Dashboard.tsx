import { useEffect, useState } from "react";
import api from "../../api";
import type { BatchInfo } from "../admin/types";

interface UserProfile {
  username: string;
  email: string;
  name: string;
  role: string;
}

interface UserAssessment {
  id: string;
  title: string;
  description: string | null;
  duration: number;
  total_questions: number;
  start_time: string | null;
  end_time: string | null;
  status: string;
  attempt_id: string | null;
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
  suggestion: string | null;
}

interface TopicScore {
  topic_name: string;
  total: number;
  correct: number;
  percentage: number;
}

interface UserResults {
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

interface Props {
  profile: UserProfile | null;
  onStartExam: (assessment: UserAssessment) => void;
}

const card = "bg-white rounded-[var(--radius)] shadow-[var(--shadow)] border border-[var(--color-border)]";

export default function Dashboard({ profile, onStartExam }: Props) {
  const [assessments, setAssessments] = useState<UserAssessment[]>([]);
  const [batches, setBatches] = useState<BatchInfo[]>([]);
  const [viewingResults, setViewingResults] = useState<string | null>(null);
  const [results, setResults] = useState<UserResults | null>(null);
  const [loadingResults, setLoadingResults] = useState(false);

  useEffect(() => {
    loadAssessments();
  }, []);

  useEffect(() => {
    if (profile) {
      loadBatches();
    }
  }, [profile]);

  useEffect(() => {
    const hasEvaluating = assessments.some((assessment) => assessment.status === "evaluating");
    if (!hasEvaluating) {
      return;
    }

    const interval = window.setInterval(() => {
      loadAssessments();
      if (viewingResults && results?.evaluation_pending) {
        viewResults(viewingResults);
      }
    }, 10000);

    return () => window.clearInterval(interval);
  }, [assessments, viewingResults, results]);

  async function loadAssessments() {
    try {
      const res = await api.get("/user/assessments/");
      setAssessments(res.data);
    } catch {
      // ignore
    }
  }

  async function loadBatches() {
    try {
      const res = await api.get("/user/assessments/batches");
      setBatches(res.data || []);
    } catch {
      // ignore
    }
  }

  async function viewResults(assessmentId: string) {
    setViewingResults(assessmentId);
    setLoadingResults(true);
    try {
      const res = await api.get(`/user/assessments/${assessmentId}/results`);
      setResults(res.data);
    } catch {
      setResults(null);
    } finally {
      setLoadingResults(false);
    }
  }

  const exportResults = async (assessmentId: string) => {
    try {
      const res = await api.get(`/user/assessments/${assessmentId}/export`, {
        responseType: "blob",
      });
      const blobUrl = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement("a");
      const disposition = res.headers["content-disposition"] as string | undefined;
      const filename = disposition?.split("filename=")[1]?.replace(/"/g, "")?.trim();
      link.href = blobUrl;
      link.download = filename || "results.xlsx";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(blobUrl);
    } catch {
      // ignore for now
    }
  };

  const getAssessmentTimestamp = (a: UserAssessment) => {
    // Prefer end_time, then start_time. Missing dates are treated as very old so they appear last.
    const t = a.end_time ?? a.start_time;
    const parsed = t ? Date.parse(t) : NaN;
    return Number.isFinite(parsed) ? parsed : 0;
  };

  const sortDescByTime = (arr: UserAssessment[]) =>
    arr.slice().sort((x, y) => getAssessmentTimestamp(y) - getAssessmentTimestamp(x));

  const pending = sortDescByTime(assessments.filter((a) => a.status === "pending"));
  const evaluating = sortDescByTime(assessments.filter((a) => a.status === "evaluating"));
  const completed = sortDescByTime(assessments.filter((a) => a.status === "completed"));
  const incomplete = sortDescByTime(assessments.filter((a) => a.status === "incomplete"));
  const missed = sortDescByTime(assessments.filter((a) => a.status === "missed"));

  const isWithinWindow = (a: UserAssessment) => {
    const now = new Date();
    if (a.start_time && now < new Date(a.start_time)) return false;
    if (a.end_time && now > new Date(a.end_time)) return false;
    return true;
  };

  return (
    <div className="space-y-6">
      {/* Profile Card */}
      {profile && (
        <div className={`${card} p-6`}>
          <div className="flex items-center gap-4 mb-5">
            <div className="w-12 h-12 rounded-full bg-[var(--color-primary)] text-white flex items-center justify-center text-lg font-semibold">
              {profile.name.charAt(0).toUpperCase()}
            </div>
            <div>
              <h2 className="text-base font-semibold">Welcome back, {profile.name}</h2>
              <p className="text-sm text-[var(--color-text-secondary)]">@{profile.username}</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4 pt-4 border-t border-[var(--color-border)]">
            <div>
              <p className="text-xs text-[var(--color-text-secondary)] mb-0.5">Email</p>
              <p className="text-sm font-medium">{profile.email}</p>
            </div>
            <div>
              <p className="text-xs text-[var(--color-text-secondary)] mb-0.5">Role</p>
              <span className="inline-flex items-center h-6 px-2.5 rounded-full text-xs font-medium bg-blue-50 text-[var(--color-primary)]">
                {profile.role}
              </span>
            </div>
          </div>
          <div className="mt-3">
            <p className="text-xs text-[var(--color-text-secondary)] mb-1">Batches</p>
            {batches.length === 0 ? (
              <p className="text-sm text-[var(--color-text-secondary)]">Not enrolled in any batches.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {batches.map((bb) => (
                  <span key={bb.id} className="inline-flex items-center gap-2 h-6 px-2.5 rounded-full text-xs font-medium bg-gray-100 text-[var(--color-text)]">
                    <span>{bb.name}</span>
                    <span className="text-[var(--color-text-secondary)]">{bb.status}</span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Summary Cards */}
      <div>
        <h2 className="text-sm font-semibold mb-3">My Assessments</h2>
        <div className="grid grid-cols-4 gap-4">
          <div className={`${card} p-5`}>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-8 h-8 rounded-[var(--radius-sm)] bg-amber-50 text-[var(--color-warning)] flex items-center justify-center">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-[var(--color-warning)]">Pending</p>
            </div>
            <p className="text-2xl font-semibold">{pending.length}</p>
          </div>

          <div className={`${card} p-5`}>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-8 h-8 rounded-[var(--radius-sm)] bg-blue-50 text-[var(--color-primary)] flex items-center justify-center">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 6.75v10.5m-4.5-7.5v4.5m-4.5-2.25v2.25M3.75 19.5h16.5" />
                </svg>
              </div>
              <p className="text-sm font-medium text-[var(--color-primary)]">Evaluating</p>
            </div>
            <p className="text-2xl font-semibold">{evaluating.length}</p>
          </div>

          <div className={`${card} p-5`}>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-8 h-8 rounded-[var(--radius-sm)] bg-green-50 text-[var(--color-success)] flex items-center justify-center">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-[var(--color-success)]">Completed</p>
            </div>
            <p className="text-2xl font-semibold">{completed.length}</p>
          </div>

          <div className={`${card} p-5`}>
            <div className="flex items-center gap-3 mb-3">
              <div className="w-8 h-8 rounded-[var(--radius-sm)] bg-red-50 text-[var(--color-danger)] flex items-center justify-center">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-[var(--color-danger)]">Missed / Incomplete</p>
            </div>
            <p className="text-2xl font-semibold">{missed.length + incomplete.length}</p>
          </div>
        </div>
      </div>

      {/* Pending Assessments List */}
      {pending.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold mb-3">Available Assessments</h2>
          <div className="space-y-3">
            {pending.map((a) => {
              const canStart = isWithinWindow(a);
              return (
                <div key={a.id} className={`${card} p-5 flex items-center justify-between`}>
                  <div>
                    <p className="text-sm font-medium">{a.title}</p>
                    {a.description && <p className="text-xs text-[var(--color-text-secondary)] mt-0.5">{a.description}</p>}
                    <div className="flex gap-4 mt-2">
                      <span className="text-xs text-[var(--color-text-secondary)]">{a.total_questions} questions</span>
                      <span className="text-xs text-[var(--color-text-secondary)]">{a.duration} min</span>
                      {a.start_time && (
                        <span className="text-xs text-[var(--color-text-secondary)]">
                          Opens: {new Date(a.start_time).toLocaleString()}
                        </span>
                      )}
                      {a.end_time && (
                        <span className="text-xs text-[var(--color-text-secondary)]">
                          Closes: {new Date(a.end_time).toLocaleString()}
                        </span>
                      )}
                    </div>
                  </div>
                  <button
                    onClick={() => onStartExam(a)}
                    disabled={!canStart}
                    className="h-9 px-4 bg-[var(--color-primary)] text-white text-sm font-medium rounded-[var(--radius-sm)] hover:bg-[var(--color-primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                  >
                    {canStart ? "Start Exam" : "Not Available Yet"}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
      
      {/* Incomplete - Resumable */}
      {incomplete.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold mb-3">Incomplete — Resume Available</h2>
          <div className="space-y-3">
            {incomplete.map((a) => {
              const canResume = isWithinWindow(a);
              return (
                <div key={a.id} className={`${card} p-5 flex items-center justify-between border-l-4 border-l-amber-400`}>
                  <div>
                    <p className="text-sm font-medium">{a.title}</p>
                    {a.description && <p className="text-xs text-[var(--color-text-secondary)] mt-0.5">{a.description}</p>}
                    <div className="flex gap-4 mt-2">
                      <span className="text-xs text-[var(--color-text-secondary)]">{a.total_questions} questions</span>
                      <span className="text-xs text-[var(--color-text-secondary)]">{a.duration} min</span>
                    </div>
                    <p className="text-xs text-amber-600 mt-1">You have an in-progress attempt. Click Resume to continue.</p>
                  </div>
                  <button
                    onClick={() => onStartExam(a)}
                    disabled={!canResume}
                    className="h-9 px-5 bg-amber-500 text-white text-sm font-medium rounded-[var(--radius-sm)] hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                  >
                    {canResume ? "Resume" : "Window Closed"}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Completed */}
      {evaluating.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold mb-3">Under Evaluation</h2>
          <div className="space-y-3">
            {evaluating.map((a) => (
              <div key={a.id} className={`${card} p-5 flex items-center justify-between`}>
                <div>
                  <p className="text-sm font-medium">{a.title}</p>
                  <div className="flex gap-4 mt-1">
                    <span className="text-xs text-[var(--color-text-secondary)]">{a.total_questions} questions</span>
                    <span className="text-xs text-[var(--color-text-secondary)]">{a.duration} min</span>
                  </div>
                  <p className="text-xs text-[var(--color-text-secondary)] mt-1">
                    Your answers were submitted. Evaluation is in progress.
                  </p>
                </div>
                <span className="inline-flex items-center h-7 px-3 rounded-full text-xs font-medium bg-blue-50 text-[var(--color-primary)]">
                  Evaluating
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {completed.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold mb-3">Completed</h2>
          <div className="space-y-3">
            {completed.map((a) => (
              <div key={a.id} className={`${card} p-5 flex items-center justify-between`}>
                <div>
                  <p className="text-sm font-medium">{a.title}</p>
                  <div className="flex gap-4 mt-1">
                    <span className="text-xs text-[var(--color-text-secondary)]">{a.total_questions} questions</span>
                    <span className="text-xs text-[var(--color-text-secondary)]">{a.duration} min</span>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => exportResults(a.id)}
                    className="h-9 px-4 border border-[var(--color-border)] text-sm font-medium rounded-[var(--radius-sm)] hover:bg-gray-50 cursor-pointer"
                  >
                    Export
                  </button>
                  <button
                    onClick={() => viewResults(a.id)}
                    className="h-9 px-4 bg-[var(--color-primary)] text-white text-sm font-medium rounded-[var(--radius-sm)] hover:bg-[var(--color-primary-hover)] cursor-pointer"
                  >
                    View Results
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Missed */}
      {missed.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold mb-3">Missed</h2>
          <div className="space-y-3">
            {missed.map((a) => (
              <div key={a.id} className={`${card} p-5 flex items-center justify-between`}>
                <div>
                  <p className="text-sm font-medium">{a.title}</p>
                  <div className="flex gap-4 mt-1">
                    <span className="text-xs text-[var(--color-text-secondary)]">{a.total_questions} questions</span>
                    <span className="text-xs text-[var(--color-text-secondary)]">{a.duration} min</span>
                  </div>
                </div>
                <span className="inline-flex items-center h-7 px-3 rounded-full text-xs font-medium bg-red-50 text-[var(--color-danger)]">
                  Missed
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Results Panel */}
      {viewingResults && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-[var(--radius)] shadow-xl w-full max-w-3xl max-h-[90vh] overflow-auto">
            <div className="sticky top-0 bg-white border-b border-[var(--color-border)] px-6 py-4 flex items-center justify-between">
              <h2 className="text-base font-semibold">
                {results?.assessment_title || "Results"}
              </h2>
              <button
                onClick={() => { setViewingResults(null); setResults(null); }}
                className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-100 cursor-pointer text-lg"
              >
                &times;
              </button>
            </div>

            <div className="p-6 space-y-6">
              {loadingResults && (
                <p className="text-center text-sm text-[var(--color-text-secondary)]">Loading results...</p>
              )}

              {results && !loadingResults && (
                <>
                  {/* Score Cards */}
                  <div className="grid grid-cols-3 gap-4">
                    <div className={`${card} p-4 text-center`}>
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Score</p>
                      <p className="text-2xl font-bold text-[var(--color-primary)]">
                        {results.evaluation_pending ? "Pending" : results.score !== null ? `${results.score}%` : "N/A"}
                      </p>
                    </div>
                    <div className={`${card} p-4 text-center`}>
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Answered</p>
                      <p className="text-2xl font-bold">
                        {results.answered}/{results.total_questions}
                      </p>
                    </div>
                    <div className={`${card} p-4 text-center`}>
                      <p className="text-xs text-[var(--color-text-secondary)] mb-1">Status</p>
                      <p className={`text-lg font-bold ${results.status === "completed" ? "text-[var(--color-success)]" : results.status === "evaluating" ? "text-[var(--color-primary)]" : "text-[var(--color-danger)]"}`}>
                        {results.status}
                      </p>
                    </div>
                  </div>

                  {results.evaluation_pending && (
                    <div className="p-4 rounded-[var(--radius-sm)] border border-blue-200 bg-blue-50 text-sm text-[var(--color-primary)]">
                      Your subjective answers are still being evaluated by the LLM. Results will update automatically when evaluation completes.
                    </div>
                  )}

                  {/* Topic Scores */}
                  {results.topic_scores.length > 0 && (
                    <div className={`${card} p-5`}>
                      <h3 className="text-sm font-semibold mb-3">Topic Performance</h3>
                      <div className="space-y-3">
                        {results.topic_scores.map((ts) => (
                          <div key={ts.topic_name}>
                            <div className="flex justify-between text-xs mb-1">
                              <span className="font-medium">{ts.topic_name}</span>
                              <span className="text-[var(--color-text-secondary)]">
                                {ts.correct}/{ts.total} ({ts.percentage}%)
                              </span>
                            </div>
                            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                              <div
                                className="h-full rounded-full"
                                style={{
                                  width: `${ts.percentage}%`,
                                  backgroundColor:
                                    ts.percentage >= 70 ? "var(--color-success)"
                                    : ts.percentage >= 40 ? "var(--color-warning)"
                                    : "var(--color-danger)",
                                }}
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/*  */}
                  <div className={`${card} overflow-hidden`}>
                    <div className="px-5 py-4 border-b border-[var(--color-border)]">
                      <h3 className="text-sm font-semibold"></h3>
                    </div>
                    <div className="divide-y divide-[var(--color-border)]">
                      {results.answers.map((ans, idx) => (
                        <div key={ans.question_id} className="px-5 py-4">
                          <div className="flex items-start gap-3">
                            <span className={`mt-0.5 w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium ${
                              ans.is_correct ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
                            }`}>
                              {idx + 1}
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-start justify-between gap-3 mb-2">
                                <p className="text-sm font-medium">{ans.question_text}</p>
                                <span className={`shrink-0 inline-flex items-center px-2 py-1 rounded text-xs font-semibold ${
                                  ans.score === null
                                    ? "bg-gray-100 text-gray-600"
                                    : ans.score >= 0.999
                                    ? "bg-green-50 text-green-700"
                                    : ans.score > 0
                                    ? "bg-amber-50 text-amber-700"
                                    : "bg-red-50 text-red-700"
                                }`}>
                                  Score: {ans.score === null ? "Pending" : `${ans.score.toFixed(2)} / 1`}
                                </span>
                              </div>
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
                              <div className="mt-1.5 flex gap-2">
                                <span className="text-xs text-[var(--color-text-secondary)]">{ans.topic_name}</span>
                                <span className="text-xs text-[var(--color-text-secondary)]">• {ans.question_type}</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {!results && !loadingResults && (
                <p className="text-center text-sm text-[var(--color-text-secondary)]">No results available</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
