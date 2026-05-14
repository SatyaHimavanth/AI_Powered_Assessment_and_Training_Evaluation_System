import { useState, useEffect, useCallback } from "react";
import type { ChangeEvent } from "react";
import api from "../../api";
import type { TopicInfo, TopicConfig, AssessmentListItem, AssessmentResult, BatchInfo } from "./types";
import { card, inputClass, selectClass, btnPrimary } from "./types";


interface Props {
  topics: TopicInfo[];
  batches: BatchInfo[];
  setMessage: (msg: string) => void;
}

export default function Assessments({ topics, batches, setMessage }: Props) {
  const [assessments, setAssessments] = useState<AssessmentListItem[]>([]);
  const [assessmentTitle, setAssessmentTitle] = useState("");
  const [assessmentDesc, setAssessmentDesc] = useState("");
  const [assessmentDuration, setAssessmentDuration] = useState(60);
  const [negativeMarking, setNegativeMarking] = useState(false);
  const [topicConfigs, setTopicConfigs] = useState<TopicConfig[]>([]);
  const [selectedBatchIds, setSelectedBatchIds] = useState<string[]>([]);
  const [batchSearch, setBatchSearch] = useState("");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [creatingAssessment, setCreatingAssessment] = useState(false);
  const [lastCreated, setLastCreated] = useState<AssessmentResult | null>(null);
  const [availableCounts, setAvailableCounts] = useState<Record<string, number>>({});

  // Import-from-Excel UI state
  const [useImport, setUseImport] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importId, setImportId] = useState<string | null>(null);
  const [importPreview, setImportPreview] = useState<any | null>(null);
  const [importErrors, setImportErrors] = useState<string[] | null>(null);

  // Inline form error (shown below Generate button)
  const [formError, setFormError] = useState("");

  // Edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editStartTime, setEditStartTime] = useState("");
  const [editEndTime, setEditEndTime] = useState("");

  // Filters & pagination
  const [filterBatchId, setFilterBatchId] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [perPage, setPerPage] = useState<number>(10);
  const [page, setPage] = useState<number>(1);
  const [totalAssessments, setTotalAssessments] = useState<number>(0);
  const [loadingAssessments, setLoadingAssessments] = useState<boolean>(false);

  const toUtcIso = (localDateTime: string): string | null => {
    if (!localDateTime) return null;
    const parsed = new Date(localDateTime);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
  };

  const toLocalDateTimeInput = (isoDateTime: string): string => {
    const d = new Date(isoDateTime);
    if (Number.isNaN(d.getTime())) return "";

    const pad = (n: number) => String(n).padStart(2, "0");
    const y = d.getFullYear();
    const m = pad(d.getMonth() + 1);
    const day = pad(d.getDate());
    const h = pad(d.getHours());
    const min = pad(d.getMinutes());
    return `${y}-${m}-${day}T${h}:${min}`;
  };


  const loadAssessments = useCallback(async () => {
    setLoadingAssessments(true);
    try {
      const params: Record<string, unknown> = {};
      if (filterBatchId) params.batch_id = filterBatchId;
      if (filterStatus && filterStatus !== "all") params.status = filterStatus;
      if (perPage) params.limit = perPage;
      if (page) params.page = page;

      const res = await api.get("/assessments/", { params });
      const data = res.data;
      if (data && data.items !== undefined) {
        const items = Array.isArray(data.items) ? (data.items as AssessmentListItem[]) : [];
        setAssessments(items);
        setTotalAssessments(data.total ?? items.length);
      } else if (Array.isArray(data)) {
        setAssessments(data as AssessmentListItem[]);
        setTotalAssessments((data as AssessmentListItem[]).length || 0);
      } else {
        setAssessments([]);
        setTotalAssessments(0);
      }
    } catch (err: unknown) {
      console.error(err);
    } finally {
      setLoadingAssessments(false);
    }
  }, [filterBatchId, filterStatus, perPage, page]);

  useEffect(() => {
    const t = setTimeout(() => {
      loadAssessments();
    }, 0);
    return () => clearTimeout(t);
  }, [loadAssessments]);

  const addTopicConfig = () => {
    setTopicConfigs([
      ...topicConfigs,
      { topic_id: "", question_type: "single_mcq", difficulty: "easy", question_count: 5, section_name: "Section-1" },
    ]);
  };

  const updateTopicConfig = (index: number, field: keyof TopicConfig, value: string | number) => {
    const updated = [...topicConfigs];
    updated[index][field] = value;
    setTopicConfigs(updated);

    // Fetch available count when topic/type/difficulty changes
    if (field !== "question_count") {
      const tc = updated[index];
      if (tc.topic_id && tc.question_type && tc.difficulty) {
        fetchAvailableCount(index, tc.topic_id, tc.question_type, tc.difficulty);
      }
    }
  };

  const fetchAvailableCount = async (index: number, topicId: string, questionType: string, difficulty: string) => {
    try {
      const res = await api.post("/assessments/available-count", {
        topic_id: topicId,
        question_type: questionType,
        difficulty: difficulty,
      });
      setAvailableCounts((prev) => ({ ...prev, [`${index}`]: res.data.available }));
    } catch {
      // ignore
    }
  };

  // Handle Excel import upload
  const handleImportFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Basic client-side checks
    const maxSize = 5 * 1024 * 1024; // 5 MB
    if (!/\.(xlsx|xls)$/i.test(file.name)) {
      setMessage("Please upload an .xlsx or .xls file");
      return;
    }
    if (file.size > maxSize) {
      setMessage("File is too large (max 5MB)");
      return;
    }

    const fd = new FormData();
    fd.append("file", file);
    setImporting(true);
    setImportPreview(null);
    setImportErrors(null);
    setImportId(null);
    try {
      const res = await api.post("/admin/assessments/import", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const data = res.data || {};
      setImportId(data.import_id || data.id || null);
      setImportPreview(data.preview || data);
      setImportErrors(data.errors || null);
      setMessage("Import uploaded and validated");
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to upload import");
    } finally {
      setImporting(false);
    }
  };

  const removeTopicConfig = (index: number) => {
    setTopicConfigs(topicConfigs.filter((_, i) => i !== index));
    setAvailableCounts((prev) => {
      const updated = { ...prev };
      delete updated[`${index}`];
      return updated;
    });
  };

  const toggleBatch = (batchId: string) => {
    setSelectedBatchIds((prev) =>
      prev.includes(batchId) ? prev.filter((id) => id !== batchId) : [...prev, batchId]
    );
  };

  const batchQuery = batchSearch.trim().toLowerCase();
  const visibleBatches = batches.filter((b) => b.status === "current");
  const selectedBatches = visibleBatches.filter((batch) => selectedBatchIds.includes(batch.id));
  const batchSuggestions = visibleBatches
    .filter((batch) => !selectedBatchIds.includes(batch.id))
    .filter((batch) => {
      if (!batchQuery) return true;
      const description = batch.description?.toLowerCase() || "";
      return batch.name.toLowerCase().includes(batchQuery) || description.includes(batchQuery);
    })
    .slice(0, 6);

  const handleBatchSelect = (batchId: string) => {
    toggleBatch(batchId);
    setBatchSearch("");
  };

  const handleCreateAssessment = async () => {
    setFormError("");

    if (!assessmentTitle.trim()) {
      setFormError("Assessment title is required.");
      return;
    }
    if (assessmentDuration < 5) {
      setFormError("Duration must be at least 5 minutes.");
      return;
    }
    if (!useImport && topicConfigs.length === 0) {
      setFormError("Add at least one topic configuration.");
      return;
    }

    if (!useImport) {
      // Check all topic configs have a topic selected
      const missingTopic = topicConfigs.findIndex((tc) => !tc.topic_id);
      if (missingTopic !== -1) {
        setFormError(`Row ${missingTopic + 1}: Please select a topic.`);
        return;
      }

      // Check all question counts are ≥ 1
      const zeroCount = topicConfigs.findIndex((tc) => tc.question_count < 1);
      if (zeroCount !== -1) {
        setFormError(`Row ${zeroCount + 1}: Question count must be at least 1.`);
        return;
      }

      // Validate total requested per (topic_id + question_type + difficulty)
      // across the whole test, even when split across multiple sections.
      const poolMap: Record<string, { requested: number; available: number | undefined; topicName: string; type: string; diff: string }> = {};
      for (let i = 0; i < topicConfigs.length; i++) {
        const tc = topicConfigs[i];
        const key = `${tc.topic_id}|${tc.question_type}|${tc.difficulty}`;
        const topic = topics.find((t) => t.id === tc.topic_id);
        if (!poolMap[key]) {
          poolMap[key] = {
            requested: 0,
            available: availableCounts[`${i}`],
            topicName: topic?.name || "Unknown",
            type: tc.question_type,
            diff: tc.difficulty,
          };
        } else {
          // Duplicate combo — update available count if not already set
          if (poolMap[key].available === undefined && availableCounts[`${i}`] !== undefined) {
            poolMap[key].available = availableCounts[`${i}`];
          }
        }
        poolMap[key].requested += tc.question_count;
      }

      for (const key of Object.keys(poolMap)) {
        const pool = poolMap[key];
        // Check requested vs available
        if (pool.available !== undefined && pool.requested > pool.available) {
          setFormError(
            `"${pool.topicName} / ${pool.type} / ${pool.diff}": requested ${pool.requested} but only ${pool.available} available.`
          );
          return;
        }
      }
    }

    // Validate time window if provided
    if (startTime && endTime && new Date(endTime) <= new Date(startTime)) {
      setFormError("End time must be after start time.");
      return;
    }

    // Ensure at least one selected batch is valid/visible
    const batchIdsToUse = selectedBatchIds.filter((id) => visibleBatches.some((b) => b.id === id));
    if (batchIdsToUse.length === 0) {
      setFormError("Select at least one batch to assign this assessment.");
      return;
    }

    setCreatingAssessment(true);
    setLastCreated(null);
    try {
      if (useImport) {
        if (!importId) {
          setFormError("Please upload and validate an import file before creating the assessment.");
          setCreatingAssessment(false);
          return;
        }
        const res = await api.post("/admin/assessments/create-from-import", {
          import_id: importId,
          title: assessmentTitle.trim(),
          description: assessmentDesc.trim(),
          duration: assessmentDuration,
          negative_marking: negativeMarking,
          batch_ids: batchIdsToUse,
          start_time: toUtcIso(startTime),
          end_time: toUtcIso(endTime),
        });
        setLastCreated(res.data);
        setFormError("");
        setMessage(`Assessment "${res.data.title}" created with ${res.data.total_questions} questions`);
        // Reset import state
        setUseImport(false);
        setImportId(null);
        setImportPreview(null);
        setImportErrors(null);
      } else {
        const res = await api.post("/assessments/create", {
          title: assessmentTitle.trim(),
          description: assessmentDesc.trim(),
          duration: assessmentDuration,
          negative_marking: negativeMarking,
          topics: topicConfigs,
          batch_ids: batchIdsToUse,
          start_time: toUtcIso(startTime),
          end_time: toUtcIso(endTime),
        });
        setLastCreated(res.data);
        setFormError("");
        setMessage(`Assessment "${res.data.title}" created with ${res.data.total_questions} questions`);
        setAssessmentTitle("");
        setAssessmentDesc("");
        setAssessmentDuration(60);
        setNegativeMarking(false);
        setTopicConfigs([]);
        setSelectedBatchIds([]);
        setBatchSearch("");
        setStartTime("");
        setEndTime("");
        setAvailableCounts({});
      }
      loadAssessments();
    } catch (err: unknown) {
      console.error(err);
      setFormError("Failed to create assessment.");
    } finally {
      setCreatingAssessment(false);
    }
  };

  const handleArchiveAssessment = async (id: string) => {
    try {
      const res = await api.delete(`/assessments/${id}`);
      setMessage(res.data.message);
      loadAssessments();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to archive");
    }
  };

  const handleRecoverAssessment = async (id: string) => {
    try {
      const res = await api.post(`/assessments/${id}/recover`);
      setMessage(res.data.message);
      loadAssessments();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to recover");
    }
  };

  const openEdit = (a: AssessmentListItem) => {
    setEditingId(a.id);
    // Convert ISO string to datetime-local format (YYYY-MM-DDTHH:MM)
    setEditStartTime(a.start_time ? toLocalDateTimeInput(a.start_time) : "");
    setEditEndTime(a.end_time ? toLocalDateTimeInput(a.end_time) : "");
  };

  const handleEditAssessment = async () => {
    if (!editingId) return;
    try {
      const res = await api.patch(`/assessments/${editingId}`, {
        start_time: editStartTime ? toUtcIso(editStartTime) : "",
        end_time: editEndTime ? toUtcIso(editEndTime) : "",
      });
      setMessage(res.data.message);
      setEditingId(null);
      loadAssessments();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to update assessment");
    }
  };

  return (
    <div className="space-y-6">
      {/* Create Assessment */}
      <div className={`${card} p-6`}>
        <h2 className="text-sm font-semibold mb-4">Create Assessment</h2>

        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Title</label>
              <input
                type="text"
                value={assessmentTitle}
                onChange={(e) => setAssessmentTitle(e.target.value)}
                placeholder="e.g. Python Fundamentals Quiz"
                className={`${inputClass} w-full`}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Duration (min)</label>
              <input
                type="number"
                value={assessmentDuration}
                onChange={(e) => setAssessmentDuration(Number(e.target.value))}
                min={5}
                className={`${inputClass} w-full`}
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Description (optional)</label>
            <input
              type="text"
              value={assessmentDesc}
              onChange={(e) => setAssessmentDesc(e.target.value)}
              placeholder="Brief description of the assessment"
              className={`${inputClass} w-full`}
            />
          </div>

          <label className="inline-flex items-center gap-3 text-sm font-medium cursor-pointer">
            <input
              type="checkbox"
              checked={negativeMarking}
              onChange={(e) => setNegativeMarking(e.target.checked)}
              className="h-4 w-4 accent-[var(--color-primary)]"
            />
            <span>Enable negative marking for multi MCQ partial scoring</span>
          </label>

          {/* Start/End Time */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Start Time</label>
              <input
                type="datetime-local"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                className={`${inputClass} w-full`}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">End Time</label>
              <input
                type="datetime-local"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                className={`${inputClass} w-full`}
              />
            </div>
          </div>

          {/* Batch Selection */}
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-2">Assign to Batches</label>
            {visibleBatches.length === 0 ? (
              <p className="text-xs text-[var(--color-text-secondary)]">No batches available. Create a batch first.</p>
            ) : (
              <div className="space-y-2">
                <div className="min-h-10 w-full px-3 py-2 border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-white focus-within:border-[var(--color-primary)] focus-within:ring-2 focus-within:ring-blue-100">
                  <div className="flex flex-wrap items-center gap-2">
                    {selectedBatches.map((batch) => (
                      <span
                        key={batch.id}
                        className="inline-flex items-center gap-2 h-8 px-3 rounded-full bg-blue-50 text-[var(--color-primary)] text-xs font-medium border border-blue-200"
                      >
                        <span>{batch.name} ({batch.user_count})</span>
                        <button
                          type="button"
                          onClick={() => toggleBatch(batch.id)}
                          className="text-[var(--color-primary)] hover:text-blue-800 cursor-pointer"
                          aria-label={`Remove ${batch.name}`}
                        >
                          ×
                        </button>
                      </span>
                    ))}
                    <input
                      type="text"
                      value={batchSearch}
                      onChange={(e) => setBatchSearch(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          if (batchSuggestions.length > 0) {
                            handleBatchSelect(batchSuggestions[0].id);
                          }
                        }
                      }}
                      placeholder={selectedBatches.length === 0 ? "Search and add batches..." : "Add another batch..."}
                      className="flex-1 min-w-[220px] h-8 bg-transparent text-sm outline-none placeholder:text-gray-400"
                    />
                  </div>
                </div>

                {batchSuggestions.length > 0 ? (
                  <div className="border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-white shadow-sm overflow-hidden max-h-56 overflow-y-auto">
                    {batchSuggestions.map((batch) => (
                      <button
                        key={batch.id}
                        type="button"
                        onClick={() => handleBatchSelect(batch.id)}
                        className="w-full px-3 py-2 text-left hover:bg-gray-50 cursor-pointer transition-colors"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="text-sm font-medium text-[var(--color-text)]">{batch.name}</p>
                            {batch.description && (
                              <p className="text-xs text-[var(--color-text-secondary)] truncate">{batch.description}</p>
                            )}
                          </div>
                          <span className="text-xs text-[var(--color-text-secondary)] shrink-0">{batch.user_count} users</span>
                        </div>
                      </button>
                    ))}
                  </div>
                ) : batchQuery ? (
                  <p className="text-xs text-[var(--color-text-secondary)]">No matching batches found.</p>
                ) : (
                  <p className="text-xs text-[var(--color-text-secondary)]">Type to search batches, then press Enter or click a result to add it.</p>
                )}
              </div>
            )}
          </div>
          
          <div className="flex items-center gap-4 mb-3">
            <div className="inline-flex items-center gap-3">
              <div className="text-sm font-medium text-[var(--color-text-secondary)]">Source</div>
              <div
                role="tablist"
                aria-label="Assessment source"
                className="inline-flex items-center bg-gray-100 rounded-full p-1"
              >
                <button
                  type="button"
                  onClick={() => {
                    setUseImport(false);
                    setImportId(null);
                    setImportPreview(null);
                    setImportErrors(null);
                  }}
                  className={`px-3 py-1 rounded-full text-sm ${!useImport ? "bg-white shadow text-[var(--color-text)]" : "text-[var(--color-text-secondary)]"}`}
                >
                  DB
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setUseImport(true);
                    setImportId(null);
                    setImportPreview(null);
                    setImportErrors(null);
                  }}
                  className={`px-3 py-1 rounded-full text-sm ${useImport ? "bg-white shadow text-[var(--color-text)]" : "text-[var(--color-text-secondary)]"}`}
                >
                  Excel
                </button>
              </div>
            </div>
            {useImport && importPreview && (
              <div className="text-xs text-[var(--color-text-secondary)]">Preview: {importPreview.total_questions ?? importPreview.total ?? "--"} questions</div>
            )}
          </div>

          {/* Topic Configurations or Excel import */}
          {!useImport ? (
            <div>
              <div className="flex items-center justify-between mb-3">
                <label className="text-xs font-medium text-[var(--color-text-secondary)]">Topic Configurations</label>
                <button
                  onClick={addTopicConfig}
                  className="inline-flex items-center gap-1.5 h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-blue-50 text-[var(--color-primary)] hover:bg-blue-100 cursor-pointer transition-colors"
                >
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                  </svg>
                  Add Topic
                </button>
              </div>

              {topicConfigs.length === 0 ? (
                <div className="border border-dashed border-[var(--color-border)] rounded-[var(--radius-sm)] p-6 text-center">
                  <p className="text-sm text-[var(--color-text-secondary)]">
                    No topics added yet. Click "Add Topic" to configure question selection.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {topicConfigs.map((tc, idx) => (
                    <div key={idx} className="border border-[var(--color-border)] rounded-[var(--radius-sm)] p-4 relative group">
                      <button
                        onClick={() => removeTopicConfig(idx)}
                        className="absolute top-3 right-3 w-6 h-6 flex items-center justify-center rounded text-[var(--color-text-secondary)] hover:bg-red-50 hover:text-[var(--color-danger)] cursor-pointer opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                      <div className="grid grid-cols-5 gap-3">
                        <div>
                          <label className="block text-[10px] font-medium text-[var(--color-text-secondary)] mb-1">Section</label>
                          <input
                            type="text"
                            value={tc.section_name || "Section-1"}
                            onChange={(e) => updateTopicConfig(idx, "section_name" as keyof TopicConfig, e.target.value)}
                            placeholder="e.g. Fundamentals"
                            className={`${inputClass} w-full`}
                          />
                        </div>
                        <div>
                          <label className="block text-[10px] font-medium text-[var(--color-text-secondary)] mb-1">Topic</label>
                          <select
                            value={tc.topic_id}
                            onChange={(e) => updateTopicConfig(idx, "topic_id", e.target.value)}
                            className={`${selectClass} w-full`}
                          >
                            <option value="">Select...</option>
                            {topics.map((t) => (
                              <option key={t.id} value={t.id}>{t.name}</option>
                            ))}
                          </select>
                        </div>
                        <div>
                          <label className="block text-[10px] font-medium text-[var(--color-text-secondary)] mb-1">Type</label>
                          <select
                            value={tc.question_type}
                            onChange={(e) => updateTopicConfig(idx, "question_type", e.target.value)}
                            className={`${selectClass} w-full`}
                          >
                            <option value="single_mcq">Single MCQ</option>
                            <option value="multi_mcq">Multi MCQ</option>
                            <option value="text">Text</option>
                            <option value="coding">Coding</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-[10px] font-medium text-[var(--color-text-secondary)] mb-1">Difficulty</label>
                          <select
                            value={tc.difficulty}
                            onChange={(e) => updateTopicConfig(idx, "difficulty", e.target.value)}
                            className={`${selectClass} w-full`}
                          >
                            <option value="easy">Easy</option>
                            <option value="medium">Medium</option>
                            <option value="hard">Hard</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-[10px] font-medium text-[var(--color-text-secondary)] mb-1">
                            Questions
                            {availableCounts[`${idx}`] !== undefined && (
                              <span className="ml-1 text-[var(--color-text-secondary)]">
                                (max: {availableCounts[`${idx}`]})
                              </span>
                            )}
                          </label>
                          <input
                            type="number"
                            value={tc.question_count}
                            onChange={(e) => updateTopicConfig(idx, "question_count", Number(e.target.value))}
                            min={1}
                            max={availableCounts[`${idx}`] || undefined}
                            className={`${inputClass} w-full ${
                              availableCounts[`${idx}`] !== undefined && tc.question_count > availableCounts[`${idx}`]
                                ? "border-[var(--color-danger)] focus:border-[var(--color-danger)]"
                                : ""
                            }`}
                          />
                          {availableCounts[`${idx}`] !== undefined && tc.question_count > availableCounts[`${idx}`] && (
                            <p className="text-[10px] text-[var(--color-danger)] mt-0.5">
                              Exceeds available ({availableCounts[`${idx}`]})
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div>
              <div className="flex items-center justify-between mb-3">
                <label className="text-xs font-medium text-[var(--color-text-secondary)]">Import Questions (Excel)</label>
                <div className="text-xs text-[var(--color-text-secondary)]">Upload .xlsx (each sheet is a section)</div>
              </div>
              <div className="border border-dashed rounded-[var(--radius-sm)] p-4">
                <input type="file" accept=".xlsx,.xls" onChange={handleImportFileChange} className="text-sm" />
                {importing && <p className="text-xs text-[var(--color-text-secondary)] mt-2">Uploading and validating...</p>}
                {importPreview && (
                  <div className="mt-3 bg-white p-3 rounded border border-gray-200 text-sm text-[var(--color-text-secondary)]">
                    <p className="font-medium text-[var(--color-text)] mb-2">Preview</p>
                    {Array.isArray(importPreview.sections) ? (
                      <ul className="list-disc ml-4 space-y-1">
                        {importPreview.sections.map((s: any, i: number) => (
                          <li key={i}>{s.name}: {s.count} questions</li>
                        ))}
                      </ul>
                    ) : (
                      <p>Total questions: {importPreview.total_questions ?? importPreview.total ?? '—'}</p>
                    )}
                  </div>
                )}
                {importErrors && importErrors.length > 0 && (
                  <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-[var(--color-danger)]">
                    <p className="font-medium">Validation Errors</p>
                    <ul className="list-disc ml-4 mt-1">
                      {importErrors.map((err, i) => <li key={i}>{err}</li>)}
                    </ul>
                  </div>
                )}
                {importId && <p className="mt-2 text-xs text-green-600">Import ready (id: {importId})</p>}
              </div>
            </div>
          )}

          <div>
            <button
              onClick={handleCreateAssessment}
              disabled={creatingAssessment}
              className={`${btnPrimary} mt-2`}
            >
              {creatingAssessment ? "Generating..." : "Generate Assessment"}
            </button>
            {formError && (
              <div className="mt-3 flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded-[var(--radius-sm)] text-sm text-[var(--color-danger)]">
                <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                </svg>
                <span>{formError}</span>
              </div>
            )}
          </div>
        </div>

        {/* Creation Result */}
        {lastCreated && (
          <div className="mt-5 p-4 bg-green-50 rounded-[var(--radius-sm)] border border-green-200 text-sm">
            <p className="font-medium text-[var(--color-success)] mb-2">Assessment Created Successfully</p>
            <div className="space-y-1 text-[var(--color-text-secondary)]">
              <p><span className="font-medium text-[var(--color-text)]">Title:</span> {lastCreated.title}</p>
              <p><span className="font-medium text-[var(--color-text)]">Total Questions:</span> {lastCreated.total_questions}</p>
              <p><span className="font-medium text-[var(--color-text)]">Negative Marking:</span> {lastCreated.negative_marking ? "Enabled" : "Disabled"}</p>
              {lastCreated.batch_names.length > 0 && (
                <p><span className="font-medium text-[var(--color-text)]">Batches:</span> {lastCreated.batch_names.join(", ")}</p>
              )}
              {lastCreated.start_time && (
                <p><span className="font-medium text-[var(--color-text)]">Window:</span> {new Date(lastCreated.start_time).toLocaleString()} - {lastCreated.end_time ? new Date(lastCreated.end_time).toLocaleString() : "No end"}</p>
              )}
              {lastCreated.topics.map((t, i) => (
                <p key={i} className="pl-3 border-l-2 border-green-200">
                  {(t.section_name || "Section-1")} -- {t.topic_name} -- {t.question_type} / {t.difficulty}: {t.selected_count}/{t.question_count} selected
                </p>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Assessment List */}
      <div className={`${card} p-6`}>
        <h2 className="text-sm font-semibold mb-4">View & Modify Assessments</h2>

        <div className="flex items-center justify-between mb-4 gap-3">
          <div className="flex items-center gap-3">
            <select
              value={filterBatchId}
              onChange={(e) => { setFilterBatchId(e.target.value); setPage(1); }}
              className={`${selectClass}`}
            >
              <option value="">All Batches</option>
              {visibleBatches.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>

            <select
              value={filterStatus}
              onChange={(e) => { setFilterStatus(e.target.value); setPage(1); }}
              className={`${selectClass}`}
            >
              <option value="all">All</option>
              <option value="upcoming">Upcoming</option>
              <option value="ongoing">Ongoing</option>
              <option value="completed">Completed</option>
            </select>

            <select
              value={perPage}
              onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1); }}
              className={`${selectClass}`}
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
            </select>
          </div>

          <div className="text-sm text-[var(--color-text-secondary)]">
            Showing {assessments.length} of {totalAssessments}
          </div>
        </div>

        {loadingAssessments ? (
          <p className="text-[var(--color-text-secondary)] text-sm">Loading assessments...</p>
        ) : assessments.length === 0 ? (
          <p className="text-[var(--color-text-secondary)] text-sm">No assessments found.</p>
        ) : (
          <div className="space-y-3">
            {assessments.map((a) => (
              <div key={a.id} className="flex items-center justify-between border border-[var(--color-border)] rounded-[var(--radius-sm)] p-4 hover:border-gray-300 transition-colors">
                <div>
                  <p className="text-sm font-medium">{a.title}</p>
                  <div className="flex gap-3 mt-1 flex-wrap">
                    <span className="text-xs text-[var(--color-text-secondary)]">{a.total_questions} questions</span>
                    <span className="text-xs text-[var(--color-text-secondary)]">{a.duration} min</span>
                    <span className={`text-xs ${a.negative_marking ? "text-amber-600" : "text-[var(--color-text-secondary)]"}`}>
                      {a.negative_marking ? "Negative marking on" : "No negative marking"}
                    </span>
                    <span className="text-xs text-[var(--color-text-secondary)]">
                      {new Date(a.created_at).toLocaleDateString()}
                    </span>
                    {a.batch_names.length > 0 && (
                      <span className="text-xs text-purple-600">Batches: {a.batch_names.join(", ")}</span>
                    )}
                    {a.start_time && (
                      <span className="text-xs text-[var(--color-text-secondary)]">
                        {new Date(a.start_time).toLocaleString()} - {a.end_time ? new Date(a.end_time).toLocaleString() : "Open"}
                      </span>
                    )}
                  </div>
                  {a.description && <p className="text-xs text-[var(--color-text-secondary)] mt-1">{a.description}</p>}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => openEdit(a)}
                    className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] text-[var(--color-primary)] hover:bg-blue-50 cursor-pointer transition-colors"
                  >
                    Edit
                  </button>
                  {a.is_archived ? (
                    <button
                      onClick={() => handleRecoverAssessment(a.id)}
                      className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] text-[var(--color-primary)] hover:bg-blue-50 cursor-pointer transition-colors"
                    >
                      Recover
                    </button>
                  ) : (
                    <button
                      onClick={() => handleArchiveAssessment(a.id)}
                      className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] text-[var(--color-danger)] hover:bg-red-50 cursor-pointer transition-colors"
                    >
                      Archive
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Pagination controls */}
        {totalAssessments > 0 && perPage > 0 && (
          <div className="mt-4 flex items-center justify-between">
            <div className="text-sm text-[var(--color-text-secondary)]">
              Page {page} of {Math.max(1, Math.ceil(totalAssessments / perPage))}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="h-8 px-3 text-sm rounded border border-[var(--color-border)] hover:bg-gray-50 disabled:opacity-50"
              >
                Prev
              </button>
              <button
                onClick={() => setPage((p) => p + 1)}
                disabled={page >= Math.max(1, Math.ceil(totalAssessments / perPage))}
                className="h-8 px-3 text-sm rounded border border-[var(--color-border)] hover:bg-gray-50 disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Edit Modal */}
      {editingId && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-[var(--radius)] shadow-xl w-full max-w-md">
            <div className="border-b border-[var(--color-border)] px-6 py-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold">Edit Assessment Schedule</h3>
              <button
                onClick={() => setEditingId(null)}
                className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-100 cursor-pointer text-lg"
              >
                &times;
              </button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Start Time</label>
                <input
                  type="datetime-local"
                  value={editStartTime}
                  onChange={(e) => setEditStartTime(e.target.value)}
                  className={`${inputClass} w-full`}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">End Time</label>
                <input
                  type="datetime-local"
                  value={editEndTime}
                  onChange={(e) => setEditEndTime(e.target.value)}
                  className={`${inputClass} w-full`}
                />
              </div>
              <div className="flex gap-3 pt-2">
                <button
                  onClick={handleEditAssessment}
                  className={`${btnPrimary} flex-1`}
                >
                  Save Changes
                </button>
                <button
                  onClick={() => setEditingId(null)}
                  className="flex-1 h-10 px-5 text-sm font-medium rounded-[var(--radius-sm)] border border-[var(--color-border)] hover:bg-gray-50 cursor-pointer"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
