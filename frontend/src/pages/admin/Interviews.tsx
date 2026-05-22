import { useEffect, useState } from "react";
import api from "../../api";
import { card, btnPrimary, inputClass, selectClass } from "./types";

type InterviewTemplate = {
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
  is_active: boolean;
  is_archived: boolean;
  created_at: string;
};

type InterviewResult = {
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

type SessionDetail = {
  id: string;
  template_title: string;
  status: string;
  total_score: number | null;
  summary: string | null;
  transcript: { role: string; content: string; timestamp: string }[];
  evaluations: { turn_index: number; user_response: string; score: number | null; focus_area: string; strengths: string[]; improvements: string[]; feedback: string }[];
  topic_scores: { topic: string; avg_score: number; turns: number }[];
};

type Props = {
  setMessage: (msg: string) => void;
};

const initialForm = {
  title: "",
  role: "",
  experience_level: "mid",
  difficulty: "intermediate",
  duration_minutes: 60,
  question_count: 5,
  focus_areas: [] as string[],
  default_questions_or_topics: [] as string[],
  max_pauses_allowed: 3,
};

export default function Interviews({ setMessage }: Props) {
  const [templates, setTemplates] = useState<InterviewTemplate[]>([]);
  const [results, setResults] = useState<InterviewResult[]>([]);
  const [form, setForm] = useState(initialForm);
  const [focusAreas, setFocusAreas] = useState<string[]>([]);
  const [focusAreaDraft, setFocusAreaDraft] = useState("");
  const [defaultQuestions, setDefaultQuestions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [viewDetail, setViewDetail] = useState<SessionDetail | null>(null);

  // Assignment state
  const [assignMode, setAssignMode] = useState<"users" | "batch">("users");
  const [assignTemplateId, setAssignTemplateId] = useState("");
  const [assignDays, setAssignDays] = useState(14);
  const [allUsers, setAllUsers] = useState<{ id: string; username: string; full_name: string }[]>([]);
  const [allBatches, setAllBatches] = useState<{ id: string; name: string }[]>([]);
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [assigning, setAssigning] = useState(false);
  const [userSearch, setUserSearch] = useState("");
  const [searchingUsers, setSearchingUsers] = useState(false);

  useEffect(() => {
    loadTemplates();
    loadResults();
    loadBatches();
  }, []);

  // Fetch users from server when search has 3+ chars
  useEffect(() => {
    if (userSearch.trim().length < 3) {
      setAllUsers([]);
      return;
    }
    const timeout = setTimeout(() => {
      searchUsers(userSearch.trim());
    }, 300);
    return () => clearTimeout(timeout);
  }, [userSearch]);

  async function loadTemplates() {
    try {
      const res = await api.get("/admin/interviews/templates");
      setTemplates(Array.isArray(res.data) ? res.data : []);
    } catch {
      // ignore
    }
  }

  async function loadResults() {
    try {
      const res = await api.get("/admin/interviews/results");
      setResults(Array.isArray(res.data) ? res.data : []);
    } catch {
      // ignore
    }
  }

  async function loadBatches() {
    try {
      const res = await api.get("/batches/");
      setAllBatches(Array.isArray(res.data) ? res.data : []);
    } catch {
      // ignore
    }
  }

  async function searchUsers(query: string) {
    setSearchingUsers(true);
    try {
      const res = await api.get(`/admin/users?search=${encodeURIComponent(query)}&page_size=50`);
      const data = res.data;
      const items = data && data.items ? data.items : Array.isArray(data) ? data : [];
      setAllUsers(items.map((u: { id: string; username: string; name?: string }) => ({ id: u.id, username: u.username, full_name: u.name || u.username })));
    } catch {
      setAllUsers([]);
    } finally {
      setSearchingUsers(false);
    }
  }

  async function assignInterview() {
    if (!assignTemplateId) {
      setMessage("Select a template to assign");
      return;
    }
    if (assignMode === "users" && selectedUserIds.length === 0) {
      setMessage("Select at least one user");
      return;
    }
    if (assignMode === "batch" && !selectedBatchId) {
      setMessage("Select a batch");
      return;
    }

    setAssigning(true);
    try {
      if (assignMode === "users") {
        const res = await api.post("/admin/interviews/assignments/users", {
          template_id: assignTemplateId,
          user_ids: selectedUserIds,
          days: assignDays,
        });
        setMessage(res.data?.message || "Assigned successfully");
      } else {
        const res = await api.post("/admin/interviews/assignments/batches", {
          template_id: assignTemplateId,
          batch_id: selectedBatchId,
          days: assignDays,
        });
        setMessage(res.data?.message || "Assigned successfully");
      }
      setSelectedUserIds([]);
      setSelectedBatchId("");
    } catch (err: any) {
      setMessage(err?.response?.data?.detail || "Failed to assign interview");
    } finally {
      setAssigning(false);
    }
  }

  const maxDefaultQuestions = Math.floor(form.question_count / 2);

  function addFocusArea() {
    const val = focusAreaDraft.trim();
    if (!val) return;
    if (focusAreas.includes(val)) { setFocusAreaDraft(""); return; }
    setFocusAreas((prev) => [...prev, val]);
    setFocusAreaDraft("");
  }

  function removeFocusArea(idx: number) {
    setFocusAreas((prev) => prev.filter((_, i) => i !== idx));
  }

  function addDefaultQuestion() {
    if (defaultQuestions.length >= maxDefaultQuestions) {
      setMessage(`Default questions cannot exceed ${maxDefaultQuestions} (50% of total questions)`);
      return;
    }
    setDefaultQuestions((prev) => [...prev, ""]);
  }

  function updateDefaultQuestion(idx: number, val: string) {
    setDefaultQuestions((prev) => prev.map((q, i) => (i === idx ? val : q)));
  }

  function removeDefaultQuestion(idx: number) {
    setDefaultQuestions((prev) => prev.filter((_, i) => i !== idx));
  }

  async function createTemplate() {
    if (!form.title.trim() || !form.role.trim()) {
      setMessage("Title and role are required");
      return;
    }
    const cleanQuestions = defaultQuestions.map((q) => q.trim()).filter(Boolean);
    if (cleanQuestions.length > maxDefaultQuestions) {
      setMessage(`Default questions cannot exceed ${maxDefaultQuestions} (50% of total questions)`);
      return;
    }

    setLoading(true);
    try {
      await api.post("/admin/interviews/templates", {
        ...form,
        focus_areas: focusAreas,
        default_questions_or_topics: cleanQuestions,
      });
      setMessage("Interview template created");
      setForm(initialForm);
      setFocusAreas([]);
      setFocusAreaDraft("");
      setDefaultQuestions([]);
      loadTemplates();
    } catch {
      setMessage("Failed to create interview template");
    } finally {
      setLoading(false);
    }
  }

  async function archiveTemplate(id: string, archived: boolean) {
    try {
      if (archived) {
        await api.post(`/admin/interviews/templates/${id}/unarchive`);
        setMessage("Template unarchived");
      } else {
        await api.post(`/admin/interviews/templates/${id}/archive`);
        setMessage("Template archived");
      }
      loadTemplates();
    } catch {
      setMessage("Failed to update template state");
    }
  }

  async function viewResults(sessionId: string) {
    try {
      const res = await api.get(`/admin/interviews/results/${sessionId}`);
      setViewDetail(res.data);
    } catch {
      setMessage("Failed to load session details");
    }
  }

  async function reenableSession(sessionId: string) {
    try {
      await api.post(`/admin/interviews/results/${sessionId}/reenable`);
      setMessage("Session re-enabled. User can now attempt again.");
      loadResults();
    } catch {
      setMessage("Failed to re-enable session");
    }
  }

  return (
    <div className="space-y-6">
      <div className={`${card} p-5`}>
        <h3 className="text-sm font-semibold mb-4">Create Interview Template</h3>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Template Title</span>
            <input
              className={inputClass}
              placeholder="Template title"
              value={form.title}
              onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))}
            />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Role</span>
            <input
              className={inputClass}
              placeholder="e.g. Backend Engineer"
              value={form.role}
              onChange={(e) => setForm((p) => ({ ...p, role: e.target.value }))}
            />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Experience Level</span>
            <select
              className={selectClass}
              value={form.experience_level}
              onChange={(e) => setForm((p) => ({ ...p, experience_level: e.target.value }))}
            >
              <option value="junior">Junior</option>
              <option value="mid">Mid</option>
              <option value="senior">Senior</option>
            </select>
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Difficulty</span>
            <select
              className={selectClass}
              value={form.difficulty}
              onChange={(e) => setForm((p) => ({ ...p, difficulty: e.target.value }))}
            >
              <option value="beginner">Beginner</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
            </select>
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Duration (Minutes)</span>
            <input
              className={inputClass}
              type="number"
              min={10}
              max={180}
              value={form.duration_minutes}
              onChange={(e) => setForm((p) => ({ ...p, duration_minutes: Number(e.target.value || 60) }))}
              placeholder="60"
            />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Question Count</span>
            <input
              className={inputClass}
              type="number"
              min={1}
              max={20}
              value={form.question_count}
              onChange={(e) => setForm((p) => ({ ...p, question_count: Number(e.target.value || 5) }))}
              placeholder="5"
            />
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Max Pauses Allowed</span>
            <input
              className={inputClass}
              type="number"
              min={0}
              max={10}
              value={form.max_pauses_allowed}
              onChange={(e) => setForm((p) => ({ ...p, max_pauses_allowed: Number(e.target.value || 3) }))}
              placeholder="3"
            />
          </label>
          <div className="col-span-2 block">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Topics To Cover</span>
            <div className="flex flex-wrap items-center gap-2 p-2 border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-white min-h-[38px]">
              {focusAreas.map((area, idx) => (
                <span key={idx} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                  {area}
                  <button type="button" onClick={() => removeFocusArea(idx)} className="ml-0.5 text-blue-500 hover:text-blue-800 font-bold leading-none">&times;</button>
                </span>
              ))}
              <input
                className="flex-1 min-w-[140px] outline-none text-sm bg-transparent placeholder:text-gray-400"
                placeholder={focusAreas.length ? "Add another topic..." : "Type a topic and press Enter"}
                value={focusAreaDraft}
                onChange={(e) => setFocusAreaDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault();
                    addFocusArea();
                  }
                }}
              />
            </div>
          </div>
          <div className="col-span-2 block">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium text-[var(--color-text-secondary)]">Default Questions (max {maxDefaultQuestions})</span>
              <button
                type="button"
                onClick={addDefaultQuestion}
                disabled={defaultQuestions.length >= maxDefaultQuestions}
                className="inline-flex items-center gap-1 h-6 px-2 text-xs font-medium rounded bg-blue-50 text-blue-700 hover:bg-blue-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <span className="text-sm leading-none">+</span> Add Question
              </button>
            </div>
            <div className="space-y-2">
              {defaultQuestions.map((q, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <input
                    className={`${inputClass} flex-1`}
                    placeholder={`Question ${idx + 1}`}
                    value={q}
                    onChange={(e) => updateDefaultQuestion(idx, e.target.value)}
                  />
                  <button
                    type="button"
                    onClick={() => removeDefaultQuestion(idx)}
                    className="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded text-red-500 hover:bg-red-50 hover:text-red-700 transition-colors"
                    title="Remove question"
                  >
                    &times;
                  </button>
                </div>
              ))}
              {defaultQuestions.length === 0 && (
                <p className="text-xs text-gray-400 italic">No default questions added. Click + to add up to {maxDefaultQuestions}.</p>
              )}
            </div>
          </div>
        </div>
        <div className="mt-4">
          <button className={btnPrimary} disabled={loading} onClick={createTemplate}>
            {loading ? "Creating..." : "Create Template"}
          </button>
        </div>
      </div>

      <div className={`${card} overflow-hidden`}>
        <div className="px-5 py-4 border-b border-[var(--color-border)]">
          <h3 className="text-sm font-semibold">Interview Templates</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] bg-gray-50/50">
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Title</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Role</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Level</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Difficulty</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Questions</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Duration</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Max Pauses</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Topics / Defaults</th>
              <th className="text-right px-5 py-3 font-medium text-[var(--color-text-secondary)]">Actions</th>
            </tr>
          </thead>
          <tbody>
            {templates.map((t) => (
              <tr key={t.id} className="border-b border-[var(--color-border)] last:border-0">
                <td className="px-5 py-3.5 font-medium">{t.title}</td>
                <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.role}</td>
                <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.experience_level}</td>
                <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.difficulty}</td>
                <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.question_count}</td>
                <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.duration_minutes} min</td>
                <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{t.max_pauses_allowed}</td>
                <td className="px-5 py-3.5 text-xs text-[var(--color-text-secondary)]">
                  <div className="inline-flex gap-2">
                    <span
                      className="cursor-default underline decoration-dotted"
                      title={(t.focus_areas || []).join("\n")}
                    >
                      {(t.focus_areas || []).length} topic(s)
                    </span>
                    <span
                      className="cursor-default underline decoration-dotted"
                      title={(t.default_questions_or_topics || []).join("\n")}
                    >
                      {(t.default_questions_or_topics || []).length} default(s)
                    </span>
                  </div>
                </td>
                <td className="px-5 py-3.5 text-right">
                  <button
                    onClick={() => archiveTemplate(t.id, t.is_archived)}
                    className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-gray-100 text-[var(--color-text)] hover:bg-gray-200 cursor-pointer transition-colors"
                  >
                    {t.is_archived ? "Unarchive" : "Archive"}
                  </button>
                </td>
              </tr>
            ))}
            {templates.length === 0 && (
              <tr>
                <td colSpan={9} className="px-5 py-8 text-center text-[var(--color-text-secondary)]">No templates created yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Assign Interview Section */}
      <div className={`${card} p-5`}>
        <h3 className="text-sm font-semibold mb-4">Assign Interview to Users / Batch</h3>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Template</span>
            <select
              className={selectClass}
              value={assignTemplateId}
              onChange={(e) => setAssignTemplateId(e.target.value)}
            >
              <option value="">Select template...</option>
              {templates.filter((t) => !t.is_archived).map((t) => (
                <option key={t.id} value={t.id}>{t.title}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Deadline (Days)</span>
            <input
              className={inputClass}
              type="number"
              min={1}
              max={30}
              value={assignDays}
              onChange={(e) => setAssignDays(Number(e.target.value) || 14)}
            />
          </label>
          <div className="col-span-2">
            <div className="flex items-center gap-4 mb-3">
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="assignMode"
                  checked={assignMode === "users"}
                  onChange={() => setAssignMode("users")}
                  className="accent-[var(--color-primary)]"
                />
                <span className="text-xs font-medium">Assign to Users</span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer">
                <input
                  type="radio"
                  name="assignMode"
                  checked={assignMode === "batch"}
                  onChange={() => setAssignMode("batch")}
                  className="accent-[var(--color-primary)]"
                />
                <span className="text-xs font-medium">Assign to Batch</span>
              </label>
            </div>

            {assignMode === "users" && (
              <div>
                <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">
                  Select Users ({selectedUserIds.length} selected)
                </span>
                {/* Selected user chips */}
                {selectedUserIds.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {selectedUserIds.map((uid) => {
                      const user = allUsers.find((u) => u.id === uid);
                      return (
                        <span key={uid} className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                          {user?.full_name || user?.username || uid}
                          <button
                            type="button"
                            onClick={() => setSelectedUserIds((prev) => prev.filter((id) => id !== uid))}
                            className="ml-0.5 text-blue-500 hover:text-blue-800 font-bold leading-none"
                          >&times;</button>
                        </span>
                      );
                    })}
                  </div>
                )}
                {/* Search input */}
                <div className="relative">
                  <input
                    className={inputClass}
                    placeholder="Type 3+ characters to search users..."
                    value={userSearch}
                    onChange={(e) => setUserSearch(e.target.value)}
                  />
                  {userSearch.trim().length > 0 && userSearch.trim().length < 3 && (
                    <p className="text-xs text-gray-400 mt-1">Type at least 3 characters to search</p>
                  )}
                  {searchingUsers && (
                    <p className="text-xs text-blue-500 mt-1">Searching...</p>
                  )}
                  {userSearch.trim().length >= 3 && !searchingUsers && (
                    <div className="absolute z-10 left-0 right-0 top-full mt-1 border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-white shadow-lg max-h-40 overflow-auto">
                      {allUsers
                        .filter((u) => !selectedUserIds.includes(u.id))
                        .slice(0, 20)
                        .map((u) => (
                          <button
                            key={u.id}
                            type="button"
                            onClick={() => {
                              setSelectedUserIds((prev) => [...prev, u.id]);
                              setUserSearch("");
                            }}
                            className="w-full text-left px-3 py-2 text-xs hover:bg-blue-50 cursor-pointer flex items-center justify-between"
                          >
                            <span>{u.full_name || u.username}</span>
                            <span className="text-gray-400">{u.username}</span>
                          </button>
                        ))}
                      {allUsers.filter((u) => !selectedUserIds.includes(u.id)).length === 0 && (
                        <p className="text-xs text-gray-400 text-center py-2">No matching users</p>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}

            {assignMode === "batch" && (
              <label className="block">
                <span className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1">Select Batch</span>
                <select
                  className={selectClass}
                  value={selectedBatchId}
                  onChange={(e) => setSelectedBatchId(e.target.value)}
                >
                  <option value="">Select batch...</option>
                  {allBatches.map((b) => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </div>
        <div className="mt-4">
          <button className={btnPrimary} disabled={assigning} onClick={assignInterview}>
            {assigning ? "Assigning..." : "Assign Interview"}
          </button>
        </div>
      </div>

      <div className={`${card} overflow-hidden`}>
        <div className="px-5 py-4 border-b border-[var(--color-border)]">
          <h3 className="text-sm font-semibold">Interview Results</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] bg-gray-50/50">
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Template</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Status</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Attempt</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Pauses</th>
              <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Score</th>
              <th className="text-right px-5 py-3 font-medium text-[var(--color-text-secondary)]">Actions</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr key={r.id} className="border-b border-[var(--color-border)] last:border-0">
                <td className="px-5 py-3.5 font-medium">{r.template_title}</td>
                <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{r.status}</td>
                <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{r.attempt_number}</td>
                <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{r.pause_count}/{r.max_pauses_allowed}</td>
                <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{r.total_score ?? "-"}</td>
                <td className="px-5 py-3.5 text-right space-x-2">
                  <button
                    onClick={() => viewResults(r.id)}
                    className="inline-flex items-center h-7 px-2.5 text-xs font-medium rounded-[var(--radius-sm)] bg-blue-50 text-blue-700 hover:bg-blue-100 cursor-pointer transition-colors"
                  >
                    View Results
                  </button>
                  {r.status === "missed" && (
                    <button
                      onClick={() => reenableSession(r.id)}
                      className="inline-flex items-center h-7 px-2.5 text-xs font-medium rounded-[var(--radius-sm)] bg-green-50 text-green-700 hover:bg-green-100 cursor-pointer transition-colors"
                    >
                      Re-enable
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {results.length === 0 && (
              <tr>
                <td colSpan={6} className="px-5 py-8 text-center text-[var(--color-text-secondary)]">No interview sessions yet.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Results Detail Modal */}
      {viewDetail && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl max-w-3xl w-full max-h-[85vh] overflow-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between sticky top-0 bg-white">
              <h3 className="font-semibold text-lg">{viewDetail.template_title} — Results</h3>
              <button onClick={() => setViewDetail(null)} className="text-gray-500 hover:text-gray-800 text-xl">&times;</button>
            </div>
            <div className="p-6 space-y-6">
              {/* Summary */}
              <div className="flex items-center gap-6">
                <div className="text-center">
                  <div className="text-2xl font-bold text-blue-700">{viewDetail.total_score ?? "-"}</div>
                  <div className="text-xs text-gray-500">Overall Score</div>
                </div>
                <div className="text-sm text-gray-700">{viewDetail.summary || "No summary available."}</div>
              </div>

              {/* Topic Scores */}
              {viewDetail.topic_scores.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2">Topic Scores</h4>
                  <div className="grid grid-cols-2 gap-2">
                    {viewDetail.topic_scores.map((ts) => (
                      <div key={ts.topic} className="flex items-center justify-between bg-gray-50 rounded-lg px-3 py-2">
                        <span className="text-sm font-medium capitalize">{ts.topic}</span>
                        <span className="text-sm text-blue-700 font-bold">{ts.avg_score}/10 <span className="text-xs text-gray-500">({ts.turns} turns)</span></span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Per-turn evaluations */}
              {viewDetail.evaluations.length > 0 && (
                <div>
                  <h4 className="text-sm font-semibold mb-2">Per-Turn Evaluations</h4>
                  <div className="space-y-3">
                    {viewDetail.evaluations.map((ev) => (
                      <div key={ev.turn_index} className="border border-gray-200 rounded-lg p-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-medium text-gray-600">Turn {ev.turn_index} — {ev.focus_area}</span>
                          <span className="text-xs font-bold text-blue-700">{ev.score !== null ? `${ev.score}/10` : "-"}</span>
                        </div>
                        <p className="text-sm text-gray-800 mb-1">{ev.user_response}</p>
                        {ev.feedback && <p className="text-xs text-gray-600 italic">{ev.feedback}</p>}
                        {ev.strengths.length > 0 && <p className="text-xs text-green-700 mt-1">✓ {ev.strengths.join(", ")}</p>}
                        {ev.improvements.length > 0 && <p className="text-xs text-orange-700">↑ {ev.improvements.join(", ")}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
