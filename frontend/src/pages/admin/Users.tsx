import { useEffect, useState } from "react";
import api from "../../api";
import type { UserInfo, BatchInfo } from "./types";
import { card } from "./types";
import CircularProgress from "../../components/CircularProgress";

interface Props {
  users: UserInfo[];
  batches: BatchInfo[];
  setMessage: (msg: string) => void;
  reloadUsers: () => void;
}

interface UserPerformanceReport {
  user_id: string;
  user_name: string;
  username: string;
  email: string;
  total_assessments: number;
  completed_assessments: number;
  average_score: number | null;
  topic_performance: Array<{
    topic_name: string;
    average_percentage: number;
    assessment_count: number;
  }>;
  improvement_areas: string[];
}

export default function Users({ users: initialUsers, batches, setMessage, reloadUsers }: Props) {
  const [searchQuery, setSearchQuery] = useState("");
  const [filteredUsers, setFilteredUsers] = useState(initialUsers);
  const [pageSize, setPageSize] = useState(10);
  const [currentPage, setCurrentPage] = useState(1);
  const [showDetailModal, setShowDetailModal] = useState(false);
  const [selectedUserPerformance, setSelectedUserPerformance] = useState<UserPerformanceReport | null>(null);
  const [loadingPerformance, setLoadingPerformance] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingUser, setEditingUser] = useState<UserInfo | null>(null);
  const [editAccount, setEditAccount] = useState("");
  const [editBatchIds, setEditBatchIds] = useState<string[]>([]);
  const [editName, setEditName] = useState("");
  const [editUsername, setEditUsername] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editContactEmail, setEditContactEmail] = useState("");
  const [editIsActive, setEditIsActive] = useState(true);
  const [batchSearch, setBatchSearch] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setFilteredUsers(initialUsers), 0);
    return () => clearTimeout(t);
  }, [initialUsers]);

  // Handle search
  const handleSearch = () => {
    const query = searchQuery.toLowerCase();
    const filtered = initialUsers.filter(
      (u) =>
        u.name.toLowerCase().includes(query) ||
        u.username.toLowerCase().includes(query) ||
        u.email.toLowerCase().includes(query)
    );
    setFilteredUsers(filtered);
    setCurrentPage(1);
  };

  // Handle pagination
  const totalPages = Math.ceil(filteredUsers.length / pageSize);
  const paginatedUsers = filteredUsers.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );

  // Handle page size change
  const handlePageSizeChange = (newSize: number) => {
    setPageSize(newSize);
    setCurrentPage(1);
  };

  // View user performance
  const handleViewPerformance = async (userId: string) => {
    setLoadingPerformance(true);
    try {
      const res = await api.get(`/admin/user/${userId}/performance`);
      setSelectedUserPerformance(res.data);
      setShowDetailModal(true);
    } catch (err: unknown) {
      console.error(err);
      alert("Failed to load user performance");
    } finally {
      setLoadingPerformance(false);
    }
  };

  // (Activation now handled in Edit modal)

  // Open edit modal
  const handleEditUser = async (user: UserInfo) => {
    setEditingUser(user);
    setEditAccount(user.account || "");
    setEditName(user.name || "");
    setEditUsername(user.username || "");
    setEditEmail(user.email || "");
    setEditContactEmail(user.contact_email || "");
    setEditIsActive(!!user.is_active);
    setBatchSearch("");
    try {
      const res = await api.get(`/admin/users/${user.id}/batches`);
      setEditBatchIds(res.data.batch_ids);
    } catch {
      setEditBatchIds([]);
    }
    setShowEditModal(true);
  };

  // Save user edits
  const handleSaveEdit = async () => {
    if (!editingUser) return;
    setSavingEdit(true);
    try {
      const payload = {
        account: editAccount,
        name: editName,
        username: editUsername,
        email: editEmail,
        contact_email: editContactEmail,
        is_active: editIsActive,
      };
      await api.patch(`/admin/users/${editingUser.id}`, payload);
      await api.put(`/admin/users/${editingUser.id}/batches`, { batch_ids: editBatchIds });
      setMessage(`User '${editUsername || editingUser.username}' updated successfully.`);
      setShowEditModal(false);
      reloadUsers();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to update user");
    } finally {
      setSavingEdit(false);
    }
  };

  // Open password modal
  const handleOpenPasswordModal = (user: UserInfo) => {
    setEditingUser(user);
    setNewPassword("");
    setConfirmPassword("");
    setShowPasswordModal(true);
  };

  // Save password
  const handleSavePassword = async () => {
    if (!editingUser) return;
    if (!newPassword || newPassword.length < 6) {
      setMessage("Password must be at least 6 characters");
      return;
    }
    if (newPassword !== confirmPassword) {
      setMessage("Passwords do not match");
      return;
    }
    setSavingPassword(true);
    try {
      await api.patch(`/admin/users/${editingUser.id}/password`, { password: newPassword });
      setMessage("Password updated successfully.");
      setShowPasswordModal(false);
      reloadUsers();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to update password");
    } finally {
      setSavingPassword(false);
    }
  };

  const filteredBatches = batches.filter(
    (b) => !editBatchIds.includes(b.id) && b.name.toLowerCase().includes(batchSearch.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* User Performance Modal */}
      {showDetailModal && selectedUserPerformance && (
        <div className="fixed inset-0 z-50 overflow-auto flex items-start md:items-center justify-center bg-black/60">
          <div className="bg-white rounded-lg shadow-2xl max-w-3xl w-full max-h-[90vh] mx-4 my-6 overflow-y-auto">
            <div className="sticky top-0 bg-white px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">{selectedUserPerformance.user_name}</h3>
                <p className="text-sm text-gray-500">@{selectedUserPerformance.username}</p>
              </div>
              <button
                onClick={() => setShowDetailModal(false)}
                className="text-gray-500 hover:text-gray-700"
              >
                ✕
              </button>
            </div>
            <div className="p-6 space-y-6">
              {/* Overall Stats */}
              <div className="grid grid-cols-3 gap-4">
                <div className="border border-gray-200 rounded-lg p-4 text-center">
                  <p className="text-sm text-gray-600">Assessments Taken</p>
                  <p className="text-2xl font-bold text-gray-900">{selectedUserPerformance.completed_assessments}/{selectedUserPerformance.total_assessments}</p>
                </div>
                <div className="border border-gray-200 rounded-lg p-4 text-center">
                  <p className="text-sm text-gray-600">Average Score</p>
                  <p className={`text-2xl font-bold ${
                    selectedUserPerformance.average_score !== null && selectedUserPerformance.average_score >= 70
                      ? "text-green-600"
                      : selectedUserPerformance.average_score !== null && selectedUserPerformance.average_score >= 40
                      ? "text-yellow-600"
                      : "text-red-600"
                  }`}>
                    {selectedUserPerformance.average_score !== null ? `${selectedUserPerformance.average_score}%` : "—"}
                  </p>
                </div>
                <div className="border border-gray-200 rounded-lg p-4 text-center">
                  <p className="text-sm text-gray-600">Topics Covered</p>
                  <p className="text-2xl font-bold text-gray-900">{selectedUserPerformance.topic_performance.length}</p>
                </div>
              </div>

              {/* Topic Performance */}
              {selectedUserPerformance.topic_performance.length > 0 && (
                <div>
                  <h4 className="font-semibold text-gray-900 mb-4">Topic-wise Performance</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-6 place-items-center">
                    {selectedUserPerformance.topic_performance.map((tp, idx) => (
                      <div key={idx} className="flex flex-col items-center">
                        <CircularProgress
                          percentage={tp.average_percentage}
                          label={`${tp.topic_name}\n(${tp.assessment_count} test)`}
                          size={130}
                          strokeWidth={9}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Improvement Suggestions */}
              {selectedUserPerformance.topic_performance.length > 0 ? (
                <div>
                  <h4 className="font-semibold text-gray-900 mb-3">Improvement Suggestions</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {selectedUserPerformance.topic_performance.map((tp, idx) => {
                      const pct = Math.round(tp.average_percentage ?? 0);
                      let title: string;
                      let desc: string;
                      let from: string;
                      let to: string;
                      let border: string;
                      let emoji: string;

                      if (pct < 50) {
                        title = "Needs significant improvement";
                        desc = "Below 50% — Focus on fundamentals, revisit core concepts, and practice basic problems regularly.";
                        from = "from-red-50";
                        to = "to-red-100";
                        border = "border-red-200";
                        emoji = "⚠️";
                      } else if (pct < 70) {
                        title = "Some improvement needed";
                        desc = "50–69% — Strengthen weak areas with targeted practice and review mistakes from past assessments.";
                        from = "from-amber-50";
                        to = "to-orange-50";
                        border = "border-amber-200";
                        emoji = "🟠";
                      } else if (pct < 90) {
                        title = "Good — minor gaps";
                        desc = "70–89% — Good understanding. Do timed practice and review edge-case questions to reach mastery.";
                        from = "from-yellow-50";
                        to = "to-green-50";
                        border = "border-yellow-200";
                        emoji = "🟡";
                      } else {
                        title = "Excellent";
                        desc = "90%+ — Strong mastery. Challenge yourself with advanced problems and apply concepts in projects.";
                        from = "from-green-50";
                        to = "to-green-100";
                        border = "border-green-200";
                        emoji = "✅";
                      }

                      return (
                        <div key={idx} className={`p-4 bg-gradient-to-r ${from} ${to} ${border} rounded-lg flex items-start gap-3 border`}>
                          <div className="text-2xl">{emoji}</div>
                          <div>
                            <p className="text-sm font-medium text-gray-900">{tp.topic_name} — {pct}%</p>
                            <p className="text-xs text-gray-600 mt-1">{title}</p>
                            <p className="text-xs text-gray-600 mt-1">{desc}</p>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : selectedUserPerformance.improvement_areas.length > 0 && (
                <div>
                  <h4 className="font-semibold text-gray-900 mb-3">Improvement Suggestions</h4>
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-2">
                    {selectedUserPerformance.improvement_areas.map((suggestion, idx) => (
                      <div key={idx} className="flex items-start gap-2">
                        <span className="text-blue-600 mt-0.5">•</span>
                        <span className="text-sm text-blue-900">{suggestion}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Edit User Modal */}
      {showEditModal && editingUser && (
        <div className="fixed inset-0 z-50 overflow-auto flex items-start md:items-center justify-center bg-black/60">
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-lg max-h-[90vh] mx-4 my-6 overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">Edit User</h3>
                <p className="text-sm text-gray-500">{editingUser.name} (@{editingUser.username})</p>
              </div>
              <button onClick={() => setShowEditModal(false)} className="text-gray-500 hover:text-gray-700 cursor-pointer">✕</button>
            </div>
            <div className="p-6 space-y-5">
              {/* Name */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                <input
                  type="text"
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  placeholder="Full name"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>

              {/* Username */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  type="text"
                  value={editUsername}
                  onChange={(e) => setEditUsername(e.target.value)}
                  placeholder="username"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>

              {/* Email */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input
                  type="email"
                  value={editEmail}
                  onChange={(e) => setEditEmail(e.target.value)}
                  placeholder="email@example.com"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>

              {/* Contact Email */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Contact Email</label>
                <input
                  type="email"
                  value={editContactEmail}
                  onChange={(e) => setEditContactEmail(e.target.value)}
                  placeholder="email@example.com"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>

              {/* Status */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
                <select
                  value={editIsActive ? "active" : "inactive"}
                  onChange={(e) => setEditIsActive(e.target.value === "active")}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
                >
                  <option value="active">Active</option>
                  <option value="inactive">Inactive</option>
                </select>
              </div>

              {/* Account field */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Account</label>
                <input
                  type="text"
                  value={editAccount}
                  onChange={(e) => setEditAccount(e.target.value)}
                  placeholder="Enter account name..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>

              {/* Batches */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Batches</label>
                {/* Selected batches as chips */}
                <div className="flex flex-wrap gap-2 mb-2 min-h-[32px]">
                  {editBatchIds.map((bid) => {
                    const batch = batches.find((b) => b.id === bid);
                    return (
                      <span key={bid} className="inline-flex items-center gap-1 px-2.5 py-1 bg-blue-50 text-blue-700 rounded-full text-xs font-medium">
                        {batch?.name || bid}
                        <button
                          onClick={() => setEditBatchIds((prev) => prev.filter((id) => id !== bid))}
                          className="hover:text-blue-900 cursor-pointer"
                        >
                          ×
                        </button>
                      </span>
                    );
                  })}
                </div>
                {/* Batch search + dropdown */}
                <input
                  type="text"
                  value={batchSearch}
                  onChange={(e) => setBatchSearch(e.target.value)}
                  placeholder="Search batches to add..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
                />
                {batchSearch && filteredBatches.length > 0 && (
                  <div className="mt-1 border border-gray-200 rounded-lg max-h-32 overflow-auto">
                    {filteredBatches.map((b) => (
                      <button
                        key={b.id}
                        onClick={() => {
                          setEditBatchIds((prev) => [...prev, b.id]);
                          setBatchSearch("");
                        }}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 cursor-pointer"
                      >
                        {b.name}
                      </button>
                    ))}
                  </div>
                )}
                {batchSearch && filteredBatches.length === 0 && (
                  <p className="mt-1 text-xs text-gray-500">No matching batches</p>
                )}
              </div>
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
              <button
                onClick={() => setShowEditModal(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={savingEdit}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 cursor-pointer"
              >
                {savingEdit ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Change Password Modal */}
      {showPasswordModal && editingUser && (
        <div className="fixed inset-0 z-50 overflow-auto flex items-start md:items-center justify-center bg-black/60">
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-md max-h-[90vh] mx-4 my-6 overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">Change Password</h3>
                <p className="text-sm text-gray-500">{editingUser.name} (@{editingUser.username})</p>
              </div>
              <button onClick={() => setShowPasswordModal(false)} className="text-gray-500 hover:text-gray-700 cursor-pointer">✕</button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">New Password</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Enter new password"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Confirm Password</label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Confirm new password"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>
              <p className="text-xs text-gray-500">Password must be at least 6 characters.</p>
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
              <button
                onClick={() => setShowPasswordModal(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleSavePassword}
                disabled={savingPassword}
                className="px-4 py-2 text-sm font-medium text-white bg-yellow-600 rounded-lg hover:bg-yellow-700 disabled:opacity-50 cursor-pointer"
              >
                {savingPassword ? "Saving..." : "Save Password"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Search and Pagination Controls */}
      <div className={`${card} p-5 space-y-4`}>
        <div className="flex gap-3">
          <input
            type="text"
            placeholder="Search by name, username, or email..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:border-blue-500 focus:outline-none"
          />
          <button
            onClick={handleSearch}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 cursor-pointer"
          >
            Search
          </button>
        </div>

        {searchQuery && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-600">
              Found {filteredUsers.length} user{filteredUsers.length !== 1 ? "s" : ""}
            </span>
            <button
              onClick={() => {
                setSearchQuery("");
                setFilteredUsers(initialUsers);
                setCurrentPage(1);
              }}
              className="text-blue-600 hover:text-blue-700 text-xs"
            >
              Clear search
            </button>
          </div>
        )}
      </div>

      {/* Users Table */}
      {paginatedUsers.length === 0 ? (
        <div className={`${card} p-12 text-center`}>
          <p className="text-[var(--color-text-secondary)] text-sm">
            {filteredUsers.length === 0 && searchQuery ? "No users match your search." : "No users yet."}
          </p>
        </div>
      ) : (
        <div className={`${card} overflow-hidden`}>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] bg-gray-50/50">
                <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Name</th>
                <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Username</th>
                <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Email</th>
                <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Account</th>
                <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Status</th>
                <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedUsers.map((u) => (
                <tr key={u.id} className="border-b border-[var(--color-border)] last:border-0 hover:bg-gray-50/50 transition-colors">
                  <td className="px-5 py-3.5 font-medium">{u.name}</td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{u.username}</td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{u.email}</td>
                  <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{u.account || "—"}</td>
                  <td className="px-5 py-3.5">
                    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                      u.is_active ? "text-[var(--color-success)]" : "text-[var(--color-danger)]"
                    }`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${u.is_active ? "bg-[var(--color-success)]" : "bg-[var(--color-danger)]"}`} />
                      {u.is_active ? "Active" : "Inactive"}
                    </span>
                  </td>
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleViewPerformance(u.id)}
                        disabled={loadingPerformance}
                        className="text-blue-600 hover:text-blue-700 text-xs font-medium disabled:opacity-50 cursor-pointer"
                      >
                        Report
                      </button>
                      <button
                        onClick={() => handleEditUser(u)}
                        className="text-indigo-600 hover:text-indigo-700 text-xs font-medium cursor-pointer"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => handleOpenPasswordModal(u)}
                        className="text-yellow-600 hover:text-yellow-700 text-xs font-medium cursor-pointer"
                      >
                        Password
                      </button>
                      
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination Controls */}
      {filteredUsers.length > 0 && (
        <div className={`${card} p-5 flex items-center justify-between`}>
          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-600">
              Showing {(currentPage - 1) * pageSize + 1} to {Math.min(currentPage * pageSize, filteredUsers.length)} of {filteredUsers.length}
            </span>
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-600">Per page:</label>
              <select
                value={pageSize}
                onChange={(e) => handlePageSizeChange(Number(e.target.value))}
                className="px-2 py-1 border border-gray-300 rounded text-sm cursor-pointer"
              >
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
              </select>
            </div>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
              className="px-3 py-1.5 border border-gray-300 rounded text-sm hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
            >
              Previous
            </button>
            <div className="flex items-center gap-1">
              {Array.from({ length: totalPages }, (_, i) => i + 1).map((page) => (
                <button
                  key={page}
                  onClick={() => setCurrentPage(page)}
                  className={`w-8 h-8 rounded text-sm font-medium cursor-pointer ${
                    currentPage === page
                      ? "bg-blue-600 text-white"
                      : "border border-gray-300 hover:bg-gray-50"
                  }`}
                >
                  {page}
                </button>
              ))}
            </div>
            <button
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
              className="px-3 py-1.5 border border-gray-300 rounded text-sm hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
