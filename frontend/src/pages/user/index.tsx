import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../api";
import Dashboard from "./Dashboard";
import Performance from "./Performance";
import Practice from "./Practice";
import ExamPage from "./ExamPage";

interface UserProfile {
  username: string;
  email: string;
  name: string;
  role: string;
}

export default function UserHome() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [examAssessmentId, setExamAssessmentId] = useState<string | null>(null);
  const [currentView, setCurrentView] = useState<"dashboard" | "performance" | "practice">("dashboard");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  const loadProfile = useCallback(async () => {
    try {
      const res = await api.get("/auth/me");
      setProfile(res.data);
    } catch {
      navigate("/login");
    }
  }, [navigate]);

  useEffect(() => {
    const role = localStorage.getItem("role");
    if (role !== "user") {
      navigate("/login");
      return;
    }
    const t = setTimeout(() => {
      loadProfile();
    }, 0);
    return () => clearTimeout(t);
  }, [loadProfile, navigate]);

  const handleLogout = () => {
    localStorage.clear();
    navigate("/login");
  };

  // If in exam mode, render fullscreen exam
  if (examAssessmentId) {
    return (
      <ExamPage
        assessmentId={examAssessmentId}
        onExit={() => setExamAssessmentId(null)}
      />
    );
  }

  return (
    <div className="flex h-screen bg-[var(--color-bg)]">
      <aside className={`${sidebarCollapsed ? "w-[68px]" : "w-[260px]"} bg-white border-r border-[var(--color-border)] flex flex-col transition-all duration-200`}>
        <div className="flex items-center gap-3 px-4 py-5 border-b border-[var(--color-border)]">
          <div className="w-9 h-9 shrink-0 rounded-[var(--radius-sm)] bg-[var(--color-primary)] text-white flex items-center justify-center text-sm font-bold">
            A
          </div>
          {!sidebarCollapsed && (
            <div className="overflow-hidden">
              <p className="text-sm font-semibold leading-tight">User Panel</p>
              <p className="text-xs text-[var(--color-text-secondary)]">Assessment System</p>
            </div>
          )}
        </div>

        <nav className="flex-1 px-2 py-4 space-y-1">
          <button
            onClick={() => setCurrentView("dashboard")}
            title={sidebarCollapsed ? "Dashboard" : undefined}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-sm)] text-sm font-medium cursor-pointer transition-colors ${
              currentView === "dashboard"
                ? "bg-blue-50 text-[var(--color-primary)]"
                : "text-[var(--color-text-secondary)] hover:bg-gray-50"
            } ${sidebarCollapsed ? "justify-center" : ""}`}
          >
            <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
            </svg>
            {!sidebarCollapsed && "Dashboard"}
          </button>

          <button
            onClick={() => setCurrentView("performance")}
            title={sidebarCollapsed ? "Performance" : undefined}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-sm)] text-sm font-medium cursor-pointer transition-colors ${
              currentView === "performance"
                ? "bg-blue-50 text-[var(--color-primary)]"
                : "text-[var(--color-text-secondary)] hover:bg-gray-50"
            } ${sidebarCollapsed ? "justify-center" : ""}`}
          >
            <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            {!sidebarCollapsed && "Performance"}
          </button>

          <button
            onClick={() => setCurrentView("practice")}
            title={sidebarCollapsed ? "Practice Test" : undefined}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-sm)] text-sm font-medium cursor-pointer transition-colors ${
              currentView === "practice"
                ? "bg-blue-50 text-[var(--color-primary)]"
                : "text-[var(--color-text-secondary)] hover:bg-gray-50"
            } ${sidebarCollapsed ? "justify-center" : ""}`}
          >
            <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 18v-5.25m0 0a6.01 6.01 0 001.5-.189m-1.5.189a6.01 6.01 0 01-1.5-.189m3.75 7.478a12.06 12.06 0 01-4.5 0m3.75 2.383a14.406 14.406 0 01-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 10-7.517 0c.85.493 1.509 1.333 1.509 2.316V18" />
            </svg>
            {!sidebarCollapsed && "Practice Test"}
          </button>
        </nav>

        <div className="px-2 py-4 border-t border-[var(--color-border)] space-y-1">
          <button
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-sm)] text-sm font-medium text-[var(--color-text-secondary)] hover:bg-gray-50 cursor-pointer transition-colors ${sidebarCollapsed ? "justify-center" : ""}`}
          >
            <svg className={`w-5 h-5 shrink-0 transition-transform ${sidebarCollapsed ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M18.75 19.5l-7.5-7.5 7.5-7.5m-6 15L5.25 12l7.5-7.5" />
            </svg>
            {!sidebarCollapsed && "Collapse"}
          </button>
          <button
            onClick={handleLogout}
            title={sidebarCollapsed ? "Sign out" : undefined}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-sm)] text-sm font-medium text-[var(--color-text-secondary)] hover:bg-red-50 hover:text-[var(--color-danger)] cursor-pointer transition-colors ${sidebarCollapsed ? "justify-center" : ""}`}
          >
            <svg className="w-5 h-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
            </svg>
            {!sidebarCollapsed && "Sign out"}
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-auto">
        <header className="sticky top-0 z-10 bg-white/80 backdrop-blur border-b border-[var(--color-border)] px-8 py-4">
          <h1 className="text-lg font-semibold">
            {currentView === "dashboard" ? "Dashboard" : currentView === "performance" ? "Performance Report" : "Practice Test"}
          </h1>
        </header>
        <div className="p-8 max-w-[1200px]">
          {currentView === "dashboard" ? (
            <Dashboard
              profile={profile}
              onStartExam={(assessment) => setExamAssessmentId(assessment.id)}
            />
          ) : currentView === "performance" ? (
            <Performance />
          ) : (
            <Practice />
          )}
        </div>
      </main>
    </div>
  );
}
