import { useState, useRef } from "react";
import api from "../../api";
import type { BatchInfo, UserInfo } from "./types";
import { card, inputClass, btnPrimary } from "./types";

interface Props {
  batches: BatchInfo[];
  users: UserInfo[];
  setMessage: (msg: string) => void;
  reloadBatches: () => void;
}

export default function Batches({ batches, users, setMessage, reloadBatches }: Props) {
  const extractError = (err: unknown, fallback: string) => {
    const anyErr = err as any;
    try {
      if (anyErr?.response?.data) {
        const data = anyErr.response.data;
        if (typeof data.detail === "string") return data.detail;
        if (Array.isArray(data.detail)) return data.detail.join(", ");
        if (typeof data.message === "string") return data.message;
        if (typeof data === "string") return data;
        // sometimes fastapi returns { detail: { ... } }
        return JSON.stringify(data);
      }
      if (anyErr?.message) return anyErr.message;
    } catch (e) {
      // ignore parsing errors
    }
    return fallback;
  };
  const [batchName, setBatchName] = useState("");
  const [batchDesc, setBatchDesc] = useState("");
  const [batchStatus, setBatchStatus] = useState<"current" | "upcoming" | "completed">("current");
  const [creating, setCreating] = useState(false);
  const [uploadBatchName, setUploadBatchName] = useState("");
  const [newUploadBatchName, setNewUploadBatchName] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<{
    batch_name: string;
    total_rows: number;
    users_created: number;
    users_added: number;
    skipped: number;
    errors: string[];
  } | null>(null);
  const [managingBatchId, setManagingBatchId] = useState<string | null>(null);
  const [userSearch, setUserSearch] = useState("");
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [addingUsers, setAddingUsers] = useState(false);
  const [deletingBatchId, setDeletingBatchId] = useState<string | null>(null);
  const [deletingInProgress, setDeletingInProgress] = useState(false);
  const [restoringBatchId, setRestoringBatchId] = useState<string | null>(null);
  const [restoringInProgress, setRestoringInProgress] = useState(false);
  const [editingBatchId, setEditingBatchId] = useState<string | null>(null);
  const [editBatchName, setEditBatchName] = useState("");
  const [editBatchDesc, setEditBatchDesc] = useState("");
  const [editBatchStatus, setEditBatchStatus] = useState<"current" | "upcoming" | "completed">("current");
  const [editingInProgress, setEditingInProgress] = useState(false);

  const selectableUsers = users.filter((user) => user.role === "user" && user.is_active);
  const selectedUsers = selectableUsers.filter((user) => selectedUserIds.includes(user.id));
  const userQuery = userSearch.trim().toLowerCase();
  const userSuggestions = selectableUsers
    .filter((user) => !selectedUserIds.includes(user.id))
    .filter((user) => {
      if (!userQuery) return true;
      return (
        user.name.toLowerCase().includes(userQuery) ||
        user.username.toLowerCase().includes(userQuery) ||
        user.email.toLowerCase().includes(userQuery)
      );
    })
    .slice(0, 8);

  const handleCreateBatch = async () => {
    if (!batchName.trim()) {
      setMessage("Batch name is required");
      return;
    }
    setCreating(true);
    try {
      await api.post("/batches/create", {
        name: batchName.trim(),
        description: batchDesc.trim(),
        status: batchStatus,
      });
      setMessage(`Batch "${batchName.trim()}" created`);
      setBatchName("");
      setBatchDesc("");
      setBatchStatus("current");
      reloadBatches();
    } catch (err: unknown) {
      console.error(err);
      setMessage(extractError(err, "Failed to create batch"));
    } finally {
      setCreating(false);
    }
  };

  const handleUpload = async () => {
    const batchToUse = uploadBatchName === "__create_new__" ? newUploadBatchName.trim() : uploadBatchName.trim();
    if (!selectedFile || !batchToUse) {
      setMessage("Please select an existing batch or enter a new batch name, and choose an Excel file");
      return;
    }
    setUploading(true);
    setUploadResult(null);
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const res = await api.post(
        `/batches/upload?batch_name=${encodeURIComponent(batchToUse)}`,
        formData,
        { headers: { "Content-Type": "multipart/form-data" } }
      );
      setUploadResult(res.data);
      setMessage(`Batch "${res.data.batch_name}": ${res.data.users_created} users created, ${res.data.users_added} added to batch`);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setSelectedFile(null);
      setUploadBatchName("");
      setNewUploadBatchName("");
      reloadBatches();
    } catch (err: unknown) {
      console.error(err);
      setMessage(extractError(err, "Upload failed"));
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteBatch = async (id: string) => {
    try {
      const res = await api.delete(`/batches/${id}`);
      setMessage(res.data.message);
      reloadBatches();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to delete batch");
    }
  };

  const handleRestoreBatch = async (id: string) => {
    setRestoringBatchId(id);
    setRestoringInProgress(true);
    try {
      const res = await api.post(`/batches/${id}/restore`);
      setMessage(res.data.message);
      reloadBatches();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to restore batch");
    } finally {
      setRestoringBatchId(null);
      setRestoringInProgress(false);
    }
  };

  const confirmDelete = async () => {
    if (!deletingBatchId) return;
    setDeletingInProgress(true);
    try {
      await handleDeleteBatch(deletingBatchId);
      setDeletingBatchId(null);
    } finally {
      setDeletingInProgress(false);
    }
  };

  const toggleManageBatch = (batchId: string) => {
    setManagingBatchId((prev) => (prev === batchId ? null : batchId));
    setSelectedUserIds([]);
    setUserSearch("");
  };

  const openEditBatch = (batch: BatchInfo) => {
    setEditingBatchId(batch.id);
    setEditBatchName(batch.name || "");
    setEditBatchDesc(batch.description || "");
    setEditBatchStatus((batch.status === "current" || batch.status === "upcoming" || batch.status === "completed") ? (batch.status as "current" | "upcoming" | "completed") : "current");
  };

  const handleSaveEdit = async () => {
    if (!editingBatchId) return;
    setEditingInProgress(true);
    try {
      const res = await api.put(`/batches/${editingBatchId}`, {
        name: editBatchName.trim(),
        description: editBatchDesc.trim(),
        status: editBatchStatus,
      });
      setMessage(`Batch "${res.data.name}" updated`);
      setEditingBatchId(null);
      reloadBatches();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to update batch");
    } finally {
      setEditingInProgress(false);
    }
  };

  const addUserToSelection = (userId: string) => {
    setSelectedUserIds((prev) => (prev.includes(userId) ? prev : [...prev, userId]));
    setUserSearch("");
  };

  const removeUserFromSelection = (userId: string) => {
    setSelectedUserIds((prev) => prev.filter((id) => id !== userId));
  };

  const handleAddExistingUsers = async () => {
    if (!managingBatchId) return;
    if (selectedUserIds.length === 0) {
      setMessage("Select at least one existing user to add");
      return;
    }

    setAddingUsers(true);
    try {
      const res = await api.post(`/batches/${managingBatchId}/users`, {
        user_ids: selectedUserIds,
      });
      setMessage(
        `Batch "${res.data.batch_name}": ${res.data.added} user(s) added${res.data.skipped ? `, ${res.data.skipped} skipped` : ""}`
      );
      setSelectedUserIds([]);
      setUserSearch("");
      reloadBatches();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to add users to batch");
    } finally {
      setAddingUsers(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Create Batch */}
      <div className={`${card} p-6`}>
        <h2 className="text-sm font-semibold mb-4">Create Batch</h2>
        <div className="flex gap-3 items-end flex-wrap">
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Batch Name</label>
            <input
              type="text"
              value={batchName}
              onChange={(e) => setBatchName(e.target.value)}
              placeholder="e.g. Batch 2025-A"
              className={`${inputClass} w-56`}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Description (optional)</label>
            <input
              type="text"
              value={batchDesc}
              onChange={(e) => setBatchDesc(e.target.value)}
              placeholder="Brief description"
              className={`${inputClass} w-64`}
            />
          </div>
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Status</label>
              <select
                  value={batchStatus}
                  onChange={(e) => setBatchStatus(e.target.value as "current" | "upcoming" | "completed")}
                  className={`${inputClass} w-40`}
                >
                <option value="current">Current</option>
                <option value="upcoming">Upcoming</option>
                <option value="completed">Completed</option>
              </select>
            </div>
          <button onClick={handleCreateBatch} disabled={creating} className={btnPrimary}>
            {creating ? "Creating..." : "Create"}
          </button>
        </div>
      </div>

      {/* Upload Users to Batch */}
      <div className={`${card} p-6`}>
        <h2 className="text-sm font-semibold mb-1">Upload Users via Excel</h2>
        <p className="text-xs text-[var(--color-text-secondary)] mb-5">
          Required columns: name, username, email, password. Optional: account
        </p>
        <div className="flex gap-3 items-end flex-wrap">
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Batch</label>
            <div className="flex items-center gap-2">
              <select
                value={uploadBatchName}
                onChange={(e) => setUploadBatchName(e.target.value)}
                className={`${inputClass} w-56`}
              >
                <option value="">Select existing batch...</option>
                {batches.map((b) => (
                  <option key={b.id} value={b.name}>{b.name}</option>
                ))}
                <option value="__create_new__">+ Create new batch</option>
              </select>

              {uploadBatchName === "__create_new__" && (
                <input
                  type="text"
                  value={newUploadBatchName}
                  onChange={(e) => setNewUploadBatchName(e.target.value)}
                  placeholder="Enter new batch name"
                  className={`${inputClass} w-56`}
                />
              )}
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Excel File (.xlsx)</label>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xls,.csv"
              onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
              className="text-sm text-[var(--color-text-secondary)] file:mr-3 file:h-10 file:px-4 file:rounded-[var(--radius-sm)] file:border-0 file:text-sm file:font-medium file:bg-gray-100 file:text-[var(--color-text)] file:cursor-pointer hover:file:bg-gray-200"
            />
          </div>
          <button onClick={handleUpload} disabled={uploading} className={btnPrimary}>
            {uploading ? "Uploading..." : "Upload"}
          </button>
        </div>

        {uploadResult && (
          <div className="mt-5 p-4 bg-gray-50 rounded-[var(--radius-sm)] border border-[var(--color-border)] text-sm">
            <div className="flex gap-6 text-sm flex-wrap">
              <span><strong className="font-medium">Batch:</strong> {uploadResult.batch_name}</span>
              <span><strong className="font-medium">Users Created:</strong> {uploadResult.users_created}</span>
              <span><strong className="font-medium">Added to Batch:</strong> {uploadResult.users_added}</span>
              <span><strong className="font-medium">Skipped:</strong> {uploadResult.skipped}</span>
            </div>
            {uploadResult.errors.length > 0 && (
              <div className="mt-3 text-[var(--color-danger)] text-xs">
                <p className="font-medium mb-1">Errors:</p>
                <ul className="list-disc ml-4 space-y-0.5">
                  {uploadResult.errors.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Batch List */}
      <div className={`${card} p-6`}>
        <h2 className="text-sm font-semibold mb-4">All Batches</h2>
        {batches.length === 0 ? (
          <p className="text-[var(--color-text-secondary)] text-sm">No batches created yet.</p>
        ) : (
          <div className="space-y-3">
            {batches.map((b) => (
              <div key={b.id} className="border border-[var(--color-border)] rounded-[var(--radius-sm)] p-4 hover:border-gray-300 transition-colors space-y-4">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium">{b.name}</p>
                    <div className="flex gap-3 mt-1">
                      <span className="text-xs text-[var(--color-text-secondary)]">{b.user_count} users</span>
                      <span className={`text-xs font-medium ${
                        b.status === "current" ? "text-[var(--color-success)]" :
                        b.status === "upcoming" ? "text-[var(--color-warning)]" :
                        "text-[var(--color-text-secondary)]"
                      }`}>
                        {b.status}
                      </span>
                    </div>
                    {b.description && <p className="text-xs text-[var(--color-text-secondary)] mt-1">{b.description}</p>}
                  </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => openEditBatch(b)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] text-[var(--color-primary)] hover:bg-blue-50 cursor-pointer transition-colors"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => toggleManageBatch(b.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] text-[var(--color-primary)] hover:bg-blue-50 cursor-pointer transition-colors"
                      >
                        {managingBatchId === b.id ? "Close" : "Add Existing Users"}
                      </button>
                      {b.status === "archived" ? (
                        <button
                          onClick={() => handleRestoreBatch(b.id)}
                          className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] text-[var(--color-success)] hover:bg-green-50 cursor-pointer transition-colors"
                        >
                          {restoringInProgress && restoringBatchId === b.id ? "Restoring..." : "Restore"}
                        </button>
                      ) : (
                        <button
                          onClick={() => setDeletingBatchId(b.id)}
                          className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] text-[var(--color-danger)] hover:bg-red-50 cursor-pointer transition-colors"
                        >
                          Archive
                        </button>
                      )}
                    </div>
                </div>

                {managingBatchId === b.id && (
                  <div className="border-t border-[var(--color-border)] pt-4 space-y-3">
                    <p className="text-xs text-[var(--color-text-secondary)]">
                      Search existing users and add them to this batch.
                    </p>

                    <div className="min-h-10 w-full px-3 py-2 border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-white focus-within:border-[var(--color-primary)] focus-within:ring-2 focus-within:ring-blue-100">
                      <div className="flex flex-wrap items-center gap-2">
                        {selectedUsers.map((user) => (
                          <span
                            key={user.id}
                            className="inline-flex items-center gap-2 h-8 px-3 rounded-full bg-blue-50 text-[var(--color-primary)] text-xs font-medium border border-blue-200"
                          >
                            <span>{user.name} (@{user.username})</span>
                            <button
                              type="button"
                              onClick={() => removeUserFromSelection(user.id)}
                              className="text-[var(--color-primary)] hover:text-blue-800 cursor-pointer"
                              aria-label={`Remove ${user.name}`}
                            >
                              ×
                            </button>
                          </span>
                        ))}
                        <input
                          type="text"
                          value={userSearch}
                          onChange={(e) => setUserSearch(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              if (userSuggestions.length > 0) {
                                addUserToSelection(userSuggestions[0].id);
                              }
                            }
                          }}
                          placeholder={selectedUsers.length === 0 ? "Search by name, username, or email..." : "Add another user..."}
                          className="flex-1 min-w-[220px] h-8 bg-transparent text-sm outline-none placeholder:text-gray-400"
                        />
                      </div>
                    </div>

                    {userSuggestions.length > 0 ? (
                      <div className="border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-white shadow-sm overflow-hidden max-h-56 overflow-y-auto">
                        {userSuggestions.map((user) => (
                          <button
                            key={user.id}
                            type="button"
                            onClick={() => addUserToSelection(user.id)}
                            className="w-full px-3 py-2 text-left hover:bg-gray-50 cursor-pointer transition-colors"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <p className="text-sm font-medium text-[var(--color-text)]">{user.name}</p>
                                <p className="text-xs text-[var(--color-text-secondary)]">@{user.username} • {user.email}</p>
                              </div>
                            </div>
                          </button>
                        ))}
                      </div>
                    ) : userQuery ? (
                      <p className="text-xs text-[var(--color-text-secondary)]">No matching users found.</p>
                    ) : null}

                    <div className="flex items-center gap-3">
                      <button onClick={handleAddExistingUsers} disabled={addingUsers} className={btnPrimary}>
                        {addingUsers ? "Adding..." : "Add Selected Users"}
                      </button>
                      <span className="text-xs text-[var(--color-text-secondary)]">
                        {selectedUserIds.length} user(s) selected
                      </span>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Delete confirmation modal */}
      {deletingBatchId && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-[var(--radius)] shadow-xl w-full max-w-md">
            <div className="border-b border-[var(--color-border)] px-6 py-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Confirm Delete</h3>
              <button
                onClick={() => setDeletingBatchId(null)}
                className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-100 cursor-pointer text-lg"
              >
                &times;
              </button>
            </div>
            <div className="p-6">
              <p className="text-sm text-[var(--color-text-secondary)] mb-4">
                Are you sure you want to archive the batch "{batches.find((bb) => bb.id === deletingBatchId)?.name}"? Archiving will hide the batch from active lists but keep user assignments; you can restore it later.
              </p>
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => setDeletingBatchId(null)}
                  className="h-10 px-4 text-sm rounded border border-[var(--color-border)] hover:bg-gray-50 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={confirmDelete}
                  disabled={deletingInProgress}
                  className={`${btnPrimary}`}
                >
                  {deletingInProgress ? "Archiving..." : "Archive Batch"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* Edit Batch modal */}
      {editingBatchId && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-[var(--radius)] shadow-xl w-full max-w-md">
            <div className="border-b border-[var(--color-border)] px-6 py-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Edit Batch</h3>
              <button
                onClick={() => setEditingBatchId(null)}
                className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-100 cursor-pointer text-lg"
              >
                &times;
              </button>
            </div>
            <div className="p-6">
              <div className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Name</label>
                  <input
                    type="text"
                    value={editBatchName}
                    onChange={(e) => setEditBatchName(e.target.value)}
                    className={`${inputClass} w-full`}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Description</label>
                  <input
                    type="text"
                    value={editBatchDesc}
                    onChange={(e) => setEditBatchDesc(e.target.value)}
                    className={`${inputClass} w-full`}
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Status</label>
                  <select
                    value={editBatchStatus}
                    onChange={(e) => setEditBatchStatus(e.target.value as "current" | "upcoming" | "completed")}
                    className={`${inputClass} w-full`}
                  >
                    <option value="current">Current</option>
                    <option value="upcoming">Upcoming</option>
                    <option value="completed">Completed</option>
                  </select>
                </div>
              </div>
              <div className="flex gap-3 justify-end mt-4">
                <button
                  onClick={() => setEditingBatchId(null)}
                  className="h-10 px-4 text-sm rounded border border-[var(--color-border)] hover:bg-gray-50 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveEdit}
                  disabled={editingInProgress}
                  className={`${btnPrimary}`}
                >
                  {editingInProgress ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
