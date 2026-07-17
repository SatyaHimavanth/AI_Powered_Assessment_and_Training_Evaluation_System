import { useCallback, useEffect, useRef, useState } from "react";
import api from "../../api";
import CodingEditor from "../../components/CodingEditor";

interface Option {
  id: string;
  text: string;
}

interface TestCaseSample {
  id: string;
  input_data: string;
  expected_output: string;
}

interface ExamQuestion {
  id: string;
  type: string;
  question: string;
  difficulty: string;
  section_name: string;
  options: Option[];
  test_cases: TestCaseSample[];
  default_code: string | null;
}

interface ExamData {
  attempt_id: string;
  assessment_title: string;
  duration: number;
  total_questions: number;
  questions: ExamQuestion[];
  saved_answers?: { question_id: string; answer: string }[];
  time_elapsed_seconds?: number;
  tab_violations?: number;
}

interface Props {
  assessmentId: string;
  onExit: () => void;
}

type Phase = "speed-test" | "exam" | "submitted" | "aborted";

function SignalBars({ strength }: { strength: number }) {
  // strength: 0-3
  return (
    <div className="flex items-end gap-0.5 h-4">
      <div className={`w-1 h-1.5 rounded-sm ${strength >= 1 ? "bg-green-500" : "bg-gray-300"}`} />
      <div className={`w-1 h-2.5 rounded-sm ${strength >= 2 ? "bg-green-500" : "bg-gray-300"}`} />
      <div className={`w-1 h-3.5 rounded-sm ${strength >= 3 ? "bg-green-500" : "bg-gray-300"}`} />
    </div>
  );
}

