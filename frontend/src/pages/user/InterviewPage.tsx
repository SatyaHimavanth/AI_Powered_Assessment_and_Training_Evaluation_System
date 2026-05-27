import { useEffect, useRef, useState } from "react";
import api from "../../api";
import SpeechToTextControl, { type SpeechToTextControlHandle } from "../../components/SpeechToTextControl";

interface InterviewTemplate {
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
}

interface InterviewSession {
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
}

interface SessionResult {
  id: string;
  status: string;
  transcript: { role: string; content: string; timestamp: string }[];
}

interface Props {
  templateId: string;
  sessionId?: string;
  onExit: () => void;
}

type Phase = "details" | "interview" | "completed";

export default function InterviewPage({ templateId, sessionId: resumeSessionId, onExit }: Props) {
  const [phase, setPhase] = useState<Phase>(resumeSessionId ? "interview" : "details");
  const [template, setTemplate] = useState<InterviewTemplate | null>(null);
  const [session, setSession] = useState<InterviewSession | null>(null);
  const [sessionResult, setSessionResult] = useState<SessionResult | null>(null);
  const [draft, setDraft] = useState("");
  const [editSecondsLeft, setEditSecondsLeft] = useState<number | null>(null); // null = edit timer not running
  const [overallSecondsLeft, setOverallSecondsLeft] = useState<number>(0);
  const [isSubmittingDraft, setIsSubmittingDraft] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(true);
  const [isMicActive, setIsMicActive] = useState(false);
  const [isTtsSpeaking, setIsTtsSpeaking] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const lastSpokenRef = useRef<string>("");
  const sessionIdRef = useRef<string | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const editTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const overallTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const micRef = useRef<SpeechToTextControlHandle | null>(null);
  const draftRef = useRef<string>("");

  // Keep draftRef in sync
  useEffect(() => { draftRef.current = draft; }, [draft]);

  const interruptKey = (sessionId: string) => `interview_interrupt_${sessionId}`;

  const markPotentialInterrupt = (sessionId: string | null) => {
    if (!sessionId) return;
    try {
      window.localStorage.setItem(interruptKey(sessionId), "1");
    } catch {
      // ignore
    }
  };

  const clearPotentialInterrupt = (sessionId: string | null) => {
    if (!sessionId) return;
    try {
      window.localStorage.removeItem(interruptKey(sessionId));
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    const loadTemplate = async () => {
      try {
        const res = await api.get("/interviews/templates");
        const templates = Array.isArray(res.data) ? res.data : [];
        const t = templates.find((x: any) => x.id === templateId);
        if (t) {
          setTemplate(t);
        } else {
          setError("Template not found");
        }
      } catch {
        setError("Failed to load template");
      } finally {
        if (!resumeSessionId) setLoading(false);
      }
    };
    loadTemplate();
  }, [templateId]);

  // If resuming, load existing session and enter interview phase (wait for template)
  useEffect(() => {
    if (!resumeSessionId || !template) return;
    const resumeExisting = async () => {
      try {
        // Report any pending interrupt from previous disconnection
        const key = interruptKey(resumeSessionId);
        if (window.localStorage.getItem(key)) {
          await api.post(`/interviews/${resumeSessionId}/interrupt`).catch(() => {});
          window.localStorage.removeItem(key);
        }
        // Resume the session on the backend
        await api.post(`/interviews/${resumeSessionId}/resume`).catch(() => {});
        await loadSessionResult(resumeSessionId);
        sessionIdRef.current = resumeSessionId;
        setSession({ id: resumeSessionId, template_id: templateId, template_title: template.title, status: "in_progress", attempt_number: 1, pause_count: 0, max_pauses_allowed: template.max_pauses_allowed, started_at: null, completed_at: null, total_score: null });
        // Set overall timer from template duration
        setOverallSecondsLeft(template.duration_minutes * 60);
        setPhase("interview");
        markPotentialInterrupt(resumeSessionId);
        try { await document.documentElement.requestFullscreen(); } catch {}
      } catch {
        setError("Failed to resume interview");
      } finally {
        setLoading(false);
      }
    };
    resumeExisting();
  }, [resumeSessionId, template]);

  const loadSessionResult = async (sessionId: string) => {
    try {
      const res = await api.get(`/interviews/${sessionId}/results`);
      setSessionResult(res.data);
    } catch {
      setSessionResult(null);
    }
  };

  const startInterview = async () => {
    if (!template) return;
    // Request fullscreen immediately (user gesture context)
    try {
      await document.documentElement.requestFullscreen();
    } catch {
      // ignore
    }
    setLoading(true);
    try {
      const res = await api.post("/interviews/start", { template_id: template.id });
      const newSession: InterviewSession = res.data;
      setSession(newSession);
      sessionIdRef.current = newSession.id;
      setDraft("");
      setEditSecondsLeft(null);
      setOverallSecondsLeft(template.duration_minutes * 60);
      await loadSessionResult(newSession.id);
      setPhase("interview");
      markPotentialInterrupt(newSession.id);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to start interview");
      // Exit fullscreen if start failed
      if (document.fullscreenElement) {
        document.exitFullscreen().catch(() => {});
      }
    } finally {
      setLoading(false);
    }
  };

  // Overall interview timer countdown
  useEffect(() => {
    if (phase !== "interview" || overallSecondsLeft <= 0) return;
    overallTimerRef.current = window.setInterval(() => {
      setOverallSecondsLeft((prev) => {
        if (prev <= 1) {
          if (overallTimerRef.current) window.clearInterval(overallTimerRef.current);
          // Time's up - end interview
          void endInterview();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => {
      if (overallTimerRef.current) window.clearInterval(overallTimerRef.current);
    };
  }, [phase, overallSecondsLeft > 0]);

  // Edit window timer (starts when mic stops, 3 minutes)
  useEffect(() => {
    if (editSecondsLeft === null) {
      if (editTimerRef.current) {
        window.clearInterval(editTimerRef.current);
        editTimerRef.current = null;
      }
      return;
    }
    editTimerRef.current = window.setInterval(() => {
      setEditSecondsLeft((prev) => {
        if (prev === null || prev <= 1) {
          if (editTimerRef.current) window.clearInterval(editTimerRef.current);
          editTimerRef.current = null;
          // Auto-submit when edit window expires
          if ((draftRef.current || "").trim()) {
            void submitDraft(true);
          } else {
            void submitMessage(sessionIdRef.current || "", "No response provided.", true);
          }
          return null;
        }
        return prev - 1;
      });
    }, 1000);
    return () => {
      if (editTimerRef.current) {
        window.clearInterval(editTimerRef.current);
        editTimerRef.current = null;
      }
    };
  }, [editSecondsLeft !== null]); // only restart when timer starts/stops

  // Handle mic stopped -> start edit window
  const handleMicStopped = () => {
    setIsMicActive(false);
    // Clear silence timer
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    // Start 3-minute edit window
    setEditSecondsLeft(180);
  };

  // Handle mic started
  const handleMicStarted = () => {
    setIsMicActive(true);
    // Stop edit window timer while mic is active
    setEditSecondsLeft(null);
  };

  // TTS for AI messages - auto-start mic after TTS completes
  useEffect(() => {
    if (!sessionResult || !ttsEnabled) return;
    const transcript = sessionResult.transcript || [];
    if (!transcript.length) return;
    const last = transcript[transcript.length - 1];
    if (!last || last.role !== "assistant") return;
    if (!last.content || last.content === lastSpokenRef.current) return;

    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(last.content);
      utter.rate = 1.0;
      utter.pitch = 1.0;
      utter.onstart = () => setIsTtsSpeaking(true);
      utter.onend = () => {
        setIsTtsSpeaking(false);
        // Auto-start mic after TTS completes
        if (micRef.current) {
          micRef.current.start();
        }
      };
      window.speechSynthesis.speak(utter);
      lastSpokenRef.current = last.content;
    }
  }, [sessionResult, ttsEnabled]);

  // Disconnect tracking
  useEffect(() => {
    if (phase !== "interview" || !sessionIdRef.current) return;

    const onBeforeUnload = () => {
      markPotentialInterrupt(sessionIdRef.current);
    };

    const onOffline = () => {
      markPotentialInterrupt(sessionIdRef.current);
    };

    const onOnline = () => {
      if (sessionIdRef.current) {
        void reportInterrupt(sessionIdRef.current);
      }
    };

    const onFullscreenChange = () => {
      if (!document.fullscreenElement && sessionIdRef.current && phase === "interview") {
        // User exited fullscreen — record as interrupt/pause
        void reportInterrupt(sessionIdRef.current);
      }
    };

    window.addEventListener("beforeunload", onBeforeUnload);
    window.addEventListener("offline", onOffline);
    window.addEventListener("online", onOnline);
    document.addEventListener("fullscreenchange", onFullscreenChange);

    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("online", onOnline);
      document.removeEventListener("fullscreenchange", onFullscreenChange);
    };
  }, [phase]);

  async function reportInterrupt(sessionId: string) {
    try {
      await api.post(`/interviews/${sessionId}/interrupt`);
      clearPotentialInterrupt(sessionId);
      await loadSessionResult(sessionId);
    } catch {
      // keep flag for retry
    }
  }

  async function submitMessage(sessionId: string, text: string, auto = false) {
    setIsSubmittingDraft(true);
    try {
      const res = await api.post(`/interviews/${sessionId}/message`, { response_text: text });
      const fromAuto = auto ? " (auto-submitted)" : "";
      console.log(`Response submitted${fromAuto}. Score: ${res.data?.score ?? "N/A"}`);
      setDraft("");
      setEditSecondsLeft(null); // Reset edit timer
      await loadSessionResult(sessionId);
      // If TTS is disabled, start edit window immediately for next response
      if (!ttsEnabled) {
        setEditSecondsLeft(180);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to submit response");
    } finally {
      setIsSubmittingDraft(false);
    }
  }

  async function submitDraft(auto = false) {
    if (!sessionIdRef.current) return;
    const text = (draft || "").trim();
    if (!text) {
      setError("Response cannot be empty");
      return;
    }
    await submitMessage(sessionIdRef.current, text, auto);
  }

  async function endInterview() {
    if (!sessionIdRef.current) return;
    setLoading(true);
    try {
      await api.post(`/interviews/${sessionIdRef.current}/end`);
      clearPotentialInterrupt(sessionIdRef.current);
      await loadSessionResult(sessionIdRef.current);
      setPhase("completed");
      if (document.fullscreenElement) {
        document.exitFullscreen().catch(() => {});
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to end interview");
    } finally {
      setLoading(false);
    }
  }

  if (loading && phase === "details") {
    return (
      <div className="fixed inset-0 bg-white flex items-center justify-center">
        <p className="text-sm text-gray-500">Loading...</p>
      </div>
    );
  }

  // Details screen before starting
  if (phase === "details") {
    return (
      <div className="fixed inset-0 bg-gradient-to-br from-slate-50 to-blue-50 flex flex-col">
        {/* Top bar */}
        <div className="border-b border-gray-200 bg-white/80 backdrop-blur px-8 py-4 flex items-center justify-between">
          <h1 className="text-lg font-bold text-gray-900">Interview Details</h1>
          <button
            onClick={onExit}
            className="h-9 px-4 text-sm font-medium rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
          >
            Back
          </button>
        </div>

        <div className="flex-1 overflow-auto">
          {error && (
            <div className="mx-8 mt-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
              {error}
            </div>
          )}

          {template && (
            <div className="p-8 space-y-8">
              {/* Title Section */}
              <div>
                <h2 className="text-3xl font-bold text-gray-900">{template.title}</h2>
                <p className="text-lg text-gray-600 mt-1">Role: {template.role}</p>
              </div>

              {/* Stats Grid */}
              <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
                <div className="bg-white rounded-xl border border-blue-100 p-5 shadow-sm">
                  <div className="text-xs uppercase tracking-wide text-blue-600 font-semibold mb-2">Experience Level</div>
                  <div className="text-2xl font-bold text-gray-900">{template.experience_level}</div>
                </div>
                <div className="bg-white rounded-xl border border-purple-100 p-5 shadow-sm">
                  <div className="text-xs uppercase tracking-wide text-purple-600 font-semibold mb-2">Difficulty</div>
                  <div className="text-2xl font-bold text-gray-900">{template.difficulty}</div>
                </div>
                <div className="bg-white rounded-xl border border-green-100 p-5 shadow-sm">
                  <div className="text-xs uppercase tracking-wide text-green-600 font-semibold mb-2">Duration</div>
                  <div className="text-2xl font-bold text-gray-900">{template.duration_minutes}<span className="text-base font-normal text-gray-500 ml-1">min</span></div>
                </div>
                <div className="bg-white rounded-xl border border-orange-100 p-5 shadow-sm">
                  <div className="text-xs uppercase tracking-wide text-orange-600 font-semibold mb-2">Questions</div>
                  <div className="text-2xl font-bold text-gray-900">{template.question_count}</div>
                </div>
                <div className="bg-white rounded-xl border border-red-100 p-5 shadow-sm">
                  <div className="text-xs uppercase tracking-wide text-red-600 font-semibold mb-2">Max Pauses</div>
                  <div className="text-2xl font-bold text-gray-900">{template.max_pauses_allowed}</div>
                </div>
              </div>

              {/* Topics and Questions */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {(template.focus_areas || []).length > 0 && (
                  <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                    <h3 className="text-sm font-semibold text-gray-900 mb-3">Topics to Cover</h3>
                    <div className="flex flex-wrap gap-2">
                      {template.focus_areas.map((area, idx) => (
                        <span key={idx} className="px-3 py-1.5 bg-blue-50 text-blue-800 rounded-lg text-sm font-medium">
                          {area}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {(template.default_questions_or_topics || []).length > 0 && (
                  <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                    <h3 className="text-sm font-semibold text-gray-900 mb-3">Reference Questions</h3>
                    <ul className="space-y-2">
                      {template.default_questions_or_topics.map((q, idx) => (
                        <li key={idx} className="text-sm text-gray-700 flex gap-2">
                          <span className="font-bold text-gray-400 shrink-0">{idx + 1}.</span>
                          <span>{q}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Instructions & Start */}
              <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
                <h3 className="text-sm font-semibold text-gray-900 mb-3">Instructions</h3>
                <ul className="space-y-2 text-sm text-gray-700 mb-6">
                  <li className="flex items-start gap-2">
                    <span className="text-blue-500 mt-0.5">•</span>
                    You will have <strong>{template.duration_minutes} minutes</strong> to complete this interview.
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-blue-500 mt-0.5">•</span>
                    Each response has a <strong>1-minute edit window</strong> before auto-submit.
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-blue-500 mt-0.5">•</span>
                    You may use the microphone button to dictate responses.
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-blue-500 mt-0.5">•</span>
                    Exceeding <strong>{template.max_pauses_allowed} pauses</strong> will mark the interview as missed.
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-blue-500 mt-0.5">•</span>
                    The interview will enter fullscreen mode when started.
                  </li>
                </ul>
                <div className="flex gap-4">
                  <button
                    onClick={onExit}
                    className="h-11 px-6 text-sm font-medium rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={startInterview}
                    disabled={loading}
                    className="h-11 px-8 text-sm font-semibold rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
                  >
                    {loading ? "Starting..." : "Start Interview"}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Interview screen
  if (phase === "interview" && session && sessionResult) {
    return (
      <div className="fixed inset-0 bg-white flex flex-col">
        {/* Header */}
        <div className="border-b border-gray-200 bg-gray-50 px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div>
              <h2 className="font-semibold text-gray-900">{template?.title}</h2>
              <p className="text-xs text-gray-600">{template?.role}</p>
            </div>
          </div>

          <div className="flex items-center gap-6">
            <div className="text-center">
              <div className="text-xs uppercase tracking-wide text-gray-600 font-semibold mb-0.5">Interview Time</div>
              <div className={`text-lg font-bold ${overallSecondsLeft <= 60 ? "text-red-600" : "text-green-600"}`}>
                {Math.floor(overallSecondsLeft / 60)}:{String(overallSecondsLeft % 60).padStart(2, "0")}
              </div>
            </div>

            {editSecondsLeft !== null && (
              <div className="text-center">
                <div className="text-xs uppercase tracking-wide text-gray-600 font-semibold mb-0.5">Edit Window</div>
                <div className={`text-lg font-bold ${editSecondsLeft <= 30 ? "text-red-600" : "text-blue-600"}`}>
                  {Math.floor(editSecondsLeft / 60)}:{String(editSecondsLeft % 60).padStart(2, "0")}
                </div>
              </div>
            )}

            <div className="text-center">
              <div className="text-xs uppercase tracking-wide text-gray-600 font-semibold mb-0.5">Pauses</div>
              <div className={`text-lg font-bold ${session.pause_count >= session.max_pauses_allowed ? "text-red-600" : "text-blue-600"}`}>
                {session.pause_count}/{session.max_pauses_allowed}
              </div>
            </div>

            {isMicActive && (
              <div className="text-center">
                <div className="text-xs font-semibold text-red-600 animate-pulse">🎤 Recording</div>
              </div>
            )}

            {isTtsSpeaking && (
              <div className="text-center">
                <div className="text-xs font-semibold text-purple-600 animate-pulse">🔊 Speaking</div>
              </div>
            )}

            <label className="flex items-center gap-2">
              <span className="text-xs text-gray-600">TTS</span>
              <button
                type="button"
                onClick={() => setTtsEnabled((v) => !v)}
                className={`h-7 px-2 text-xs font-medium rounded-md ${
                  ttsEnabled ? "bg-blue-50 text-blue-700" : "bg-gray-100 text-gray-700"
                }`}
              >
                {ttsEnabled ? "On" : "Off"}
              </button>
            </label>

            <button
              onClick={endInterview}
              disabled={loading}
              className="h-8 px-4 text-xs font-medium rounded-lg bg-red-50 text-red-700 hover:bg-red-100 disabled:opacity-50"
            >
              End
            </button>
          </div>
        </div>

        {/* Transcript */}
        <div className="flex-1 overflow-auto p-6 bg-gray-50">
          <div className="max-w-3xl mx-auto space-y-3">
            {(sessionResult.transcript || []).map((m, idx) => (
              <div
                key={`${m.timestamp}-${idx}`}
                className={`rounded-lg px-4 py-3 text-sm ${
                  m.role === "assistant" ? "bg-white border border-gray-200" : "bg-blue-50"
                }`}
              >
                <div className="text-xs uppercase tracking-wide font-semibold mb-1 text-gray-600">{m.role}</div>
                <div className="text-gray-900">{m.content}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Input area */}
        <div className="border-t border-gray-200 bg-white p-6">
          <div className="max-w-3xl mx-auto space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-xs text-gray-600">
                {isMicActive
                  ? "Mic active — speak your response (auto-stops after 5s silence)"
                  : editSecondsLeft !== null
                  ? `Edit window: ${Math.floor(editSecondsLeft / 60)}:${String(editSecondsLeft % 60).padStart(2, "0")} (auto-submit at 0:00)`
                  : "Waiting for AI to finish speaking..."}
              </div>
              <SpeechToTextControl
                ref={micRef}
                disabled={isSubmittingDraft || isTtsSpeaking}
                onTranscriptChange={(text) => {
                  setDraft((prev) => (prev ? `${prev} ${text}` : text));
                  // Reset silence timer on new speech
                  if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
                  silenceTimerRef.current = setTimeout(() => {
                    // 5 seconds of silence - auto-stop mic
                    if (micRef.current) micRef.current.stop();
                  }, 5000);
                }}
                onError={(err) => setError(err)}
                onStart={handleMicStarted}
                onStop={handleMicStopped}
              />
            </div>

            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={isSubmittingDraft || isMicActive}
              className="w-full min-h-20 px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
              placeholder={isMicActive ? "Mic is active — speak your response..." : "Edit your response here, or use mic to dictate..."}
            />

            <div className="flex justify-end">
              <button
                type="button"
                onClick={() => void submitDraft(false)}
                disabled={isSubmittingDraft || !(draft || "").trim()}
                className="h-9 px-4 text-sm font-medium rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isSubmittingDraft ? "Submitting..." : "Submit Response"}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Completed screen
  if (phase === "completed") {
    return (
      <div className="fixed inset-0 bg-white flex items-center justify-center">
        <div className="text-center">
          <h2 className="text-2xl font-bold mb-2">Interview Completed</h2>
          <p className="text-gray-600 mb-6">Your responses have been submitted for evaluation.</p>
          <button
            onClick={onExit}
            className="h-10 px-6 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700"
          >
            Return to Interviews
          </button>
        </div>
      </div>
    );
  }

  return null;
}
