import { useCallback, useEffect, useRef, useState } from "react";
import api, { API_BASE } from "../../api";
import CodingEditor from "../../components/CodingEditor";
import { AnswerSaveQueue } from "../../answerSaveQueue";
import { assessmentDeadlineEpoch } from "../../assessmentDeadline";
import {
  clearAssessmentDraft,
  clearOtherAssessmentDrafts,
  loadAssessmentDraft,
  saveAssessmentDraft,
} from "../../assessmentOfflineDraft";

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
  assessment_end_time?: string | null;
  time_remaining_seconds?: number | null;
  total_questions: number;
  questions: ExamQuestion[];
  saved_answers?: { question_id: string; answer: string }[];
  time_elapsed_seconds?: number;
  tab_violations?: number;
}

interface Props {
  assessmentId: string;
  userKey: string;
  onExit: () => void;
}

type Phase = "speed-test" | "exam" | "submitted" | "aborted";
const OFFLINE_LOCK_AFTER_MS = 5 * 60 * 1000;

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

export default function ExamPage({ assessmentId, userKey, onExit }: Props) {
  const [phase, setPhase] = useState<Phase>("speed-test");
  const [speedMbps, setSpeedMbps] = useState<number | null>(null);
  const [speedTesting, setSpeedTesting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [examData, setExamData] = useState<ExamData | null>(null);
  const [currentQ, setCurrentQ] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [timeLeft, setTimeLeft] = useState(0);
  const [deadlineEnabled, setDeadlineEnabled] = useState(false);
  const [violations, setViolations] = useState(0);
  const [escapeAttempts, setEscapeAttempts] = useState(0);
  const [showWarning, setShowWarning] = useState(false);
  const [warningType, setWarningType] = useState<'violation' | 'escape'>('violation');
  const [submitting, setSubmitting] = useState(false);
  const [signalStrength, setSignalStrength] = useState(3);
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showSubmitConfirm, setShowSubmitConfirm] = useState(false);
  const [showAutoSubmitModal, setShowAutoSubmitModal] = useState(false);
  const [submittedWithAutosaveWarning, setSubmittedWithAutosaveWarning] = useState(false);
  const [isOffline, setIsOffline] = useState(false);
  const [offlineLocked, setOfflineLocked] = useState(false);
  const [locallyExpired, setLocallyExpired] = useState(false);
  const [pendingSubmit, setPendingSubmit] = useState(false);

  const violationsRef = useRef(0);
  const escapeAttemptsRef = useRef(0);
  const lastFocusSignalAtRef = useRef(0);
  const examDataRef = useRef<ExamData | null>(null);
  const answersRef = useRef<Record<string, string>>({});
  const timeLeftRef = useRef(0);
  const deadlineEpochRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const internalClipboardRef = useRef<string>("");
  const answerSaveQueueRef = useRef<AnswerSaveQueue | null>(null);
  const offlineSinceRef = useRef<number | null>(null);
  const pendingSubmitRef = useRef(false);
  const syncOfflineRef = useRef<(() => Promise<void>) | null>(null);
  const exitFullscreenRef = useRef<(() => void) | null>(null);

  const createAnswerSaveQueue = (attemptId: string) => new AnswerSaveQueue(async (questionId, value) => {
      await api.post(`/user/assessments/save-answer?attempt_id=${attemptId}`, {
        question_id: questionId,
        answer: value,
      });
    });

  const markOffline = useCallback(() => {
    if (offlineSinceRef.current === null) offlineSinceRef.current = Date.now();
    setIsOffline(true);
  }, []);

  const persistDraft = useCallback((data = examDataRef.current, nextAnswers = answersRef.current) => {
    if (!data) return;
    if (!userKey) {
      setSaveError("Your account could not be identified for a safe offline draft. Keep this page open until answers sync.");
      return;
    }
    const saved = saveAssessmentDraft({
      userKey,
      assessmentId,
      attemptId: data.attempt_id,
      updatedAt: Date.now(),
      timeRemainingSeconds: timeLeftRef.current,
      answers: nextAnswers,
      pendingSubmit: pendingSubmitRef.current,
      examData: data,
    });
    if (!saved) setSaveError("Browser storage is unavailable. Keep this page open until your answers sync.");
  }, [assessmentId, userKey]);

  const syncOfflineDraft = useCallback(async () => {
    const data = examDataRef.current;
    if (!data) return;
    const answerList = data.questions.map((question) => ({
      question_id: question.id,
      answer: answersRef.current[question.id] || "",
    }));
    try {
      const response = await api.post(`/user/assessments/offline-sync/${data.attempt_id}`, {
        answers: answerList,
      });
      const status = response.data?.status;
      if (status === "finished") {
        clearAssessmentDraft(userKey, assessmentId, data.attempt_id);
        setIsOffline(false);
        offlineSinceRef.current = null;
        setOfflineLocked(false);
        setLocallyExpired(false);
        setPendingSubmit(false);
        pendingSubmitRef.current = false;
        setSubmittedWithAutosaveWarning(false);
        setPhase("submitted");
        exitFullscreenRef.current?.();
        return;
      }
      const remaining = Number(response.data?.time_remaining_seconds);
      if (Number.isFinite(remaining)) {
        deadlineEpochRef.current = assessmentDeadlineEpoch(remaining, data.assessment_end_time);
        timeLeftRef.current = remaining;
        setTimeLeft(remaining);
      }
      offlineSinceRef.current = null;
      setIsOffline(false);
      setOfflineLocked(false);
      setLocallyExpired(false);
      setError("");
      setSaveError("");

      if (pendingSubmitRef.current) {
        await api.post(`/user/assessments/submit/${data.attempt_id}`, { answers: answerList });
        clearAssessmentDraft(userKey, assessmentId, data.attempt_id);
        pendingSubmitRef.current = false;
        setPendingSubmit(false);
        setSubmittedWithAutosaveWarning(false);
        setPhase("submitted");
        exitFullscreenRef.current?.();
      } else {
        persistDraft(data);
      }
    } catch {
      markOffline();
      setError("Could not sync yet. Keep this page open; your saved draft will retry when the connection returns.");
    }
  }, [assessmentId, markOffline, persistDraft, userKey]);
  useEffect(() => {
    syncOfflineRef.current = syncOfflineDraft;
  }, [syncOfflineDraft]);

  // Keep refs in sync
  useEffect(() => { violationsRef.current = violations; }, [violations]);
  useEffect(() => { escapeAttemptsRef.current = escapeAttempts; }, [escapeAttempts]);
  useEffect(() => { examDataRef.current = examData; }, [examData]);
  useEffect(() => { answersRef.current = answers; }, [answers]);
  useEffect(() => { timeLeftRef.current = timeLeft; }, [timeLeft]);

  // ---- Network Speed Test ----
  const runSpeedTest = async () => {
    setSpeedTesting(true);
    setSpeedMbps(null);
    try {
      // Download a known-size payload from the API to estimate real throughput.
      // The endpoint returns random bytes (default 500 KB) to prevent
      // transparent compression from inflating the measured speed.
      const testUrl = `${API_BASE}/speed-test?size=524288&_t=${Date.now()}`;
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
        markOffline();
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
  }, [phase, markOffline]);

  // ---- Start Exam ----
  const startExam = async () => {
    if (starting) return;
    setStarting(true);
    try {
      const res = await api.post(`/user/assessments/start/${assessmentId}`);
      const data: ExamData = res.data;
      answerSaveQueueRef.current = createAnswerSaveQueue(data.attempt_id);
      setExamData(data);
      violationsRef.current = Number(data.tab_violations || 0);
      setViolations(violationsRef.current);

      // Restore saved answers if resuming
      const localDraft = userKey
        ? loadAssessmentDraft<ExamData>(userKey, assessmentId, data.attempt_id)
        : null;
      if (userKey) clearOtherAssessmentDrafts(userKey, assessmentId, data.attempt_id);
      const restored: Record<string, string> = {};
      if (data.saved_answers && data.saved_answers.length > 0) {
        data.saved_answers.forEach((sa) => {
          restored[sa.question_id] = sa.answer;
        });
      }
      if (localDraft) {
        const allowedQuestionIds = new Set(data.questions.map((question) => question.id));
        for (const [questionId, answer] of Object.entries(localDraft.answers)) {
          if (allowedQuestionIds.has(questionId)) restored[questionId] = answer;
        }
      }
      answersRef.current = restored;
      setAnswers(restored);
      pendingSubmitRef.current = Boolean(localDraft?.pendingSubmit);
      setPendingSubmit(pendingSubmitRef.current);

      const serverRemaining = data.time_remaining_seconds;
      const remaining = typeof serverRemaining === "number" && localDraft
        ? Math.min(serverRemaining, localDraft.timeRemainingSeconds)
        : serverRemaining;
      const hasDeadline = typeof remaining === "number";
      setDeadlineEnabled(hasDeadline);
      deadlineEpochRef.current = hasDeadline
        ? assessmentDeadlineEpoch(remaining, data.assessment_end_time)
        : null;
      timeLeftRef.current = hasDeadline ? remaining : 0;
      setTimeLeft(hasDeadline ? remaining : 0);


      setPhase("exam");
      examDataRef.current = data;
      persistDraft(data, restored);
      if (localDraft || pendingSubmitRef.current) {
        window.setTimeout(() => { void syncOfflineRef.current?.(); }, 0);
      }
      // Request fullscreen
      try {
        await document.documentElement.requestFullscreen();
      } catch {
        // May not be supported
      }
    } catch (err: unknown) {
      console.error(err);
      if (navigator.onLine === false) markOffline();
      const apiDetail = (err as { response?: { data?: { detail?: unknown } } })
        .response?.data?.detail;
      setError(typeof apiDetail === "string" ? apiDetail : "Failed to start assessment");
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

  const flushAnswerSaves = useCallback(async () => {
    try {
      if (answerSaveQueueRef.current) await answerSaveQueueRef.current.flush();
      setSaveError("");
    } catch {
      markOffline();
      setSaveError("Some answers have not synced. Keep this page open; the saved draft will retry when the connection returns.");
      throw new Error("One or more assessment answers could not be saved");
    }
  }, [markOffline]);

  const handleSubmit = useCallback(async () => {
    if (submittingRef.current) return;
    if (isOffline || navigator.onLine === false) {
      pendingSubmitRef.current = true;
      setPendingSubmit(true);
      setLocallyExpired((current) => current || timeLeftRef.current <= 0);
      setError("Submission has not reached the server. Keep this page open; it will sync and submit when the connection returns.");
      persistDraft();
      markOffline();
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);

    const data = examDataRef.current;
    if (!data) { submittingRef.current = false; setSubmitting(false); return; }

    let autosaveFailed = false;
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
      saveTimeoutRef.current = null;
    }
    try {
      await flushAnswerSaves();
    } catch {
      autosaveFailed = true;
    }

    const answerList = data.questions.map((q) => ({
      question_id: q.id,
      answer: answersRef.current[q.id] || "",
    }));

    try {
      await api.post(`/user/assessments/submit/${data.attempt_id}`, { answers: answerList });
      clearAssessmentDraft(userKey, assessmentId, data.attempt_id);
      pendingSubmitRef.current = false;
      setPendingSubmit(false);
      if (timerRef.current) clearInterval(timerRef.current);
      setSubmittedWithAutosaveWarning(autosaveFailed);
      setPhase("submitted");
      exitFullscreen();
    } catch {
      markOffline();
      if (timeLeftRef.current <= 0 || (deadlineEpochRef.current !== null && Date.now() >= deadlineEpochRef.current)) {
        pendingSubmitRef.current = true;
        setPendingSubmit(true);
        setLocallyExpired(true);
      }
      persistDraft();
      if (timeLeftRef.current <= 0 && timerRef.current) clearInterval(timerRef.current);
      setShowAutoSubmitModal(false);
      setError(
          deadlineEpochRef.current !== null && Date.now() >= deadlineEpochRef.current
          ? "Your time has expired. Keep this page open and reconnect so your saved draft can sync before evaluation."
          : "Submission failed. Check your connection and submit again."
      );
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }, [assessmentId, exitFullscreen, flushAnswerSaves, isOffline, markOffline, persistDraft, userKey]);

  useEffect(() => {
    exitFullscreenRef.current = exitFullscreen;
  }, [exitFullscreen]);

  // ---- Timer ----
  useEffect(() => {
    if (phase !== "exam" || offlineLocked || locallyExpired || !deadlineEnabled || deadlineEpochRef.current === null) return;
    timerRef.current = setInterval(() => {
      const deadline = deadlineEpochRef.current;
      if (deadline === null) return;
      const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      timeLeftRef.current = remaining;
      setTimeLeft(remaining);
      if (remaining === 0) {
        if (timerRef.current) clearInterval(timerRef.current);
        setShowAutoSubmitModal(true);
        if (isOffline || navigator.onLine === false) {
          pendingSubmitRef.current = true;
          setPendingSubmit(true);
          setLocallyExpired(true);
          persistDraft();
          markOffline();
        }
        void handleSubmit();
      } else {
        setTimeLeft(remaining);
        persistDraft();
      }
    }, 1000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [phase, deadlineEnabled, offlineLocked, locallyExpired, handleSubmit, isOffline, markOffline, persistDraft]);

  // The server checkpoints active time on each heartbeat. Leaving this page
  // pauses the session; missed heartbeats are bounded by the server lease.
  useEffect(() => {
    const attemptId = examData?.attempt_id;
    if (phase !== "exam" || !attemptId) return;
    const heartbeat = setInterval(() => {
      void api.post(`/user/assessments/heartbeat/${attemptId}`).then((response) => {
        const remaining = Number(response.data?.time_remaining_seconds);
        if (Number.isFinite(remaining)) {
          const currentData = examDataRef.current;
          deadlineEpochRef.current = currentData
            ? assessmentDeadlineEpoch(remaining, currentData.assessment_end_time)
            : Date.now() + remaining * 1000;
          timeLeftRef.current = remaining;
          setTimeLeft(remaining);
        }
        if (offlineSinceRef.current !== null || response.data?.status === "finished") {
          void syncOfflineRef.current?.();
        }
      }).catch(() => {
        markOffline();
      });
    }, 5000);
    const onOnline = () => { void syncOfflineRef.current?.(); };
    const onOffline = () => { markOffline(); };
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      clearInterval(heartbeat);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      void api.post(`/user/assessments/pause/${attemptId}`).catch(() => {
        // Heartbeat lease bounds time if a best-effort pause cannot reach the server.
      });
    };
  }, [phase, examData?.attempt_id, markOffline]);

  useEffect(() => {
    if (phase !== "exam") return;
    const timer = window.setInterval(() => {
      const offlineSince = offlineSinceRef.current;
      if (offlineSince === null || Date.now() - offlineSince < OFFLINE_LOCK_AFTER_MS) return;
      if (!offlineLocked) {
        setOfflineLocked(true);
        if (deadlineEpochRef.current !== null) {
          deadlineEpochRef.current = Date.now() + timeLeftRef.current * 1000;
        }
        persistDraft();
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [phase, offlineLocked, persistDraft]);

  // ---- Fullscreen / Tab Violations ----
  const sendIntegrityEvent = useCallback((eventType: string) => {
    const attemptId = examDataRef.current?.attempt_id;
    if (!attemptId) return Promise.resolve(null);
    // The event UUID survives HTTP retries at the server's idempotency boundary.
    const payload = {
      event_id: crypto.randomUUID(),
      event_type: eventType,
      answers: Object.entries(answersRef.current).map(([question_id, answer]) => ({ question_id, answer })),
    };
    return api.post(`/user/assessments/save-violations?attempt_id=${attemptId}`, payload).catch(() =>
      api.post(`/user/assessments/save-violations?attempt_id=${attemptId}`, payload),
    ).catch(() => {
      markOffline();
      return null;
    });
  }, [markOffline]);

  const handleViolation = useCallback((eventType: "focus_lost" | "fullscreen_exit" = "focus_lost") => {
    if (phase !== "exam") return;
    // visibilitychange, blur, and fullscreenchange often describe one action.
    // Coalesce them so one browser action counts as one exit event.
    const now = Date.now();
    if (now - lastFocusSignalAtRef.current < 1500) return;
    lastFocusSignalAtRef.current = now;
    const newCount = violationsRef.current + 1;
    violationsRef.current = newCount;
    setViolations(newCount);
    setWarningType('violation');

    setShowWarning(true);
    void sendIntegrityEvent(eventType).then((response) => {
      if (response?.data?.status === "aborted") {
        setPhase("aborted");
        exitFullscreenRef.current?.();
      }
    });
    // Re-enter fullscreen after the warning; the server applies the configured
    // five-event limit using deduplicated, attempt-owned event IDs.
    if (document.fullscreenEnabled) {
      void document.documentElement.requestFullscreen().catch(() => {});
    }
  }, [phase, sendIntegrityEvent]);

  // ---- Escape Key Handler ----
  const handleEscapeAttempt = useCallback(() => {
    if (phase !== "exam") return;
    const newCount = escapeAttemptsRef.current + 1;
    sendIntegrityEvent("escape_key");
    setEscapeAttempts(newCount);
    setWarningType('escape');

    setShowWarning(true);
    // Escape can be a browser/assistive-technology action. Do not end the
    // assessment based on this client-side signal.
    if (document.fullscreenEnabled && !document.fullscreenElement) {
      void document.documentElement.requestFullscreen().catch(() => {});
    }
  }, [phase, sendIntegrityEvent]);

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
        handleViolation("fullscreen_exit");
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
        // Browser key events are advisory only and cannot prove misconduct.
        sendIntegrityEvent("devtools_shortcut");
        setWarningType('violation');
        setShowWarning(true);
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
  }, [phase, handleViolation, handleEscapeAttempt, sendIntegrityEvent]);



  // ---- Answer handling with auto-save ----
  const setAnswer = (questionId: string, value: string) => {
    const nextAnswers = { ...answersRef.current, [questionId]: value };
    answersRef.current = nextAnswers;
    setAnswers(nextAnswers);
    persistDraft(examDataRef.current, nextAnswers);

    // Debounced auto-save: save after 500ms of inactivity per question
    answerSaveQueueRef.current?.enqueue(questionId, value);
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(() => {
      void flushAnswerSaves().catch(() => undefined);
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
              <li>Fullscreen and focus changes may show a reminder</li>
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
              {submittedWithAutosaveWarning && (
                <p role="alert" className="mt-3 text-sm text-amber-800">
                  One or more autosaves failed before submission. Check your results to confirm each answer was recorded.
                </p>
              )}
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
  const answersLocked = submitting || offlineLocked || locallyExpired || pendingSubmit;
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
      {isOffline && !offlineLocked && !locallyExpired && (
        <div role="status" className="bg-amber-100 px-5 py-2 text-sm text-amber-950">
          Connection lost. Answers are being saved on this device and the timer continues for up to five minutes. Keep this page open.
        </div>
      )}
      {(offlineLocked || (locallyExpired && isOffline)) && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/80 p-5">
          <section role="alert" aria-live="assertive" className="max-w-lg rounded-xl bg-white p-7 text-center text-gray-900 shadow-2xl">
            <h2 className="text-xl font-semibold">{locallyExpired ? "Assessment time has ended" : "Assessment paused while offline"}</h2>
            <p className="mt-3 text-sm leading-6 text-gray-700">
              {pendingSubmit
                ? "Your answers are saved on this device. Keep this page open and reconnect so they can be synced and submitted."
                : "Answers are locked and the assessment timer is paused. Keep this page open; when the connection returns, your draft will sync and the same attempt can resume if time remains."}
            </p>
            <p className="mt-3 text-sm font-medium text-red-700">Do not refresh or close this page.</p>
          </section>
        </div>
      )}
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
                <h3 className="text-base font-semibold mb-1">Reminder ({escapeAttempts})</h3>
                <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                  Your assessment remains active. Use the assessment controls to submit when you are ready.
                </p>
              </>
            ) : (
              <>
            <h3 className="text-base font-semibold mb-1">Assessment exit warning ({violations}/5)</h3>
                <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                  A focus or fullscreen exit counts toward the five-event limit. The fifth event ends the attempt and saves your synced answers.
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

      {error && (
        <div className="bg-red-700 px-6 py-2 text-center text-sm text-white">{error}</div>
      )}
      {saveError && (
        <div role="alert" className="bg-amber-100 px-6 py-2 text-center text-sm text-amber-900">
          {saveError}
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
          <div className={`text-sm font-mono font-semibold px-3 py-1 rounded ${deadlineEnabled && timeLeft < 60 ? "bg-red-600 animate-pulse" : deadlineEnabled && timeLeft < 300 ? "bg-amber-600" : "bg-gray-700"}`}>
            {deadlineEnabled ? formatTime(timeLeft) : "No time limit"}
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
              Escape reminders: {escapeAttempts}
            </span>
          )}
          <button
            onClick={() => setShowSubmitConfirm(true)}
            disabled={answersLocked}
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
              key={question.id}
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
              readOnly={answersLocked}
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
                        disabled={answersLocked}
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
                disabled={answersLocked}
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
          disabled={currentQ === 0 || answersLocked}
          className="h-9 px-4 text-sm font-medium rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
        >
          Previous
        </button>
        <div className="flex gap-3">
          {currentQ < examData.questions.length - 1 ? (
            <button
              onClick={goToNextQuestionInSection}
              disabled={answersLocked}
              className="h-9 px-4 text-sm font-medium rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            >
              Next
            </button>
          ) : null}
        </div>
      </footer>
    </div>
  );
}