export default function ExamPage({ assessmentId, onExit }: Props) {
  const [phase, setPhase] = useState<Phase>("speed-test");
  const [speedMbps, setSpeedMbps] = useState<number | null>(null);
  const [speedTesting, setSpeedTesting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [examData, setExamData] = useState<ExamData | null>(null);
  const [currentQ, setCurrentQ] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [timeLeft, setTimeLeft] = useState(0);
  const [violations, setViolations] = useState(0);
  const [escapeAttempts, setEscapeAttempts] = useState(0);
  const [showWarning, setShowWarning] = useState(false);
  const [warningType, setWarningType] = useState<'violation' | 'escape'>('violation');
  const [submitting, setSubmitting] = useState(false);
  const [signalStrength, setSignalStrength] = useState(3);
  const [error, setError] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showSubmitConfirm, setShowSubmitConfirm] = useState(false);
  const [showAutoSubmitModal, setShowAutoSubmitModal] = useState(false);

  const violationsRef = useRef(0);
  const escapeAttemptsRef = useRef(0);
  const examDataRef = useRef<ExamData | null>(null);
  const answersRef = useRef<Record<string, string>>({});
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const savingQueueRef = useRef<Set<string>>(new Set());
  const internalClipboardRef = useRef<string>("");

  // Keep refs in sync
  useEffect(() => { violationsRef.current = violations; }, [violations]);
  useEffect(() => { escapeAttemptsRef.current = escapeAttempts; }, [escapeAttempts]);
  useEffect(() => { examDataRef.current = examData; }, [examData]);
  useEffect(() => { answersRef.current = answers; }, [answers]);

  // ---- Network Speed Test ----
  const runSpeedTest = async () => {
    setSpeedTesting(true);
    setSpeedMbps(null);
    try {
      // Download a known-size payload from the API to estimate real throughput.
      // The endpoint returns random bytes (default 500 KB) to prevent
      // transparent compression from inflating the measured speed.
      const apiUrl = import.meta.env.VITE_API_URL || "";
      const testUrl = `${apiUrl}/speed-test?size=524288&_t=${Date.now()}`;
      const startTime = performance.now();
      const response = await fetch(testUrl, { cache: "no-store" });
      const blob = await response.blob();
      const endTime = performance.now();
      const durationSec = (endTime - startTime) / 1000;
      if (durationSec <= 0 || blob.size === 0) {
        setSpeedMbps(0);
        return;
      }
      const sizeBytes = blob.size;
      const speedBps = (sizeBytes * 8) / durationSec;
      const mbps = speedBps / 1_000_000;
      setSpeedMbps(Math.round(mbps * 100) / 100);
    } catch {
      // If fetch fails, network might be down
      setSpeedMbps(0);
    } finally {
      setSpeedTesting(false);
    }
  };

  useEffect(() => {
    const t = setTimeout(() => { runSpeedTest(); }, 0);
    return () => clearTimeout(t);
  }, []);

  // ---- Signal Strength Monitor ----
  useEffect(() => {
    if (phase !== "exam") return;
    const checkConnection = () => {
      if (!navigator.onLine) {
        setSignalStrength(0);
        return;
      }
      // Use Network Information API if available
      const conn = (navigator as unknown as { connection?: { downlink?: number } }).connection;
      if (conn && typeof conn.downlink === "number") {
        const dl = conn.downlink || 10; // Mbps
        if (dl >= 5) setSignalStrength(3);
        else if (dl >= 1) setSignalStrength(2);
        else setSignalStrength(1);
      } else {
        setSignalStrength(navigator.onLine ? 3 : 0);
      }
    };
    checkConnection();
    const interval = setInterval(checkConnection, 3000);
    return () => clearInterval(interval);
  }, [phase]);

  // ---- Start Exam ----
  const startExam = async () => {
    if (starting) return;
    setStarting(true);
    try {
      const res = await api.post(`/user/assessments/start/${assessmentId}`);
      const data: ExamData = res.data;
      setExamData(data);

      // Restore saved answers if resuming
      if (data.saved_answers && data.saved_answers.length > 0) {
        const restored: Record<string, string> = {};
        data.saved_answers.forEach((sa) => {
          restored[sa.question_id] = sa.answer;
        });
        setAnswers(restored);
      }

      // Adjust timer for elapsed time on resume
      const totalSeconds = data.duration * 60;
      const elapsed = data.time_elapsed_seconds || 0;
      const remaining = Math.max(0, totalSeconds - elapsed);
      setTimeLeft(remaining);

      // Restore violations count on resume
      if (data.tab_violations) {
        setViolations(data.tab_violations);
      }

      setPhase("exam");
      // Request fullscreen
      try {
        await document.documentElement.requestFullscreen();
      } catch {
        // May not be supported
      }
    } catch (err: unknown) {
      console.error(err);
      setError("Failed to start assessment");
    } finally {
      setStarting(false);
    }
  };

  // ---- Timer ----
  // helpers: stable refs + fullscreen exit
  const submittingRef = useRef(false);

  const exitFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    }
  }, []);

  const handleSubmit = useCallback(async () => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    if (timerRef.current) clearInterval(timerRef.current);

    const data = examDataRef.current;
    if (!data) { submittingRef.current = false; setSubmitting(false); return; }

    const answerList = data.questions.map((q) => ({
      question_id: q.id,
      answer: answersRef.current[q.id] || "",
    }));

    try {
      await api.post(`/user/assessments/submit/${data.attempt_id}`, { answers: answerList });
      setPhase("submitted");
    } catch {
      setPhase("submitted");
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }

    exitFullscreen();
  }, [exitFullscreen]);

  const handleAbort = useCallback(async () => {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setSubmitting(true);
    if (timerRef.current) clearInterval(timerRef.current);

    const data = examDataRef.current;
    if (!data) { setPhase("aborted"); submittingRef.current = false; setSubmitting(false); return; }

    const answerList = data.questions.map((q) => ({
      question_id: q.id,
      answer: answersRef.current[q.id] || "",
    }));

    try {
      await api.post(`/user/assessments/abort/${data.attempt_id}`, { answers: answerList });
    } catch { /* ignore */ }

    setPhase("aborted");
    exitFullscreen();
    submittingRef.current = false;
    setSubmitting(false);
  }, [exitFullscreen]);

  // ---- Timer ----
  useEffect(() => {
    if (phase !== "exam") return;
    timerRef.current = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          if (timerRef.current) clearInterval(timerRef.current);
          // Auto-submit on time up
          setShowAutoSubmitModal(true);
          void handleSubmit();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [phase, handleSubmit]);

  // ---- Fullscreen / Tab Violations ----
  const saveViolationsToServer = useCallback((count: number) => {
    const data = examDataRef.current;
    if (!data) return;
    api.post(`/user/assessments/save-violations?attempt_id=${data.attempt_id}&violations=${count}`)
      .catch(() => { /* silent */ });
  }, []);

  const handleViolation = useCallback(() => {
    if (phase !== "exam") return;
    const newCount = violationsRef.current + 1;
    setViolations(newCount);
    setWarningType('violation');
    saveViolationsToServer(newCount);

    if (newCount > 5) {
      // Abort exam
      handleAbort();
    } else {
      setShowWarning(true);
      // Re-enter fullscreen
      try {
        document.documentElement.requestFullscreen();
      } catch { /* ignore */ }
    }
  }, [phase, handleAbort, saveViolationsToServer]);

  // ---- Escape Key Handler ----
  const handleEscapeAttempt = useCallback(() => {
    if (phase !== "exam") return;
    const newCount = escapeAttemptsRef.current + 1;
    setEscapeAttempts(newCount);
    setWarningType('escape');
    saveViolationsToServer(violationsRef.current + newCount);

    if (newCount >= 5) {
      // Auto-abort after 5 escape attempts
      handleAbort();
    } else {
      setShowWarning(true);
      // Immediately re-enter fullscreen (in case browser allowed ESC to exit)
      setTimeout(() => {
        try {
          if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen();
          }
        } catch { /* ignore */ }
      }, 50);
    }
  }, [phase, handleAbort, saveViolationsToServer]);

  useEffect(() => {
    if (phase !== "exam") return;

    const onVisibilityChange = () => {
      if (document.hidden) handleViolation();
    };
    const onFullscreenChange = () => {
      // If fullscreen is exited during exam, immediately re-enter
      if (!document.fullscreenElement && phase === "exam") {
        // Try to re-enter fullscreen immediately
        setTimeout(() => {
          try {
            if (!document.fullscreenElement) {
              document.documentElement.requestFullscreen();
            }
          } catch { /* ignore */ }
        }, 50);
        
        // Only count as violation if not an escape attempt
        handleViolation();
      }
    };
    const onBlur = () => {
      // Delay to check if focus moved within the page (e.g., Tab in code editor)
      setTimeout(() => {
        if (document.hasFocus()) return; // Focus is still in-page
        handleViolation();
      }, 100);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      // Allow Tab key for code editor indentation
      if (e.key === "Tab") return;
      // Detect common DevTools key combos and F12
      const key = (e.key || "").toLowerCase();
      if (
        e.key === "F12" ||
        (e.ctrlKey && e.shiftKey && (key === "i" || key === "j")) ||
        ((e.metaKey || e.ctrlKey) && e.altKey && key === "i")
      ) {
        e.preventDefault();
        // Immediately abort the exam if DevTools is opened
        handleAbort();
        return;
      }

      if (e.key === "Escape" || e.keyCode === 27) {
        e.preventDefault();
        handleEscapeAttempt();
      }
    };

    document.addEventListener("visibilitychange", onVisibilityChange);
    document.addEventListener("fullscreenchange", onFullscreenChange);
    window.addEventListener("blur", onBlur);
    document.addEventListener("keydown", onKeyDown);

    // Prevent page refresh/close without warning
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);

    // ---- Clipboard isolation: internal copy/paste only ----
    const onCopy = (e: ClipboardEvent) => {
      const selection = window.getSelection()?.toString() || "";
      internalClipboardRef.current = selection;
      // Prevent text from reaching system clipboard
      e.preventDefault();
      e.clipboardData?.setData("text/plain", "");
    };

    const onCut = (e: ClipboardEvent) => {
      const selection = window.getSelection()?.toString() || "";
      internalClipboardRef.current = selection;
      // Remove selected text from the active element
      const el = document.activeElement as HTMLInputElement | HTMLTextAreaElement;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) {
        const start = el.selectionStart ?? 0;
        const end = el.selectionEnd ?? 0;
        const val = el.value;
        // Simulate native input for React controlled components
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
          "value"
        )?.set;
        nativeInputValueSetter?.call(el, val.slice(0, start) + val.slice(end));
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.setSelectionRange(start, start);
      }
      e.preventDefault();
      e.clipboardData?.setData("text/plain", "");
    };

    const onPaste = (e: ClipboardEvent) => {
      e.preventDefault();
      // Only paste from internal clipboard
      const text = internalClipboardRef.current;
      if (!text) return;
      const el = document.activeElement as HTMLInputElement | HTMLTextAreaElement;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) {
        const start = el.selectionStart ?? 0;
        const end = el.selectionEnd ?? 0;
        const val = el.value;
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
          "value"
        )?.set;
        nativeInputValueSetter?.call(el, val.slice(0, start) + text + val.slice(end));
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.setSelectionRange(start + text.length, start + text.length);
      }
    };

    document.addEventListener("copy", onCopy);
    document.addEventListener("cut", onCut);
    document.addEventListener("paste", onPaste);

    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange);
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("copy", onCopy);
      document.removeEventListener("cut", onCut);
      document.removeEventListener("paste", onPaste);
      // cleanup (no size-based DevTools interval to clear)
    };
  }, [phase, handleViolation, handleEscapeAttempt]);



  // ---- Answer handling with auto-save ----
  const saveAnswerToServer = useCallback((questionId: string, value: string) => {
    const data = examDataRef.current;
    if (!data) return;
    // Fire and forget - don't block the UI
    api.post(`/user/assessments/save-answer?attempt_id=${data.attempt_id}`, {
      question_id: questionId,
      answer: value,
    }).catch(() => { /* silent fail - will be saved on final submit */ });
  }, []);

  const setAnswer = (questionId: string, value: string) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }));

    // Debounced auto-save: save after 500ms of inactivity per question
    savingQueueRef.current.add(questionId);
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(() => {
      savingQueueRef.current.forEach((qId) => {
        saveAnswerToServer(qId, answersRef.current[qId] || "");
      });
      savingQueueRef.current.clear();
    }, 500);
  };

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  };

  const goToNextQuestionInSection = () => {
    if (!examData) return;
    const currentSection = examData.questions[currentQ]?.section_name || "General";

    // 1) Prefer next question in same section.
    for (let i = currentQ + 1; i < examData.questions.length; i++) {
      const section = examData.questions[i]?.section_name || "General";
      if (section === currentSection) {
        setCurrentQ(i);
        return;
      }
    }

    // 2) If same section is complete, move to the first unseen question in next sections.
    if (currentQ < examData.questions.length - 1) {
      setCurrentQ(currentQ + 1);
    }
  };

  // ---- SPEED TEST PHASE ----
  if (phase === "speed-test") {
    return (
      <div className="min-h-screen bg-[var(--color-bg)] flex items-center justify-center p-8">
        <div className="bg-white rounded-[var(--radius)] shadow-[var(--shadow)] border border-[var(--color-border)] p-8 max-w-md w-full text-center">
          <h2 className="text-lg font-semibold mb-4">Network Speed Test</h2>

          {speedTesting ? (
            <div className="py-8">
              <div className="w-10 h-10 border-4 border-blue-200 border-t-[var(--color-primary)] rounded-full animate-spin mx-auto mb-4" />
              <p className="text-sm text-[var(--color-text-secondary)]">Testing your connection...</p>
            </div>
          ) : speedMbps !== null ? (
            <div className="py-6">
              <p className="text-4xl font-bold mb-2">{speedMbps.toFixed(1)} Mbps</p>
              {speedMbps < 1 ? (
                <div className="bg-red-50 border border-red-200 rounded-[var(--radius-sm)] p-3 mt-4">
                  <p className="text-sm text-[var(--color-danger)] font-medium">
                    Your connection speed is below the recommended 1 Mbps.
                  </p>
                  <p className="text-xs text-[var(--color-text-secondary)] mt-1">
                    You may experience issues during the exam. Consider switching to a better network.
                  </p>
                </div>
              ) : (
                <div className="bg-green-50 border border-green-200 rounded-[var(--radius-sm)] p-3 mt-4">
                  <p className="text-sm text-[var(--color-success)] font-medium">
                    Your connection is good. You can proceed.
                  </p>
                </div>
              )}
            </div>
          ) : null}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-[var(--radius-sm)] p-3 mt-4">
              <p className="text-sm text-[var(--color-danger)]">{error}</p>
            </div>
          )}

          <div className="mt-6 space-y-3">
            <button
              onClick={startExam}
              disabled={speedTesting || starting}
              className="w-full h-10 bg-[var(--color-primary)] text-white text-sm font-medium rounded-[var(--radius-sm)] hover:bg-[var(--color-primary-hover)] disabled:opacity-50 cursor-pointer"
            >
              {starting ? "Starting..." : "Start Assessment"}
            </button>
            <button
              onClick={runSpeedTest}
              disabled={speedTesting}
              className="w-full h-10 border border-[var(--color-border)] text-sm font-medium rounded-[var(--radius-sm)] hover:bg-gray-50 cursor-pointer"
            >
              Re-test Speed
            </button>
            <button
              onClick={onExit}
              className="w-full h-10 text-sm text-[var(--color-text-secondary)] hover:text-[var(--color-text)] cursor-pointer"
            >
              Back to Dashboard
            </button>
          </div>

          <div className="mt-6 p-3 bg-amber-50 border border-amber-200 rounded-[var(--radius-sm)] text-left">
            <p className="text-xs font-medium text-amber-800 mb-1">Important:</p>
            <ul className="text-xs text-amber-700 space-y-0.5 list-disc ml-3">
              <li>The exam will open in fullscreen mode</li>
              <li>Exiting fullscreen or switching tabs will trigger a warning</li>
              <li>Pressing Escape is blocked (after 3 attempts your exam will abort)</li>
              <li>After 3 violations, the exam will be automatically aborted</li>
              <li>You cannot re-enter the exam once you leave</li>
            </ul>
          </div>
        </div>
      </div>
    );
  }

  // ---- SUBMITTED / ABORTED ----
  if (phase === "submitted" || phase === "aborted") {
    return (
      <div className="min-h-screen bg-[var(--color-bg)] flex items-center justify-center p-8">
        <div className="bg-white rounded-[var(--radius)] shadow-[var(--shadow)] border border-[var(--color-border)] p-8 max-w-md w-full text-center">
          {phase === "submitted" ? (
            <>
              <div className="w-16 h-16 rounded-full bg-green-50 text-[var(--color-success)] flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <h2 className="text-lg font-semibold mb-2">Assessment Submitted</h2>
              <p className="text-sm text-[var(--color-text-secondary)]">Your answers have been recorded successfully.</p>
            </>
          ) : (
            <>
              <div className="w-16 h-16 rounded-full bg-red-50 text-[var(--color-danger)] flex items-center justify-center mx-auto mb-4">
                <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                </svg>
              </div>
              <h2 className="text-lg font-semibold mb-2">Assessment Aborted</h2>
              <p className="text-sm text-[var(--color-text-secondary)]">
                You exceeded the maximum allowed violations. Your partial answers have been saved.
              </p>
            </>
          )}
          <button
            onClick={onExit}
            className="mt-6 h-10 px-6 bg-[var(--color-primary)] text-white text-sm font-medium rounded-[var(--radius-sm)] hover:bg-[var(--color-primary-hover)] cursor-pointer"
          >
            Back to Dashboard
          </button>
        </div>
      </div>
    );
  }

  // ---- EXAM PHASE ----
  if (!examData) return null;

  const question = examData.questions[currentQ];
  const answeredCount = Object.keys(answers).filter((k) => answers[k].trim()).length;
  const sectionOrder: string[] = [];
  const questionsBySection: Record<string, number[]> = {};

  examData.questions.forEach((q, idx) => {
    const section = q.section_name || "General";
    if (!questionsBySection[section]) {
      questionsBySection[section] = [];
      sectionOrder.push(section);
    }
    questionsBySection[section].push(idx);
  });

  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col">
      {/* Warning Modal */}
      {showWarning && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-white text-gray-900 rounded-[var(--radius)] p-6 max-w-sm w-full text-center shadow-2xl">
            <div className="w-12 h-12 rounded-full bg-red-50 text-[var(--color-danger)] flex items-center justify-center mx-auto mb-3">
              <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
              </svg>
            </div>
            {warningType === 'escape' ? (
              <>
                <h3 className="text-base font-semibold mb-1">Exit Blocked! ({escapeAttempts}/3)</h3>
                <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                  You cannot exit the exam by pressing Escape. After 3 attempts, your exam will be automatically terminated.
                </p>
              </>
            ) : (
              <>
                <h3 className="text-base font-semibold mb-1">Warning! ({violations}/5)</h3>
                <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                  Leaving the exam window is not allowed. After 5 violations your exam will be automatically terminated.
                </p>
              </>
            )}
            <button
              onClick={() => {
                setShowWarning(false);
                // Ensure fullscreen is re-entered after warning is dismissed
                setTimeout(() => {
                  try {
                    if (!document.fullscreenElement) {
                      document.documentElement.requestFullscreen();
                    }
                  } catch { /* ignore */ }
                }, 100);
              }}
              className="h-9 px-5 bg-[var(--color-primary)] text-white text-sm font-medium rounded-[var(--radius-sm)] cursor-pointer"
            >
              Continue Exam
            </button>
          </div>
        </div>
      )}

      {showSubmitConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-white text-gray-900 rounded-[var(--radius)] p-6 max-w-sm w-full text-center shadow-2xl">
            <h3 className="text-base font-semibold mb-2">Submit Assessment?</h3>
            <p className="text-sm text-[var(--color-text-secondary)] mb-5">
              Please confirm. Once submitted, you cannot re-enter this assessment.
            </p>
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={() => setShowSubmitConfirm(false)}
                className="h-9 px-4 text-sm font-medium rounded border border-[var(--color-border)] hover:bg-gray-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setShowSubmitConfirm(false);
                  handleSubmit();
                }}
                className="h-9 px-4 text-sm font-medium rounded bg-green-600 text-white hover:bg-green-500 cursor-pointer"
              >
                Yes, Submit
              </button>
            </div>
          </div>
        </div>
      )}

      {showAutoSubmitModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-white text-gray-900 rounded-[var(--radius)] p-6 max-w-sm w-full text-center shadow-2xl">
            <div className="w-10 h-10 border-4 border-blue-200 border-t-[var(--color-primary)] rounded-full animate-spin mx-auto mb-4" />
            <h3 className="text-base font-semibold mb-2">Time Is Up</h3>
            <p className="text-sm text-[var(--color-text-secondary)]">
              Your assessment is being auto-submitted.
            </p>
          </div>
        </div>
      )}

      {/* Top Bar */}
      <header className="bg-gray-800 border-b border-gray-700 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-sm font-semibold">{examData.assessment_title}</h1>
          <span className="text-xs text-gray-400">
            Q {currentQ + 1} / {examData.total_questions}
          </span>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <SignalBars strength={signalStrength} />
            <span className="text-xs text-gray-400">
              {signalStrength === 0 ? "Offline" : signalStrength === 1 ? "Weak" : signalStrength === 2 ? "Fair" : "Good"}
            </span>
          </div>
          <div className={`text-sm font-mono font-semibold px-3 py-1 rounded ${timeLeft < 60 ? "bg-red-600 animate-pulse" : timeLeft < 300 ? "bg-amber-600" : "bg-gray-700"}`}>
            {formatTime(timeLeft)}
          </div>
          <span className="text-xs text-gray-400">
            {answeredCount}/{examData.total_questions} answered
          </span>
          {violations > 0 && (
            <span className="text-xs text-red-400 font-medium">
              Tab/Window Violations: {violations}/5
            </span>
          )}
          {escapeAttempts > 0 && (
            <span className="text-xs text-orange-400 font-medium">
              Escape Attempts: {escapeAttempts}/3
            </span>
          )}
          <button
            onClick={() => setShowSubmitConfirm(true)}
            disabled={submitting}
            className="h-9 px-4 text-sm font-medium rounded bg-green-600 hover:bg-green-500 disabled:opacity-50 cursor-pointer"
          >
            {submitting ? "Submitting..." : "Submit Assessment"}
          </button>
        </div>
      </header>

      {/* Main Content */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* Question Navigation Sidebar */}
        <aside className={`${sidebarCollapsed ? "w-56" : "w-[360px]"} bg-gray-800 border-r border-gray-700 p-3 overflow-y-auto transition-all duration-200`}>
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold text-gray-300 uppercase tracking-wide">Sections</p>
            <button
              onClick={() => setSidebarCollapsed((prev) => !prev)}
              className="h-7 px-2 text-xs rounded bg-gray-700 hover:bg-gray-600 text-gray-200 cursor-pointer"
            >
              {sidebarCollapsed ? "Expand" : "Collapse"}
            </button>
          </div>

          <div className="space-y-3">
            {sectionOrder.map((section) => {
              const indices = questionsBySection[section];
              const answeredInSection = indices.filter((idx) => answers[examData.questions[idx].id]?.trim()).length;
              const isCurrentSection = indices.includes(currentQ);

              return (
                <div key={section} className={`rounded border ${isCurrentSection ? "border-blue-500" : "border-gray-700"}`}>
                  <div className={`px-3 py-2 text-xs flex items-center justify-between ${isCurrentSection ? "bg-blue-900/30" : "bg-gray-700"}`}>
                    <span className="font-medium text-gray-200 truncate pr-2">{section}</span>
                    <span className="text-gray-400 shrink-0">{answeredInSection}/{indices.length}</span>
                  </div>

                  {!sidebarCollapsed && (
                    <div className="p-2 grid grid-cols-3 gap-1.5 bg-gray-800">
                      {indices.map((idx, positionInSection) => {
                        const q = examData.questions[idx];
                        return (
                          <button
                            key={q.id}
                            onClick={() => setCurrentQ(idx)}
                            className={`h-8 flex items-center justify-center text-xs font-medium rounded cursor-pointer transition-colors ${
                              idx === currentQ
                                ? "bg-[var(--color-primary)] text-white"
                                : answers[q.id]?.trim()
                                ? "bg-green-600 text-white"
                                : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                            }`}
                          >
                            {positionInSection + 1}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </aside>

        {/* Question Area */}
        <main className="flex-1 flex overflow-hidden min-h-0">
          {question.type === "coding" ? (
            <CodingEditor
              questionId={question.id}
              questionText={question.question}
              difficulty={question.difficulty}
              sectionName={question.section_name}
              testCases={question.test_cases || []}
              defaultCode={question.default_code || ""}
              value={answers[question.id] || ""}
              onChange={(code) => setAnswer(question.id, code)}
              disablePaste={phase === "exam"}
              onPasteAttempt={() => handleViolation()}
            />
          ) : (
          <div className="flex-1 p-8 overflow-y-auto">
          <div className="max-w-3xl mx-auto">
            {/* Question Header */}
            <div className="flex items-center gap-2 mb-4">
              <span className="text-xs font-medium px-2 py-0.5 rounded bg-blue-900/40 text-blue-200">
                {question.section_name || "General"}
              </span>
              <span className="text-xs font-medium px-2 py-0.5 rounded bg-gray-700 text-gray-300">
                {question.type.replace("_", " ").toUpperCase()}
              </span>
              <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                question.difficulty === "easy" ? "bg-green-900 text-green-300" :
                question.difficulty === "medium" ? "bg-amber-900 text-amber-300" :
                "bg-red-900 text-red-300"
              }`}>
                {question.difficulty}
              </span>
            </div>

            {/* Question Text */}
            <h2 className="text-lg font-medium leading-relaxed mb-6 whitespace-pre-wrap">
              {question.question}
            </h2>

            {/* Answer Area */}
            {(question.type === "single_mcq" || question.type === "multi_mcq") && question.options.length > 0 ? (
              <div className="space-y-2">
                {question.options.map((opt) => {
                  const isSelected = question.type === "single_mcq"
                    ? answers[question.id] === opt.id
                    : (answers[question.id] || "").split(",").includes(opt.id);

                  return (
                    <label
                      key={opt.id}
                      className={`w-full flex items-start gap-3 p-4 rounded-lg border transition-colors cursor-pointer ${
                        isSelected
                          ? "border-[var(--color-primary)] bg-blue-900/30"
                          : "border-gray-700 bg-gray-800 hover:border-gray-500"
                      }`}
                    >
                      <input
                        type={question.type === "single_mcq" ? "radio" : "checkbox"}
                        name={`q-${question.id}`}
                        checked={isSelected}
                        onChange={() => {
                          if (question.type === "single_mcq") {
                            setAnswer(question.id, opt.id);
                          } else {
                            const current = (answers[question.id] || "").split(",").filter(Boolean);
                            const updated = current.includes(opt.id)
                              ? current.filter((id) => id !== opt.id)
                              : [...current, opt.id];
                            setAnswer(question.id, updated.join(","));
                          }
                        }}
                        className="mt-1 h-4 w-4 accent-blue-500"
                      />
                      <span className="text-sm leading-6">{opt.text}</span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <textarea
                value={answers[question.id] || ""}
                onChange={(e) => setAnswer(question.id, e.target.value)}
                placeholder="Type your answer here..."
                className="w-full h-48 p-4 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white placeholder:text-gray-500 resize-none focus:border-[var(--color-primary)] focus:outline-none"
              />
            )}
          </div>
          </div>
          )}
        </main>
      </div>

      {/* Bottom Bar */}
      <footer className="bg-gray-800 border-t border-gray-700 px-6 py-3 flex items-center justify-between">
        <button
          onClick={() => setCurrentQ(Math.max(0, currentQ - 1))}
          disabled={currentQ === 0}
          className="h-9 px-4 text-sm font-medium rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
        >
          Previous
        </button>
        <div className="flex gap-3">
          {currentQ < examData.questions.length - 1 ? (
            <button
              onClick={goToNextQuestionInSection}
              className="h-9 px-4 text-sm font-medium rounded bg-gray-700 hover:bg-gray-600 cursor-pointer"
            >
              Next
            </button>
          ) : null}
        </div>
      </footer>
    </div>
  );
}
