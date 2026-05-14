import { useState, useRef } from "react";
import api from "../../api";
import type { TopicInfo, QuestionInfo, UploadResult } from "./types";
import { card, inputClass, selectClass, btnPrimary } from "./types";

interface Props {
  topics: TopicInfo[];
  setMessage: (msg: string) => void;
  reloadTopics: () => void;
}

export default function Questions({ topics, setMessage, reloadTopics }: Props) {
  const [questions, setQuestions] = useState<QuestionInfo[]>([]);
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [topicName, setTopicName] = useState("");
  const [isNewTopic, setIsNewTopic] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [filterTopic, setFilterTopic] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterDifficulty, setFilterDifficulty] = useState("");
  const [showTopicEditModal, setShowTopicEditModal] = useState(false);
  const [editingTopic, setEditingTopic] = useState<TopicInfo | null>(null);
  const [editTopicName, setEditTopicName] = useState("");
  const [editTopicDescription, setEditTopicDescription] = useState("");
  const [showTopicDeleteModal, setShowTopicDeleteModal] = useState(false);
  const [deleteMode, setDeleteMode] = useState<string>("");
  const [reassignToTopicId, setReassignToTopicId] = useState<string>("");
  const isDeleteEnabled = deleteMode === "cascade" || (deleteMode === "reassign" && Boolean(reassignToTopicId));
  const [showCreateTopicModal, setShowCreateTopicModal] = useState(false);
  const [createTopicName, setCreateTopicName] = useState("");
  const [createTopicDescription, setCreateTopicDescription] = useState("");
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(10);
  const [totalQuestions, setTotalQuestions] = useState<number>(0);
  const [searchText, setSearchText] = useState<string>("");
  const [loadingQuestions, setLoadingQuestions] = useState<boolean>(false);
  const [showQuestionDeleteModal, setShowQuestionDeleteModal] = useState(false);
  const [questionToDelete, setQuestionToDelete] = useState<QuestionInfo | null>(null);
  const [deletingQuestion, setDeletingQuestion] = useState(false);
  const [showQuestionEditModal, setShowQuestionEditModal] = useState(false);
  const [questionToEdit, setQuestionToEdit] = useState<QuestionInfo | null>(null);
  const [loadingQuestionDetails, setLoadingQuestionDetails] = useState(false);
  const [savingQuestion, setSavingQuestion] = useState(false);
  const [editQuestionText, setEditQuestionText] = useState("");
  const [editType, setEditType] = useState("");
  const [editDifficulty, setEditDifficulty] = useState("");
  const [editReferenceAnswer, setEditReferenceAnswer] = useState("");
  const [editOptions, setEditOptions] = useState<{ text: string; is_correct: boolean }[]>([]);
  const [editDefaultCode, setEditDefaultCode] = useState("");
  const [editTestCases, setEditTestCases] = useState<{ input: string; expected_output: string; is_sample: boolean }[]>([]);

  const loadQuestions = async (pageArg?: number) => {
    const p = Number(pageArg ?? page) || 1;
    setLoadingQuestions(true);
    try {
        const params: Record<string, unknown> = {};
      if (filterTopic) params.topic_id = filterTopic;
      if (filterType) params.q_type = filterType;
      if (filterDifficulty) params.difficulty = filterDifficulty;
      if (searchText) params.search = searchText;
      params.page = p;
      params.limit = pageSize;
      const res = await api.get("/questions/", { params });
      const data = res.data;
      if (Array.isArray(data)) {
        setQuestions(data as QuestionInfo[]);
        setTotalQuestions((data as QuestionInfo[]).length);
        setPage(1);
        setPageSize((data as QuestionInfo[]).length || 10);
      } else {
        setQuestions(data.items as QuestionInfo[]);
        setTotalQuestions(Number(data.total) || 0);
        setPage(Number(data.page) || p);
        setPageSize(Number(data.limit) || pageSize);
      }
    } catch {
      // ignore errors for now
    } finally {
      setLoadingQuestions(false);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile || !topicName.trim()) {
      setMessage("Please select a file and enter a topic name");
      return;
    }
    setUploading(true);
    setUploadResult(null);
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const res = await api.post(`/questions/upload?topic_name=${encodeURIComponent(topicName.trim())}`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setUploadResult(res.data);
      setMessage(`Successfully imported ${res.data.imported} questions for topic "${res.data.topic}"`);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setSelectedFile(null);
      setTopicName("");
      setIsNewTopic(false);
      reloadTopics();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const openEditTopic = (t: TopicInfo) => {
    setEditingTopic(t);
    setEditTopicName(t.name || "");
    setEditTopicDescription(t.description || "");
    setShowTopicEditModal(true);
  };

  const saveEditTopic = async () => {
    if (!editingTopic) return;
    try {
      const payload: Record<string, string> = {};
      if (editTopicName.trim()) payload.name = editTopicName.trim();
      payload.description = editTopicDescription;
      await api.patch(`/questions/topics/${editingTopic.id}`, payload);
      setMessage(`Topic '${editTopicName}' updated.`);
      setShowTopicEditModal(false);
      reloadTopics();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to update topic");
    }
  };

  const openDeleteTopic = (t: TopicInfo) => {
    setEditingTopic(t);
    setDeleteMode("");
    setReassignToTopicId("");
    setShowTopicDeleteModal(true);
  };

  const confirmDeleteTopic = async () => {
    if (!editingTopic) return;
    try {
      const params: Record<string, unknown> = {};
      if (deleteMode === "cascade") params.mode = "cascade";
      else if (deleteMode === "reassign") {
        if (!reassignToTopicId) {
          setMessage("Select a topic to reassign questions to.");
          return;
        }
        params.mode = "reassign";
        params.reassign_to = reassignToTopicId;
      }

      const res = await api.delete(`/questions/topics/${editingTopic.id}`, { params });
      setMessage(res.data?.message || "Topic deleted.");
      setShowTopicDeleteModal(false);
      reloadTopics();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to delete topic");
    }
  };

  const openQuestionDelete = (q: QuestionInfo) => {
    setQuestionToDelete(q);
    setShowQuestionDeleteModal(true);
  };

  const confirmDeleteQuestion = async () => {
    if (!questionToDelete) return;
    setDeletingQuestion(true);
    try {
      const res = await api.delete(`/questions/${questionToDelete.id}`);
      setMessage(res.data?.message || "Question archived.");
      setShowQuestionDeleteModal(false);
      setQuestionToDelete(null);
      // reload current page
      loadQuestions(page);
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to archive question");
    } finally {
      setDeletingQuestion(false);
    }
  };

  const openQuestionEdit = async (q: QuestionInfo) => {
    setQuestionToEdit(q);
    setLoadingQuestionDetails(true);
    setShowQuestionEditModal(true);
    try {
      const res = await api.get(`/questions/${q.id}`);
      const data = res.data;
      setEditQuestionText(data.question || "");
      setEditType(data.type || "");
      setEditDifficulty(data.difficulty || "");
      setEditReferenceAnswer(data.reference_answer || "");
      setEditDefaultCode(data.default_code || "");
      setEditOptions((data.options && Array.isArray(data.options)) ? data.options.map((o: any) => ({ text: o.text || "", is_correct: !!o.is_correct })) : []);
      setEditTestCases((data.test_cases && Array.isArray(data.test_cases)) ? data.test_cases.map((tc: any) => ({ input: tc.input_data || "", expected_output: tc.expected_output || "", is_sample: !!tc.is_sample })) : []);
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to load question details");
      setShowQuestionEditModal(false);
    } finally {
      setLoadingQuestionDetails(false);
    }
  };

  const saveQuestionEdit = async () => {
    if (!questionToEdit) return;
    // Basic validation
    if (!editQuestionText.trim()) {
      setMessage("Question text is required");
      return;
    }

    if ((editType === "single_mcq" || editType === "multi_mcq") && (!editOptions || editOptions.length === 0)) {
      setMessage("MCQ questions must have at least one option");
      return;
    }
    if ((editType === "single_mcq" || editType === "multi_mcq") && !editOptions.some((o) => o.is_correct)) {
      setMessage("At least one option must be marked correct");
      return;
    }

    if (editType === "coding" && editTestCases.some((tc) => !tc.input.trim() && !tc.expected_output.trim())) {
      setMessage("Test cases must include input or expected output");
      return;
    }

    const payload: any = {
      question: editQuestionText,
      type: editType,
      difficulty: editDifficulty,
      reference_answer: editReferenceAnswer,
    };

    if (editType === "coding") {
      payload.default_code = editDefaultCode;
      payload.test_cases = editTestCases.map((tc) => ({ input: tc.input, expected_output: tc.expected_output, is_sample: !!tc.is_sample }));
    }

    if (editType === "single_mcq" || editType === "multi_mcq") {
      payload.options = editOptions.map((o) => ({ text: o.text, is_correct: !!o.is_correct }));
    }

    setSavingQuestion(true);
    try {
      await api.patch(`/questions/${questionToEdit.id}`, payload);
      setMessage("Question updated.");
      setShowQuestionEditModal(false);
      setQuestionToEdit(null);
      loadQuestions(page);
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to update question");
    } finally {
      setSavingQuestion(false);
    }
  };

  const createTopic = async () => {
    if (!createTopicName.trim()) {
      setMessage("Topic name is required");
      return;
    }
    try {
      await api.post(`/questions/topics`, { name: createTopicName.trim(), description: createTopicDescription });
      setMessage(`Topic '${createTopicName.trim()}' created.`);
      setShowCreateTopicModal(false);
      setCreateTopicName("");
      setCreateTopicDescription("");
      reloadTopics();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to create topic");
    }
  };

  return (
    <div className="space-y-6">
      {/* Upload */}
      <div className={`${card} p-6`}>
        <h2 className="text-sm font-semibold mb-1">Upload Questions</h2>
        <p className="text-xs text-[var(--color-text-secondary)] mb-5">
          Columns: type, difficulty, question, option_a, option_b, option_c, option_d, correct_options, reference_answer
        </p>
        <div className="flex gap-3 items-end flex-wrap">
          <div>
            <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">Topic</label>
            <select
              value={isNewTopic ? "__new__" : topicName}
              onChange={(e) => {
                if (e.target.value === "__new__") {
                  setIsNewTopic(true);
                  setTopicName("");
                } else {
                  setIsNewTopic(false);
                  setTopicName(e.target.value);
                }
              }}
              className={`${selectClass} w-52`}
            >
              <option value="">Select a topic...</option>
              {topics.map((t) => (
                <option key={t.id} value={t.name}>{t.name}</option>
              ))}
              <option value="__new__">+ Create new topic</option>
            </select>
          </div>
          {isNewTopic && (
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">New Topic Name</label>
              <input
                type="text"
                value={topicName}
                onChange={(e) => setTopicName(e.target.value)}
                placeholder="e.g. FastAPI"
                className={`${inputClass} w-48`}
                autoFocus
              />
            </div>
          )}
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
            <div className="flex gap-6 text-sm">
              <span><strong className="font-medium">Topic:</strong> {uploadResult.topic}</span>
              <span><strong className="font-medium">Imported:</strong> {uploadResult.imported}</span>
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

      {/* Topics */}
      <div className={`${card} p-6`}>
        <div className="flex items-start justify-between mb-3">
          <h2 className="text-sm font-semibold">Topics</h2>
          <button type="button" onClick={() => setShowCreateTopicModal(true)} className={`${btnPrimary} px-3 py-1 text-sm`}>Create Topic</button>
        </div>
        {topics.length === 0 ? (
          <p className="text-[var(--color-text-secondary)] text-sm">No topics yet. Upload questions to create topics.</p>
        ) : (
          <div className="space-y-2">
            {topics.map((t) => (
              <div key={t.id} className="flex items-center justify-between border border-[var(--color-border)] rounded-[var(--radius-sm)] p-3">
                <div>
                  <div className="text-sm font-medium">{t.name}</div>
                  {t.description && <div className="text-xs text-[var(--color-text-secondary)] mt-1">{t.description}</div>}
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => openEditTopic(t)}
                    className="text-indigo-600 hover:text-indigo-700 text-xs font-medium"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => openDeleteTopic(t)}
                    className="text-red-600 hover:text-red-700 text-xs font-medium"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Edit Topic Modal */}
      {showTopicEditModal && editingTopic && (
        <div className="fixed inset-0 z-50 overflow-auto flex items-start md:items-center justify-center bg-black/60">
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-md max-h-[90vh] mx-4 my-6 overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">Edit Topic</h3>
                <p className="text-sm text-gray-500">{editingTopic.name}</p>
              </div>
              <button onClick={() => setShowTopicEditModal(false)} className="text-gray-500 hover:text-gray-700 cursor-pointer">✕</button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                <input
                  type="text"
                  value={editTopicName}
                  onChange={(e) => setEditTopicName(e.target.value)}
                  className={`${inputClass} w-full`}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <textarea
                  value={editTopicDescription}
                  onChange={(e) => setEditTopicDescription(e.target.value)}
                  className="w-full px-3 py-2 border border-[var(--color-border)] rounded-[var(--radius-sm)] text-sm focus:border-[var(--color-primary)] focus:ring-2 focus:ring-blue-100"
                  rows={4}
                />
              </div>
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
              <button onClick={() => setShowTopicEditModal(false)} className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">Cancel</button>
              <button onClick={saveEditTopic} className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700">Save</button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Question Modal */}
      {showQuestionDeleteModal && questionToDelete && (
        <div className="fixed inset-0 z-50 overflow-auto flex items-start md:items-center justify-center bg-black/60">
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-lg max-h-[90vh] mx-4 my-6 overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">Archive Question</h3>
                <p className="text-sm text-gray-500">Are you sure you want to archive this question?</p>
              </div>
              <button onClick={() => setShowQuestionDeleteModal(false)} className="text-gray-500 hover:text-gray-700 cursor-pointer">✕</button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-sm text-[var(--color-text-secondary)]">This will archive the question and remove it from lists. Historical assessment data will remain intact.</p>
              <div className="bg-gray-50 p-4 rounded">
                <p className="text-sm font-medium">{questionToDelete.question}</p>
                {questionToDelete.reference_answer && (
                  <p className="text-sm text-[var(--color-text-secondary)] mt-2">{questionToDelete.reference_answer}</p>
                )}
              </div>
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
              <button onClick={() => setShowQuestionDeleteModal(false)} className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">Cancel</button>
              <button
                onClick={confirmDeleteQuestion}
                disabled={deletingQuestion}
                className={`px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg ${deletingQuestion ? 'opacity-50 cursor-not-allowed' : 'hover:bg-red-700'}`}
              >
                {deletingQuestion ? 'Archiving...' : 'Archive Question'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Question Modal */}
      {showQuestionEditModal && questionToEdit && (
        <div className="fixed inset-0 z-50 overflow-auto flex items-start md:items-center justify-center bg-black/60">
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-2xl max-h-[90vh] mx-4 my-6 overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">Edit Question</h3>
                <p className="text-sm text-gray-500">{questionToEdit.topic}</p>
              </div>
              <button onClick={() => setShowQuestionEditModal(false)} className="text-gray-500 hover:text-gray-700 cursor-pointer">✕</button>
            </div>
            <div className="p-6 space-y-4">
              {loadingQuestionDetails ? (
                <p className="text-sm text-[var(--color-text-secondary)]">Loading...</p>
              ) : (
                <>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Question</label>
                    <textarea value={editQuestionText} onChange={(e) => setEditQuestionText(e.target.value)} rows={3} className="w-full px-3 py-2 border border-[var(--color-border)] rounded-[var(--radius-sm)] text-sm focus:border-[var(--color-primary)] focus:ring-2 focus:ring-blue-100" />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
                      <select value={editType} onChange={(e) => setEditType(e.target.value)} className={selectClass}>
                        <option value="single_mcq">Single MCQ</option>
                        <option value="multi_mcq">Multi MCQ</option>
                        <option value="text">Text Q&A</option>
                        <option value="coding">Coding</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Difficulty</label>
                      <select value={editDifficulty} onChange={(e) => setEditDifficulty(e.target.value)} className={selectClass}>
                        <option value="easy">Easy</option>
                        <option value="medium">Medium</option>
                        <option value="hard">Hard</option>
                      </select>
                    </div>
                  </div>

                  {(editType === "single_mcq" || editType === "multi_mcq") && (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Options</label>
                      <div className="space-y-2">
                        {editOptions.map((opt, idx) => (
                          <div key={idx} className="flex items-center gap-2">
                            {editType === "single_mcq" ? (
                              <input type="radio" name="correct" checked={opt.is_correct} onChange={() => setEditOptions(editOptions.map((o, i) => ({ ...o, is_correct: i === idx })))} />
                            ) : (
                              <input type="checkbox" checked={opt.is_correct} onChange={() => setEditOptions(editOptions.map((o, i) => i === idx ? { ...o, is_correct: !o.is_correct } : o))} />
                            )}
                            <input type="text" value={opt.text} onChange={(e) => setEditOptions(editOptions.map((o, i) => i === idx ? { ...o, text: e.target.value } : o))} className={`${inputClass} flex-1`} />
                            <button onClick={() => setEditOptions(editOptions.filter((_, i) => i !== idx))} className="text-sm text-red-600 px-2" disabled={editOptions.length <= 1}>Remove</button>
                          </div>
                        ))}
                        <div>
                          <button onClick={() => setEditOptions([...editOptions, { text: "", is_correct: false }])} className="px-3 py-1 text-sm bg-gray-100 rounded">Add Option</button>
                        </div>
                      </div>
                    </div>
                  )}

                  {editType === "text" && (
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-1">Reference Answer (optional)</label>
                      <textarea value={editReferenceAnswer} onChange={(e) => setEditReferenceAnswer(e.target.value)} rows={4} className="w-full px-3 py-2 border border-[var(--color-border)] rounded-[var(--radius-sm)] text-sm focus:border-[var(--color-primary)] focus:ring-2 focus:ring-blue-100" />
                    </div>
                  )}

                  {editType === "coding" && (
                    <div className="space-y-3">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-1">Default Code (optional)</label>
                        <textarea value={editDefaultCode} onChange={(e) => setEditDefaultCode(e.target.value)} rows={6} className="w-full px-3 py-2 border border-[var(--color-border)] rounded-[var(--radius-sm)] text-sm font-mono focus:border-[var(--color-primary)] focus:ring-2 focus:ring-blue-100" />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Test Cases</label>
                        <div className="space-y-2">
                          {editTestCases.map((tc, idx) => (
                            <div key={idx} className="grid grid-cols-12 gap-2 items-start">
                              <div className="col-span-5">
                                <input type="text" placeholder="Input" value={tc.input} onChange={(e) => setEditTestCases(editTestCases.map((t, i) => i === idx ? { ...t, input: e.target.value } : t))} className={`${inputClass} w-full`} />
                              </div>
                              <div className="col-span-5">
                                <input type="text" placeholder="Expected Output" value={tc.expected_output} onChange={(e) => setEditTestCases(editTestCases.map((t, i) => i === idx ? { ...t, expected_output: e.target.value } : t))} className={`${inputClass} w-full`} />
                              </div>
                              <div className="col-span-2 flex items-center gap-2">
                                <label className="text-xs">Sample</label>
                                <input type="checkbox" checked={tc.is_sample} onChange={() => setEditTestCases(editTestCases.map((t, i) => i === idx ? { ...t, is_sample: !t.is_sample } : t))} />
                                <button onClick={() => setEditTestCases(editTestCases.filter((_, i) => i !== idx))} className="text-sm text-red-600">Remove</button>
                              </div>
                            </div>
                          ))}
                          <div>
                            <button onClick={() => setEditTestCases([...editTestCases, { input: "", expected_output: "", is_sample: false }])} className="px-3 py-1 text-sm bg-gray-100 rounded">Add Test Case</button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
              <button onClick={() => setShowQuestionEditModal(false)} className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">Cancel</button>
              <button onClick={saveQuestionEdit} disabled={savingQuestion} className={`px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg ${savingQuestion ? 'opacity-50 cursor-not-allowed' : 'hover:bg-indigo-700'}`}>{savingQuestion ? 'Saving...' : 'Save'}</button>
            </div>
          </div>
        </div>
      )}

      {/* Create Topic Modal */}
      {showCreateTopicModal && (
        <div className="fixed inset-0 z-50 overflow-auto flex items-start md:items-center justify-center bg-black/60">
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-md max-h-[90vh] mx-4 my-6 overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">Create Topic</h3>
                <p className="text-sm text-gray-500">Create a new topic</p>
              </div>
              <button onClick={() => setShowCreateTopicModal(false)} className="text-gray-500 hover:text-gray-700 cursor-pointer">✕</button>
            </div>
            <div className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                <input
                  type="text"
                  value={createTopicName}
                  onChange={(e) => setCreateTopicName(e.target.value)}
                  className={`${inputClass} w-full`}
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <textarea
                  value={createTopicDescription}
                  onChange={(e) => setCreateTopicDescription(e.target.value)}
                  className="w-full px-3 py-2 border border-[var(--color-border)] rounded-[var(--radius-sm)] text-sm focus:border-[var(--color-primary)] focus:ring-2 focus:ring-blue-100"
                  rows={4}
                />
              </div>
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
              <button onClick={() => setShowCreateTopicModal(false)} className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">Cancel</button>
              <button
                onClick={createTopic}
                disabled={!createTopicName.trim()}
                className={`px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg ${createTopicName.trim() ? 'hover:bg-indigo-700' : 'opacity-50 cursor-not-allowed'}`}
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Topic Modal */}
      {showTopicDeleteModal && editingTopic && (
        <div className="fixed inset-0 z-50 overflow-auto flex items-start md:items-center justify-center bg-black/60">
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-lg max-h-[90vh] mx-4 my-6 overflow-y-auto">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">Delete Topic</h3>
                <p className="text-sm text-gray-500">{editingTopic.name}</p>
              </div>
              <button onClick={() => setShowTopicDeleteModal(false)} className="text-gray-500 hover:text-gray-700 cursor-pointer">✕</button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-sm text-[var(--color-text-secondary)]">If this topic has questions, choose whether to remove them or move them to another topic.</p>
              <div className="space-y-3">
                <label className="inline-flex items-center gap-2">
                  <input type="radio" name="deleteMode" value="cascade" checked={deleteMode === "cascade"} onChange={() => setDeleteMode("cascade")} />
                  <span className="text-sm">Archive questions questions (remove questions and their options)</span>
                </label>
                <label className="inline-flex items-center gap-2">
                  <input type="radio" name="deleteMode" value="reassign" checked={deleteMode === "reassign"} onChange={() => setDeleteMode("reassign")} />
                  <span className="text-sm">Reassign questions to another topic</span>
                </label>
                {deleteMode === "reassign" && (
                  <div>
                    <label className="block text-sm text-gray-700 mb-1">Reassign to</label>
                    <select className={selectClass} value={reassignToTopicId} onChange={(e) => setReassignToTopicId(e.target.value)}>
                      <option value="">Select topic...</option>
                      {topics.filter((tt) => tt.id !== editingTopic.id).map((tt) => (
                        <option key={tt.id} value={tt.id}>{tt.name}</option>
                      ))}
                    </select>
                  </div>
                )}
                {/* Prompt when no valid option is chosen */}
                {!deleteMode && (
                  <div className="text-sm text-red-600">Please select how you want to handle this topic's questions.</div>
                )}
                {deleteMode === "reassign" && !reassignToTopicId && (
                  <div className="text-sm text-red-600">Please select a topic to reassign questions to.</div>
                )}
              </div>
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
              <button onClick={() => setShowTopicDeleteModal(false)} className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 cursor-pointer">Cancel</button>
              <button
                onClick={confirmDeleteTopic}
                disabled={!isDeleteEnabled}
                title={!isDeleteEnabled ? "Select an option first" : "Delete topic"}
                className={`px-4 py-2 text-sm font-medium text-white bg-red-600 rounded-lg ${isDeleteEnabled ? 'hover:bg-red-700 cursor-pointer' : 'opacity-50 cursor-not-allowed'}`}
              >
                Delete Topic
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Browse */}
      <div className={`${card} p-6`}>
        <h2 className="text-sm font-semibold mb-4">Browse Questions</h2>
          <div className="flex gap-3 mb-5 flex-wrap items-end">
          <select value={filterTopic} onChange={(e) => setFilterTopic(e.target.value)} className={selectClass}>
            <option value="">All Topics</option>
            {topics.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
          <select value={filterType} onChange={(e) => setFilterType(e.target.value)} className={selectClass}>
            <option value="">All Types</option>
            <option value="single_mcq">Single MCQ</option>
            <option value="multi_mcq">Multi MCQ</option>
            <option value="text">Text</option>
            <option value="coding">Coding</option>
          </select>
          <select value={filterDifficulty} onChange={(e) => setFilterDifficulty(e.target.value)} className={selectClass}>
            <option value="">All Difficulties</option>
            <option value="easy">Easy</option>
            <option value="medium">Medium</option>
            <option value="hard">Hard</option>
          </select>
            <input
              type="text"
              placeholder="Search questions and answers"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              className={`${inputClass} w-64`}
            />
            <select value={pageSize} onChange={(e) => { const s = Number(e.target.value); setPageSize(s); setPage(1); }} className={selectClass}>
              <option value={10}>10</option>
              <option value={20}>20</option>
              <option value={50}>50</option>
            </select>
          <button onClick={() => loadQuestions(1)} className={btnPrimary}>
            Search
          </button>
        </div>

        {questions.length === 0 ? (
          <div>
            {loadingQuestions ? (
              <p className="text-[var(--color-text-secondary)] text-sm">Loading...</p>
            ) : (
              <p className="text-[var(--color-text-secondary)] text-sm">No questions found. Use filters and click Search.</p>
            )}
          </div>
        ) : (
          <div>
            {/* Top pagination controls */}
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => { if (page > 1) { setPage(page - 1); loadQuestions(page - 1); } }}
                  disabled={page <= 1}
                  className="px-3 py-1 border rounded-md text-sm"
                >
                  Prev
                </button>
                <select
                  value={page}
                  onChange={(e) => { const p = Number(e.target.value); setPage(p); loadQuestions(p); }}
                  className={selectClass}
                >
                  {Array.from({ length: Math.max(1, Math.ceil(totalQuestions / pageSize)) }).map((_, i) => (
                    <option key={i} value={i + 1}>Page {i + 1}</option>
                  ))}
                </select>
                <button
                  onClick={() => { const totalPages = Math.max(1, Math.ceil(totalQuestions / pageSize)); if (page < totalPages) { setPage(page + 1); loadQuestions(page + 1); } }}
                  disabled={page >= Math.max(1, Math.ceil(totalQuestions / pageSize))}
                  className="px-3 py-1 border rounded-md text-sm"
                >
                  Next
                </button>
                <div className="text-sm text-[var(--color-text-secondary)] ml-3">{totalQuestions} results</div>
              </div>
              {/* per-page selector removed — use selector near search controls */}
            </div>

            <div className="space-y-3 max-h-[520px] overflow-y-auto pr-1">
              {questions.map((q) => {
                return (
                  <div key={q.id} className="border border-[var(--color-border)] rounded-[var(--radius-sm)] p-4 hover:border-gray-300 transition-colors">
                    <div className="flex gap-2 mb-2 items-center">
                      <span className="inline-flex h-5 px-2 rounded text-[10px] font-medium bg-purple-50 text-purple-700">{q.topic}</span>
                      <span className="inline-flex h-5 px-2 rounded text-[10px] font-medium bg-amber-50 text-amber-700">{q.type}</span>
                      <span className={`inline-flex h-5 px-2 rounded text-[10px] font-medium ${
                        q.difficulty === "easy" ? "bg-green-50 text-green-700" :
                        q.difficulty === "medium" ? "bg-yellow-50 text-yellow-700" :
                        "bg-red-50 text-red-700"
                      }`}>{q.difficulty}</span>
                      <button onClick={() => openQuestionDelete(q)} title="Archive question" className="ml-auto text-red-600 hover:text-red-800 p-1 rounded">
                        <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-0.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M9 7V5a2 2 0 012-2h2a2 2 0 012 2v2m4 0H5" />
                        </svg>
                      </button>
                      <button onClick={() => openQuestionEdit(q)} title="Edit question" className="ml-2 text-indigo-600 hover:text-indigo-800 p-1 rounded">
                        <svg xmlns="http://www.w3.org/2000/svg" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M11 5h6M6 7h.01M21 10v10a1 1 0 01-1 1H6a1 1 0 01-1-1V7a1 1 0 011-1h10" />
                          <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 3.5l4 4L12 16l-4 1 1-4 8.5-9.5z" />
                        </svg>
                      </button>
                    </div>
                    <p className="text-sm font-medium leading-relaxed">{q.question}</p>
                    {q.options && q.options.length > 0 && (
                      <ul className="mt-2.5 space-y-1">
                        {q.options.map((o, i) => (
                          <li key={i} className={`flex items-center gap-2 text-sm px-2.5 py-1 rounded-[var(--radius-sm)] ${
                            o.is_correct ? "bg-green-50 text-[var(--color-success)] font-medium" : "text-[var(--color-text-secondary)]"
                          }`}>
                            <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px] shrink-0">
                              {String.fromCharCode(65 + i)}
                            </span>
                            {o.text}
                            {o.is_correct && (
                              <svg className="w-3.5 h-3.5 ml-auto shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                              </svg>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                    {q.reference_answer && (
                      <div className="mt-3 p-3 bg-green-50/60 rounded-[var(--radius-sm)] border-l-2 border-[var(--color-success)]">
                        <p className="text-[10px] font-semibold text-[var(--color-success)] uppercase tracking-wider mb-1">Answer</p>
                        <p className="text-sm text-[var(--color-text)] leading-relaxed whitespace-pre-wrap">{q.reference_answer}</p>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
