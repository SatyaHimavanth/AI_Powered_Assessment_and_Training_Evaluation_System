import { useEffect, useState, useMemo, useRef } from "react";
import api from "../../api";
import Toast from "../../components/Toast";

const card = "bg-white rounded-lg border border-gray-200 shadow-sm";

interface PracticeTestInfo {
  id: string;
  job_title: string;
  topics: string | null;
  difficulty: string;
  question_count: number;
  status: string;
  score: number | null;
  created_at: string;
  submitted_at: string | null;
}

interface QuestionItem {
  id: string;
  position: number;
  type: string;
  question: string;
  options: { text: string; is_correct?: boolean }[] | null;
  topic: string | null;
}

interface ResultQuestion {
  position: number;
  type: string;
  question: string;
  options: { text: string; is_correct?: boolean }[] | null;
  topic: string | null;
  user_answer: string | null;
  correct_answer: string | null;
  score: number | null;
  feedback: string | null;
}

type View = "home" | "create" | "test" | "result";

export default function Practice() {
  const [view, setView] = useState<View>("home");
  const [todayTest, setTodayTest] = useState<PracticeTestInfo | null>(null);
  const [history, setHistory] = useState<PracticeTestInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");

  const extractError = (err: unknown, fallback: string) => {
    const anyErr = err as any;
    try {
      if (anyErr?.response?.data) {
        const data = anyErr.response.data;
        if (typeof data.detail === "string") return data.detail;
        if (Array.isArray(data.detail)) return data.detail.join(", ");
        if (typeof data.message === "string") return data.message;
        if (typeof data === "string") return data;
        return JSON.stringify(data);
      }
      if (anyErr?.message) return anyErr.message;
    } catch (e) {
      // ignore parsing errors
    }
    return fallback;
  };

  // Access state
  const [accessInfo, setAccessInfo] = useState<{ has_access: boolean; expires_at: string | null; pending_request: boolean; requested_tests_per_day?: number | null; tests_per_day_granted?: number | null } | null>(null);
  const [requestingAccess, setRequestingAccess] = useState(false);
  const [showAccessForm, setShowAccessForm] = useState(false);
  const [accessReason, setAccessReason] = useState("");
  const [accessDays, setAccessDays] = useState(14);
  const [requestedTestsPerDay, setRequestedTestsPerDay] = useState(1);

  // Create form state
  const [jobTitle, setJobTitle] = useState("");
  const [jobDescription, setJobDescription] = useState("");
  const [topics, setTopics] = useState("");
  const [difficulty, setDifficulty] = useState("medium");
  const [questionCount, setQuestionCount] = useState(30);
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [creating, setCreating] = useState(false);

  // Test state
  const [testDetail, setTestDetail] = useState<{ id: string; questions: QuestionItem[] } | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [currentQ, setCurrentQ] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const submitLockRef = useRef(false);

  // Result state
  const [resultData, setResultData] = useState<{ score: number | null; questions: ResultQuestion[] } | null>(null);
  const [resultTestId, setResultTestId] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const todayCount = useMemo(() => {
    try {
      const today = new Date().toISOString().slice(0, 10);
      const ids = new Set<string>();
      history.forEach((h) => {
        if (new Date(h.created_at).toISOString().slice(0, 10) === today) ids.add(h.id);
      });
      if (todayTest && new Date(todayTest.created_at).toISOString().slice(0, 10) === today) ids.add(todayTest.id);
      return ids.size;
    } catch {
      return 0;
    }
  }, [history, todayTest]);

  const maxPerDay = (accessInfo && accessInfo.tests_per_day_granted) ? Number(accessInfo.tests_per_day_granted) : 3;
  const canCreateMore = Boolean(accessInfo?.has_access) && todayCount < maxPerDay;

  // Poll for status when generating
  useEffect(() => {
    if (todayTest?.status === "generating") {
      const interval = setInterval(async () => {
        try {
          const res = await api.get("/practice/today");
          if (res.data && res.data.status !== "generating") {
            setTodayTest(res.data);
            clearInterval(interval);
          }
        } catch { /* ignore */ }
      }, 3000);
      return () => clearInterval(interval);
    }
  }, [todayTest?.status]);

  async function loadData() {
    setLoading(true);
    try {
      const accessRes = await api.get("/practice/access");
      setAccessInfo(accessRes.data);

      if (accessRes.data.has_access) {
        const [todayRes, historyRes] = await Promise.all([
          api.get("/practice/today"),
          api.get("/practice/history"),
        ]);
        setTodayTest(todayRes.data);
        setHistory(historyRes.data || []);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  const handleRequestAccess = async () => {
    if (!accessReason.trim()) {
      setMessage("Please provide a reason for the request");
      return;
    }
    setRequestingAccess(true);
    try {
      const res = await api.post("/practice/request-access", {
        reason: accessReason,
        requested_days: accessDays,
        requested_tests_per_day: requestedTestsPerDay,
      });
      setMessage(res.data.message);
      setAccessInfo({
        has_access: false,
        expires_at: null,
        pending_request: true,
        requested_tests_per_day: requestedTestsPerDay,
        tests_per_day_granted: null,
      });
      setShowAccessForm(false);
      await loadData();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to request access");
    } finally {
      setRequestingAccess(false);
    }
  };

  const handleCreate = async () => {
    if (!jobTitle.trim()) {
      setMessage("Job title is required");
      return;
    }
    setCreating(true);
    setMessage("");
    try {
      const formData = new FormData();
      formData.append("job_title", jobTitle);
      formData.append("difficulty", difficulty);
      formData.append("topics", topics);
      formData.append("job_description", jobDescription);
      formData.append("question_count", String(questionCount));
      if (resumeFile) {
        formData.append("resume", resumeFile);
      }
      const res = await api.post("/practice/create", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setTodayTest(res.data);
      setView("home");
      setMessage("Practice test is being generated...");
      // Refresh history/counts
      await loadData();
    } catch (err: unknown) {
      console.error(err);
      setMessage(extractError(err, "Failed to create test"));
    } finally {
      setCreating(false);
    }
  };

  const handleStartTest = async () => {
    if (!todayTest) return;
    try {
      await api.post(`/practice/${todayTest.id}/start`);
      const res = await api.get(`/practice/${todayTest.id}`);
      setTestDetail({ id: res.data.id, questions: res.data.questions });
      setAnswers({});
      setCurrentQ(0);
      setView("test");
      setTodayTest({ ...todayTest, status: "in_progress" });
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to start test");
    }
  };

  const handleSubmitTest = async () => {
    if (!testDetail || submitLockRef.current) return;
    submitLockRef.current = true;
    setSubmitting(true);
    try {
      const answerPayload = testDetail.questions.map((q) => ({
        question_id: q.id,
        answer: answers[q.id] || "",
      }));
      const res = await api.post(`/practice/${testDetail.id}/submit`, { answers: answerPayload });
      setMessage(res.data.message);
      setView("home");
      loadData();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to submit test");
    } finally {
      submitLockRef.current = false;
      setSubmitting(false);
    }
  };

  const handleViewResult = async (testId: string) => {
    try {
      const res = await api.get(`/practice/${testId}/result`);
      setResultData({ score: res.data.score, questions: res.data.questions });
      setResultTestId(testId);
      setView("result");
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to load results");
    }
  };

  const handleExport = async (testId: string) => {
    try {
      const res = await api.get(`/practice/${testId}/export`, { responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", `practice_test_result.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch {
      setMessage("Failed to export");
    }
  };

  const setMcqAnswer = (questionId: string, optionText: string, isMulti: boolean) => {
    setAnswers((prev) => {
      if (!isMulti) {
        return { ...prev, [questionId]: optionText };
      }
      const current = prev[questionId] || "";
      const parts = current ? current.split("|||") : [];
      if (parts.includes(optionText)) {
        return { ...prev, [questionId]: parts.filter((p) => p !== optionText).join("|||") };
      }
      return { ...prev, [questionId]: [...parts, optionText].join("|||") };
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-3 border-blue-600 border-t-transparent rounded-full" />
      </div>
    );
  }


  // ---------- ACCESS GATE ---------- //
  if (!accessInfo?.has_access && view !== "result") {
    return (
      <div className="space-y-6">
        <Toast message={message} onClose={() => setMessage("")} />

        <div className={`${card} p-8 text-center`}>
          <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-100 flex items-center justify-center">
            <svg className="w-8 h-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-gray-900 mb-2">Practice Test Access Required</h2>
          <p className="text-sm text-gray-500 mb-6 max-w-md mx-auto">
            Practice tests are available on request. Submit an access request and an admin will approve it for a limited duration (up to 30 days).
          </p>

          {accessInfo?.pending_request ? (
            <div className="inline-flex items-center gap-2 px-4 py-2.5 bg-yellow-50 text-yellow-700 rounded-lg text-sm font-medium">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Your access request is pending admin approval
            </div>
          ) : !showAccessForm ? (
            <button
              onClick={() => setShowAccessForm(true)}
              className="px-6 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 cursor-pointer"
            >
              Request Practice Access
            </button>
          ) : (
            <div className="max-w-md mx-auto text-left mt-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Reason for access * (max 200 characters)</label>
                <textarea
                  value={accessReason}
                  onChange={(e) => setAccessReason(e.target.value)}
                  placeholder="e.g. Preparing for upcoming interview, skill improvement..."
                  rows={3}
                  maxLength={200}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none resize-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Duration requested (days)</label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min={1}
                    max={30}
                    value={accessDays}
                    onChange={(e) => setAccessDays(Number(e.target.value))}
                    className="flex-1"
                  />
                  <span className="text-sm font-medium text-gray-900 w-16 text-center">{accessDays} days</span>
                </div>
                <p className="text-xs text-gray-500 mt-1">Admin may adjust this when approving (max 30 days)</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Requested tests per day</label>
                <div className="flex items-center gap-3">
                  <input
                    type="number"
                    min={1}
                    max={3}
                    value={requestedTestsPerDay}
                    onChange={(e) => setRequestedTestsPerDay(Math.min(3, Math.max(1, Number(e.target.value))))}
                    className="w-20 px-2 py-1 border border-gray-300 rounded text-sm text-center"
                  />
                  <span className="text-xs text-gray-500">(max 3)</span>
                </div>
                <p className="text-xs text-gray-500 mt-1">Admin may adjust this when approving</p>
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  onClick={handleRequestAccess}
                  disabled={requestingAccess}
                  className="flex-1 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 cursor-pointer"
                >
                  {requestingAccess ? "Submitting..." : "Submit Request"}
                </button>
                <button
                  onClick={() => setShowAccessForm(false)}
                  className="px-4 py-2.5 border border-gray-300 text-sm font-medium rounded-lg hover:bg-gray-50 cursor-pointer"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Still show history if any */}
        {history.length > 0 && (
          <div className={`${card} overflow-hidden`}>
            <div className="px-6 py-4 border-b border-gray-200">
              <h2 className="text-base font-semibold">Past Practice Tests</h2>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="text-left px-5 py-3 font-medium text-gray-500">Date</th>
                  <th className="text-left px-5 py-3 font-medium text-gray-500">Job Title</th>
                  <th className="text-left px-5 py-3 font-medium text-gray-500">Score</th>
                  <th className="text-left px-5 py-3 font-medium text-gray-500">Actions</th>
                </tr>
              </thead>
              <tbody>
                {history.filter(t => t.status === "completed").map((t) => (
                  <tr key={t.id} className="border-b border-gray-100 last:border-0">
                    <td className="px-5 py-3 text-gray-600">{new Date(t.created_at).toLocaleDateString()}</td>
                    <td className="px-5 py-3 font-medium">{t.job_title}</td>
                    <td className="px-5 py-3">
                      {t.score !== null ? <span className="font-medium">{t.score}%</span> : "—"}
                    </td>
                    <td className="px-5 py-3">
                      <button
                        onClick={() => handleViewResult(t.id)}
                        className="text-blue-600 hover:text-blue-700 text-xs font-medium cursor-pointer mr-2"
                      >
                        View
                      </button>
                      <button
                        onClick={() => handleExport(t.id)}
                        className="text-green-600 hover:text-green-700 text-xs font-medium cursor-pointer"
                      >
                        Export
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    );
  }

  // ---------- TEST VIEW ---------- //
  if (view === "test" && testDetail) {
    const q = testDetail.questions[currentQ];
    const totalQ = testDetail.questions.length;
    const answeredCount = Object.keys(answers).filter((k) => answers[k]).length;

    return (
      <div className="space-y-6">
        {/* Progress bar */}
        <div className={`${card} p-5`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">
              Question {currentQ + 1} of {totalQ}
            </span>
            <span className="text-sm text-gray-500">{answeredCount}/{totalQ} answered</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-600 h-2 rounded-full transition-all"
              style={{ width: `${((currentQ + 1) / totalQ) * 100}%` }}
            />
          </div>
        </div>

        {/* Question */}
        <div className={`${card} p-6`}>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-blue-50 text-blue-700">{q.type.replace("_", " ").toUpperCase()}</span>
            {q.topic && <span className="text-xs text-gray-500">{q.topic}</span>}
          </div>
          <p className="text-base font-medium text-gray-900 mb-5">{q.question}</p>

          {/* MCQ options */}
          {q.options && (
            <div className="space-y-2">
              {q.options.map((opt, idx) => {
                const selected = q.type === "multi_mcq"
                  ? (answers[q.id] || "").split("|||").includes(opt.text)
                  : answers[q.id] === opt.text;
                return (
                  <button
                    key={idx}
                    onClick={() => setMcqAnswer(q.id, opt.text, q.type === "multi_mcq")}
                    className={`w-full text-left px-4 py-3 rounded-lg border text-sm transition-colors cursor-pointer ${
                      selected
                        ? "border-blue-500 bg-blue-50 text-blue-900"
                        : "border-gray-200 hover:border-gray-300 hover:bg-gray-50"
                    }`}
                  >
                    <span className="font-medium mr-2">{String.fromCharCode(65 + idx)}.</span>
                    {opt.text}
                  </button>
                );
              })}
              {q.type === "multi_mcq" && (
                <p className="text-xs text-gray-500 mt-1">Select all that apply</p>
              )}
            </div>
          )}

          {/* Text answer */}
          {q.type === "text" && (
            <textarea
              value={answers[q.id] || ""}
              onChange={(e) => setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))}
              rows={5}
              placeholder="Type your answer here..."
              className="w-full px-4 py-3 border border-gray-200 rounded-lg text-sm focus:border-blue-500 focus:outline-none resize-none"
            />
          )}
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between">
          <button
            onClick={() => setCurrentQ((p) => Math.max(0, p - 1))}
            disabled={currentQ === 0}
            className="px-4 py-2 text-sm font-medium border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 cursor-pointer"
          >
            Previous
          </button>

          <div className="flex gap-1 flex-wrap max-w-md justify-center">
            {testDetail.questions.map((_, i) => (
              <button
                key={i}
                onClick={() => setCurrentQ(i)}
                className={`w-7 h-7 rounded text-xs font-medium cursor-pointer ${
                  i === currentQ
                    ? "bg-blue-600 text-white"
                    : answers[testDetail.questions[i].id]
                    ? "bg-green-100 text-green-800 border border-green-300"
                    : "bg-gray-100 text-gray-600 border border-gray-200"
                }`}
              >
                {i + 1}
              </button>
            ))}
          </div>

          {currentQ < totalQ - 1 ? (
            <button
              onClick={() => setCurrentQ((p) => Math.min(totalQ - 1, p + 1))}
              className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer"
            >
              Next
            </button>
          ) : (
            <button
              onClick={handleSubmitTest}
              disabled={submitting}
              className="px-5 py-2 text-sm font-medium bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 cursor-pointer"
            >
              {submitting ? "Submitting..." : "Submit Test"}
            </button>
          )}
        </div>
      </div>
    );
  }

  // ---------- RESULT VIEW ---------- //
  if (view === "result" && resultData) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <button
            onClick={() => { setView("home"); setResultData(null); }}
            className="text-sm text-blue-600 hover:text-blue-700 font-medium cursor-pointer"
          >
            ← Back to Practice
          </button>
          {resultTestId && (
            <button
              onClick={() => handleExport(resultTestId)}
              className="px-4 py-2 text-sm font-medium bg-green-600 text-white rounded-lg hover:bg-green-700 cursor-pointer"
            >
              Export as Excel
            </button>
          )}
        </div>

        <div className={`${card} p-6 text-center`}>
          <p className="text-sm text-gray-600 mb-1">Your Score</p>
          <p className={`text-4xl font-bold ${
            (resultData.score || 0) >= 70 ? "text-green-600" :
            (resultData.score || 0) >= 40 ? "text-yellow-600" : "text-red-600"
          }`}>
            {resultData.score !== null ? `${resultData.score}%` : "—"}
          </p>
          <p className="text-sm text-gray-500 mt-1">{resultData.questions.length} questions</p>
        </div>

        <div className="space-y-4">
          {resultData.questions.map((q) => (
            <div key={q.position} className={`${card} p-5`}>
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium w-6 h-6 rounded-full flex items-center justify-center bg-gray-100">{q.position}</span>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700">{q.type.replace("_", " ")}</span>
                  {q.topic && <span className="text-xs text-gray-500">{q.topic}</span>}
                </div>
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                  q.score === 1 ? "bg-green-50 text-green-700" :
                  q.score && q.score > 0 ? "bg-yellow-50 text-yellow-700" : "bg-red-50 text-red-700"
                }`}>
                  {q.feedback || "—"}
                </span>
              </div>
              <p className="text-sm font-medium text-gray-900 mb-3">{q.question}</p>

              {q.options && (
                <div className="space-y-1 mb-3">
                  {q.options.map((opt, idx) => {
                    const isCorrect = opt.is_correct;
                    const isUserAnswer = q.user_answer?.split("|||").includes(opt.text);
                    return (
                      <div
                        key={idx}
                        className={`px-3 py-2 rounded text-xs ${
                          isCorrect ? "bg-green-50 border border-green-200" :
                          isUserAnswer ? "bg-red-50 border border-red-200" :
                          "bg-gray-50 border border-gray-100"
                        }`}
                      >
                        <span className="font-medium mr-1">{String.fromCharCode(65 + idx)}.</span>
                        {opt.text}
                        {isCorrect && <span className="ml-2 text-green-600">✓</span>}
                        {isUserAnswer && !isCorrect && <span className="ml-2 text-red-600">✗</span>}
                      </div>
                    );
                  })}
                </div>
              )}

              {q.type === "text" && (
                <div className="space-y-2 text-xs">
                  <div className="bg-gray-50 border border-gray-200 rounded p-3">
                    <p className="font-medium text-gray-700 mb-1">Your Answer:</p>
                    <p className="text-gray-600">{q.user_answer || "(no answer)"}</p>
                  </div>
                  {q.correct_answer && (
                    <div className="bg-green-50 border border-green-200 rounded p-3">
                      <p className="font-medium text-green-700 mb-1">Reference Answer:</p>
                      <p className="text-green-800">{q.correct_answer}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ---------- CREATE VIEW ---------- //
  if (view === "create") {
    return (
      <div className="space-y-6">
        <button
          onClick={() => setView("home")}
          className="text-sm text-blue-600 hover:text-blue-700 font-medium cursor-pointer"
        >
          ← Back
        </button>

        <div className={`${card} p-6`}>
          <h2 className="text-lg font-semibold mb-5">Create Practice Test</h2>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Job Title *</label>
              <input
                type="text"
                value={jobTitle}
                onChange={(e) => setJobTitle(e.target.value)}
                placeholder="e.g. Senior Software Engineer"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Job Description</label>
              <textarea
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
                placeholder="Paste the job description here..."
                rows={4}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none resize-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Topics</label>
              <input
                type="text"
                value={topics}
                onChange={(e) => setTopics(e.target.value)}
                placeholder="e.g. Python, System Design, SQL (comma-separated)"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Difficulty</label>
                <select
                  value={difficulty}
                  onChange={(e) => setDifficulty(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none cursor-pointer"
                >
                  <option value="easy">Easy</option>
                  <option value="medium">Medium</option>
                  <option value="hard">Hard</option>
                  <option value="mixed">Mixed (All Levels)</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Question Count (10-30)</label>
                <input
                  type="number"
                  min={10}
                  max={30}
                  value={questionCount}
                  onChange={(e) => setQuestionCount(Math.min(30, Math.max(10, Number(e.target.value))))}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Upload Resume (optional)</label>
              <div className="border-2 border-dashed border-gray-300 rounded-lg p-4 text-center">
                <input
                  type="file"
                  accept=".pdf,.docx,.txt"
                  onChange={(e) => setResumeFile(e.target.files?.[0] || null)}
                  className="text-sm text-gray-600"
                />
                <p className="text-xs text-gray-500 mt-1">PDF, DOCX, or TXT (max 5 MB)</p>
              </div>
            </div>

            {/* Inline errors converted to toast */}

            <button
              onClick={handleCreate}
              disabled={creating}
              className="w-full py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 cursor-pointer"
            >
              {creating ? "Creating..." : "Generate Practice Test"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ---------- HOME VIEW ---------- //
  return (
    <div className="space-y-6">
      <Toast message={message} onClose={() => setMessage("")} />

      {/* Access Expiry Banner */}
      {accessInfo?.has_access && accessInfo.expires_at && (
        <div className="flex items-center justify-between bg-green-50 text-green-700 px-4 py-3 rounded-lg text-sm">
          <span>
            Practice access active — expires {new Date(accessInfo.expires_at).toLocaleDateString()}
          </span>
        </div>
      )}

      {/* Today's Test Card */}
      <div className={`${card} p-6`}>
        <h2 className="text-base font-semibold mb-4">Today's Practice Test</h2>

        {!todayTest ? (
          <div className="text-center py-6">
            <p className="text-sm text-gray-500 mb-4">No practice test created today. Create one to get started!</p>
            <button
              onClick={() => setView("create")}
              className="px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 cursor-pointer"
            >
              Create Practice Test
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium text-gray-900">{todayTest.job_title}</p>
                <p className="text-xs text-gray-500">
                  {todayTest.topics || "General"} · {todayTest.difficulty} · {todayTest.question_count} questions
                </p>
              </div>
              <span className={`text-xs font-medium px-2.5 py-1 rounded-full ${
                todayTest.status === "generating" ? "bg-yellow-50 text-yellow-700" :
                todayTest.status === "ready" ? "bg-green-50 text-green-700" :
                todayTest.status === "in_progress" ? "bg-blue-50 text-blue-700" :
                todayTest.status === "completed" ? "bg-purple-50 text-purple-700" :
                "bg-red-50 text-red-700"
              }`}>
                {todayTest.status === "generating" ? "Generating..." :
                 todayTest.status === "ready" ? "Ready" :
                 todayTest.status === "in_progress" ? "In Progress" :
                 todayTest.status === "completed" ? `Completed (${todayTest.score}%)` :
                 "Failed"}
              </span>
            </div>

            <div className="flex gap-2">
              {(todayTest.status === "ready" || todayTest.status === "in_progress") && (
                <button
                  onClick={handleStartTest}
                  className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 cursor-pointer"
                >
                  {todayTest.status === "in_progress" ? "Resume Test" : "Start Test"}
                </button>
              )}
              {todayTest.status === "completed" && (
                <>
                  <button
                    onClick={() => handleViewResult(todayTest.id)}
                    className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 cursor-pointer"
                  >
                    View Results
                  </button>
                  <button
                    onClick={() => handleExport(todayTest.id)}
                    className="px-4 py-2 border border-gray-300 text-sm font-medium rounded-lg hover:bg-gray-50 cursor-pointer"
                  >
                    Export Excel
                  </button>
                </>
              )}
              {todayTest.status === "failed" && (
                <p className="text-sm text-red-600">Generation failed. Please try again tomorrow.</p>
              )}
              {canCreateMore && (
                <button
                  onClick={() => setView("create")}
                  className="px-4 py-2 text-sm font-medium border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer"
                >
                  Create Another Test
                </button>
              )}
            </div>
            {accessInfo?.has_access && (
              <p className="text-xs text-gray-500 mt-2">You have used {todayCount} of {maxPerDay} tests today.</p>
            )}
          </div>
        )}
      </div>

      {/* History */}
      <div className={`${card} overflow-hidden`}>
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-base font-semibold">Practice History</h2>
        </div>

        {history.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-gray-500">No practice tests yet.</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50">
                <th className="text-left px-5 py-3 font-medium text-gray-500">Date</th>
                <th className="text-left px-5 py-3 font-medium text-gray-500">Job Title</th>
                <th className="text-left px-5 py-3 font-medium text-gray-500">Topics</th>
                <th className="text-left px-5 py-3 font-medium text-gray-500">Difficulty</th>
                <th className="text-left px-5 py-3 font-medium text-gray-500">Score</th>
                <th className="text-left px-5 py-3 font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody>
              {history.map((t) => (
                <tr key={t.id} className="border-b border-gray-100 last:border-0 hover:bg-gray-50/50">
                  <td className="px-5 py-3 text-gray-600">{new Date(t.created_at).toLocaleDateString()}</td>
                  <td className="px-5 py-3 font-medium">{t.job_title}</td>
                  <td className="px-5 py-3 text-gray-600">{t.topics || "General"}</td>
                  <td className="px-5 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      t.difficulty === "hard" ? "bg-red-50 text-red-700" :
                      t.difficulty === "easy" ? "bg-green-50 text-green-700" :
                      "bg-yellow-50 text-yellow-700"
                    }`}>
                      {t.difficulty}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    {t.score !== null ? (
                      <span className={`font-medium ${
                        t.score >= 70 ? "text-green-600" : t.score >= 40 ? "text-yellow-600" : "text-red-600"
                      }`}>
                        {t.score}%
                      </span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-5 py-3">
                    {t.status === "completed" && (
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleViewResult(t.id)}
                          className="text-blue-600 hover:text-blue-700 text-xs font-medium cursor-pointer"
                        >
                          View
                        </button>
                        <button
                          onClick={() => handleExport(t.id)}
                          className="text-green-600 hover:text-green-700 text-xs font-medium cursor-pointer"
                        >
                          Export
                        </button>
                      </div>
                    )}
                    {t.status === "generating" && <span className="text-xs text-yellow-600">Generating...</span>}
                    {t.status === "failed" && <span className="text-xs text-red-600">Failed</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
