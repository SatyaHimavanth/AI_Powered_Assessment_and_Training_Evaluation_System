import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../api";
import type { PendingRequest, UserInfo, TopicInfo, BatchInfo } from "./types";
import Dashboard from "./Dashboard";
import Approvals from "./Approvals";
import Users from "./Users";
import Questions from "./Questions";
import Assessments from "./Assessments";
import Batches from "./Batches";
import Results from "./Results";
import Toast from "../../components/Toast";

type Tab = "dashboard" | "approvals" | "users" | "assessments" | "questions" | "batches" | "results";

const NAV_ITEMS: { key: Tab; label: string; icon: React.ReactNode }[] = [
  {
    key: "dashboard",
    label: "Dashboard",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
      </svg>
    ),
  },
  {
    key: "approvals",
    label: "Approvals",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M19 7.5v3m0 0v3m0-3h3m-3 0h-3m-2.25-4.125a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zM4 19.235v-.11a6.375 6.375 0 0112.75 0v.109A12.318 12.318 0 0110.374 21c-2.331 0-4.512-.645-6.374-1.766z" />
      </svg>
    ),
  },
  {
    key: "users",
    label: "Users",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
      </svg>
    ),
  },
  {
    key: "batches",
    label: "Batches",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z" />
      </svg>
    ),
  },
  {
    key: "assessments",
    label: "Assessments",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15a2.25 2.25 0 012.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25zM6.75 12h.008v.008H6.75V12zm0 3h.008v.008H6.75V15zm0 3h.008v.008H6.75V18z" />
      </svg>
    ),
  },
  {
    key: "questions",
    label: "Questions",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M9.879 7.519c1.171-1.025 3.071-1.025 4.242 0 1.172 1.025 1.172 2.687 0 3.712-.203.179-.43.326-.67.442-.745.361-1.45.999-1.45 1.827v.75M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9 5.25h.008v.008H12v-.008z" />
      </svg>
    ),
  },
  {
    key: "results",
    label: "Results",
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
    ),
  },
];

export default function AdminHome() {
  const [pending, setPending] = useState<PendingRequest[]>([]);
  const [pendingPracticeCount, setPendingPracticeCount] = useState(0);
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [topics, setTopics] = useState<TopicInfo[]>([]);
  const [batches, setBatches] = useState<BatchInfo[]>([]);
  const [activeTab, setActiveTab] = useState<Tab>("dashboard");
  const [message, setMessage] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const role = localStorage.getItem("role");
    if (role !== "admin") {
      navigate("/login");
      return;
    }
  }, [navigate]);

  // Reload relevant data whenever the active tab changes
  useEffect(() => {
    switch (activeTab) {
      case "dashboard":
        loadUsers();
        loadTopics();
        loadBatches();
        loadPending();
        break;
      case "approvals":
        loadPending();
        break;
      case "users":
        loadUsers();
        loadBatches();
        break;
      case "questions":
        loadTopics();
        break;
      case "assessments":
        loadTopics();
        loadBatches();
        break;
      case "batches":
        loadBatches();
        loadUsers();
        break;
      case "results":
        loadBatches();
        break;
    }
  }, [activeTab]);

  async function loadPending() {
    try {
      const [regRes, practiceRes] = await Promise.all([
        api.get("/admin/pending-registrations"),
        api.get("/admin/practice-access-requests"),
      ]);
      setPending(regRes.data);
      setPendingPracticeCount(Array.isArray(practiceRes.data) ? practiceRes.data.length : 0);
    } catch {
      // ignore
    }
  }

  async function loadUsers() {
    try {
      const res = await api.get("/admin/users");
      setUsers(res.data);
    } catch {
      // ignore
    }
  }

  async function loadTopics() {
    try {
      const res = await api.get("/questions/topics");
      setTopics(res.data);
    } catch {
      // ignore
    }
  }

  async function loadBatches() {
    try {
      const res = await api.get("/batches/");
      setBatches(res.data);
    } catch {
      // ignore
    }
  }

  const handleLogout = () => {
    localStorage.clear();
    navigate("/login");
  };

  const reloadAfterApprovals = () => {
    loadPending();
    loadUsers();
  };

  const tabTitle = () => {
    switch (activeTab) {
      case "questions": return "Question Bank";
      case "assessments": return "Assessments";
      case "batches": return "Batches";
      case "results": return "Results Analytics";
      default: return activeTab.charAt(0).toUpperCase() + activeTab.slice(1);
    }
  };

  return (
    <div className="flex h-screen bg-[var(--color-bg)]">
      {/* Sidebar */}
      <aside className={`${sidebarCollapsed ? "w-[68px]" : "w-[260px]"} bg-white border-r border-[var(--color-border)] flex flex-col transition-all duration-200`}>
        <div className="flex items-center gap-3 px-4 py-5 border-b border-[var(--color-border)]">
          <div className="w-9 h-9 shrink-0 rounded-[var(--radius-sm)] bg-[var(--color-primary)] text-white flex items-center justify-center text-sm font-bold">
            A
          </div>
          {!sidebarCollapsed && (
            <div className="overflow-hidden">
              <p className="text-sm font-semibold leading-tight">Admin Panel</p>
              <p className="text-xs text-[var(--color-text-secondary)]">Assessment System</p>
            </div>
          )}
        </div>

        <nav className="flex-1 px-2 py-4 space-y-1">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.key}
              onClick={() => setActiveTab(item.key)}
              title={sidebarCollapsed ? item.label : undefined}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-sm)] text-sm font-medium cursor-pointer transition-colors ${
                activeTab === item.key
                  ? "bg-blue-50 text-[var(--color-primary)]"
                  : "text-[var(--color-text-secondary)] hover:bg-gray-50 hover:text-[var(--color-text)]"
              } ${sidebarCollapsed ? "justify-center" : ""}`}
            >
              <span className="shrink-0">{item.icon}</span>
              {!sidebarCollapsed && item.label}
              {!sidebarCollapsed && item.key === "approvals" && (pending.length + pendingPracticeCount) > 0 && (
                <span className="ml-auto text-xs bg-[var(--color-danger)] text-white px-2 py-0.5 rounded-full font-medium">
                  {pending.length + pendingPracticeCount}
                </span>
              )}
              {sidebarCollapsed && item.key === "approvals" && (pending.length + pendingPracticeCount) > 0 && (
                <span className="absolute -top-1 -right-1 w-2 h-2 bg-[var(--color-danger)] rounded-full" />
              )}
            </button>
          ))}
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

      {/* Main Content */}
      <main className="flex-1 overflow-auto">
        <header className="sticky top-0 z-10 bg-white/80 backdrop-blur border-b border-[var(--color-border)] px-8 py-4">
          <h1 className="text-lg font-semibold">{tabTitle()}</h1>
        </header>

        <div className="p-8 max-w-[1200px]">
          <Toast message={message} onClose={() => setMessage("")} />

          {activeTab === "dashboard" && <Dashboard users={users} pending={pending} topics={topics} batches={batches} />}
          {activeTab === "approvals" && <Approvals pending={pending} setMessage={setMessage} reload={reloadAfterApprovals} />}
          {activeTab === "users" && <Users users={users} batches={batches} setMessage={setMessage} reloadUsers={loadUsers} />}
          {activeTab === "questions" && <Questions topics={topics} setMessage={setMessage} reloadTopics={loadTopics} />}
          {activeTab === "assessments" && <Assessments topics={topics} batches={batches} setMessage={setMessage} />}
          {activeTab === "batches" && <Batches batches={batches} users={users} setMessage={setMessage} reloadBatches={loadBatches} />}
          {activeTab === "results" && <Results batches={batches} />}
        </div>
      </main>
    </div>
  );
}
