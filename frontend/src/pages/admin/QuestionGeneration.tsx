import { useState, useEffect } from "react";
import api from "../../api";
import type { TopicInfo } from "./types";
import { card, inputClass, selectClass, btnPrimary } from "./types";

interface Props {
  topics: TopicInfo[];
  setMessage: (msg: string) => void;
}

interface BatchItem {
  id: string;
  status: string;
  filename: string | null;
  total_generated: number;
  total_approved: number;
  total_rejected: number;
  requested_count: number;
  created_at: string;
  completed_at: string | null;
}

interface StagedItem {
  id: string;
  question_type: string;
  question_text: string;
  reference_answer: string | null;
  options: { option_text: string; is_correct: boolean }[] | null;
  difficulty: string | null;
  similarity_score: number | null;
  matched_question_id: string | null;
  match_band: string | null;
  status: string;
  created_at: string;
}

interface MatchedQuestion {
  id: string;
  question_text: string;
  question_type: string | null;
  difficulty: string | null;
  reference_answer: string | null;
  options: { option_text: string; is_correct: boolean }[] | null;
}

export default function QuestionGeneration({ topics, setMessage }: Props) {
  // Generation form state
  const [sourceText, setSourceText] = useState("");
  const [topicId, setTopicId] = useState("");
  const [questionType, setQuestionType] = useState("text");
  const [difficulty, setDifficulty] = useState("medium");
  const [count, setCount] = useState(10);
  const [autoApprove, setAutoApprove] = useState(false);
  const [generating, setGenerating] = useState(false);

  // Batches list
  const [batches, setBatches] = useState<BatchItem[]>([]);
  const [loadingBatches, setLoadingBatches] = useState(false);
  const [batchesTotal, setBatchesTotal] = useState(0);
  const [batchesPage, setBatchesPage] = useState(1);
  const batchesPageSize = 10;

  // Staged questions for selected batch
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [staged, setStaged] = useState<StagedItem[]>([]);
  const [stagedTotal, setStagedTotal] = useState(0);
  const [stagedPage, setStagedPage] = useState(1);
  const [filterStatus, setFilterStatus] = useState("");
  const [filterBand, setFilterBand] = useState("");
  const [loadingStaged, setLoadingStaged] = useState(false);

  // Comparison modal
  const [compareItem, setCompareItem] = useState<StagedItem | null>(null);
  const [matchedQuestion, setMatchedQuestion] = useState<MatchedQuestion | null>(null);
  const [loadingCompare, setLoadingCompare] = useState(false);

  useEffect(() => {
    loadBatches();
  }, [batchesPage]);

  useEffect(() => {
    if (selectedBatchId) {
      loadStaged();
    }
  }, [selectedBatchId, stagedPage, filterStatus, filterBand]);

  const loadBatches = async () => {
    setLoadingBatches(true);
    try {
      const res = await api.get("/admin/questions/generation/batches", {
        params: { page: batchesPage, page_size: batchesPageSize },
      });
      setBatches(res.data.items || []);
      setBatchesTotal(res.data.total || 0);
    } catch {
      setMessage("Failed to load batches");
    } finally {
      setLoadingBatches(false);
    }
  };

  const loadStaged = async () => {
    if (!selectedBatchId) return;
    setLoadingStaged(true);
    try {
      const params: Record<string, string | number> = { page: stagedPage, page_size: 20 };
      if (filterStatus) params.status = filterStatus;
      if (filterBand) params.band = filterBand;
      const res = await api.get(`/admin/questions/generation/batches/${selectedBatchId}/staged`, { params });
      setStaged(res.data.items || []);
      setStagedTotal(res.data.total || 0);
    } catch {
      setMessage("Failed to load staged questions");
    } finally {
      setLoadingStaged(false);
    }
  };

  const handleGenerate = async () => {
    if (!sourceText.trim()) {
      setMessage("Please provide source text");
      return;
    }
    if (!topicId) {
      setMessage("Please select a topic");
      return;
    }
    if (count < 1 || count > 50) {
      setMessage("Count must be between 1 and 50");
      return;
    }
    setGenerating(true);
    try {
      await api.post("/admin/questions/generation/generate", {
        source_text: sourceText,
        topic_id: topicId || null,
        question_type: questionType,
        difficulty,
        count,
        auto_approve_unique: autoApprove,
      });
      setMessage("Generation started! Refresh batches to see progress.");
      setSourceText("");
      setTimeout(loadBatches, 2000);
    } catch {
      setMessage("Failed to start generation");
    } finally {
      setGenerating(false);
    }
  };

  const handleApprove = async (id: string) => {
    try {
      await api.post(`/admin/questions/generation/staged/${id}/approve`);
      setMessage("Question approved and added to bank");
      loadStaged();
      loadBatches();
    } catch {
      setMessage("Failed to approve question");
    }
  };

  const handleReject = async (id: string) => {
    try {
      await api.post(`/admin/questions/generation/staged/${id}/reject`);
      setMessage("Question rejected");
      loadStaged();
      loadBatches();
    } catch {
      setMessage("Failed to reject question");
    }
  };

  const handleCompare = async (item: StagedItem) => {
    if (!item.matched_question_id) return;
    setCompareItem(item);
    setLoadingCompare(true);
    try {
      const res = await api.get(`/admin/questions/generation/questions/${item.matched_question_id}`);
      setMatchedQuestion(res.data);
    } catch {
      setMessage("Failed to load matched question");
      setCompareItem(null);
    } finally {
      setLoadingCompare(false);
    }
  };

  const closeCompare = () => {
    setCompareItem(null);
    setMatchedQuestion(null);
  };

  const bandColor = (band: string | null) => {
    switch (band) {
      case "high_dup": return "bg-red-100 text-red-700";
      case "review": return "bg-yellow-100 text-yellow-700";
      case "unique": return "bg-green-100 text-green-700";
      default: return "bg-gray-100 text-gray-600";
    }
  };

  const statusColor = (status: string) => {
    switch (status) {
      case "approved": return "bg-green-100 text-green-700";
      case "rejected":
      case "auto_rejected": return "bg-red-100 text-red-700";
      case "pending": return "bg-blue-100 text-blue-700";
      default: return "bg-gray-100 text-gray-600";
    }
  };

  const batchStatusColor = (status: string) => {
    switch (status) {
      case "completed": return "text-green-600";
      case "failed": return "text-red-600";
      case "pending": return "text-gray-500";
      default: return "text-blue-600";
    }
  };

  return (
    <div className="space-y-6">
      {/* Generation Form */}
      <div className={`${card} p-6`}>
        <h2 className="text-base font-semibold mb-4">Generate Questions from Text</h2>
        <div className="space-y-4">
          <textarea
            className={`${inputClass} w-full min-h-[120px] py-2`}
            placeholder="Paste source material here (documentation, study notes, etc.)..."
            value={sourceText}
            onChange={(e) => setSourceText(e.target.value)}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <select className={selectClass} value={topicId} onChange={(e) => setTopicId(e.target.value)}>
              <option value="">No topic</option>
              {topics.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            <select className={selectClass} value={questionType} onChange={(e) => setQuestionType(e.target.value)}>
              <option value="text">Text</option>
              <option value="single_mcq">Single MCQ</option>
              <option value="multi_mcq">Multi MCQ</option>
            </select>
            <select className={selectClass} value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
              <option value="easy">Easy</option>
              <option value="medium">Medium</option>
              <option value="hard">Hard</option>
            </select>
            <input
              type="number"
              className={inputClass}
              min={1}
              max={50}
              value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              placeholder="Count"
            />
          </div>
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autoApprove}
                onChange={(e) => setAutoApprove(e.target.checked)}
                className="rounded"
              />
              Auto-approve unique questions (similarity &lt; 0.70)
            </label>
            <button
              className={btnPrimary}
              onClick={handleGenerate}
              disabled={generating || !sourceText.trim() || !topicId || count < 1 || count > 50}
            >
              {generating ? "Generating..." : "Generate Questions"}
            </button>
          </div>
        </div>
      </div>

      {/* Batches List */}
      <div className={`${card} p-6`}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold">Generation Batches</h2>
          <button onClick={loadBatches} className="text-sm text-blue-600 hover:underline">
            Refresh
          </button>
        </div>
        {loadingBatches ? (
          <p className="text-sm text-gray-500">Loading...</p>
        ) : batches.length === 0 ? (
          <p className="text-sm text-gray-500">No batches yet. Generate some questions above.</p>
        ) : (
          <div className="divide-y">
            {batches.map((b) => (
              <div
                key={b.id}
                className={`py-3 flex items-center justify-between cursor-pointer hover:bg-gray-50 px-2 rounded ${selectedBatchId === b.id ? "bg-blue-50" : ""}`}
                onClick={() => { setSelectedBatchId(b.id); setStagedPage(1); }}
              >
                <div>
                  <span className={`text-sm font-medium ${batchStatusColor(b.status)}`}>
                    {b.status}
                  </span>
                  <span className="text-sm text-gray-600 ml-3">
                    {b.total_generated} generated · {b.total_approved} approved · {b.total_rejected} rejected
                  </span>
                </div>
                <span className="text-xs text-gray-400">
                  {new Date(b.created_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>
        )}
        {batchesTotal > batchesPageSize && (
          <div className="flex items-center justify-between pt-3 mt-3 border-t">
            <span className="text-xs text-gray-500">
              Page {batchesPage} of {Math.ceil(batchesTotal / batchesPageSize)} ({batchesTotal} total)
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => setBatchesPage((p) => Math.max(1, p - 1))}
                disabled={batchesPage === 1}
                className="text-xs px-2 py-1 border rounded disabled:opacity-40"
              >
                Prev
              </button>
              <button
                onClick={() => setBatchesPage((p) => p + 1)}
                disabled={batchesPage * batchesPageSize >= batchesTotal}
                className="text-xs px-2 py-1 border rounded disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Staged Questions Review */}
      {selectedBatchId && (
        <div className={`${card} p-6`}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-base font-semibold">Review Staged Questions</h2>
            <div className="flex gap-2">
              <select className={`${selectClass} text-xs h-8`} value={filterStatus} onChange={(e) => { setFilterStatus(e.target.value); setStagedPage(1); }}>
                <option value="">All statuses</option>
                <option value="pending">Pending</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
                <option value="auto_rejected">Auto-rejected</option>
              </select>
              <select className={`${selectClass} text-xs h-8`} value={filterBand} onChange={(e) => { setFilterBand(e.target.value); setStagedPage(1); }}>
                <option value="">All bands</option>
                <option value="unique">Unique</option>
                <option value="review">Review</option>
                <option value="high_dup">High Duplicate</option>
              </select>
            </div>
          </div>

          {loadingStaged ? (
            <p className="text-sm text-gray-500">Loading...</p>
          ) : staged.length === 0 ? (
            <p className="text-sm text-gray-500">No staged questions found.</p>
          ) : (
            <div className="space-y-3">
              {staged.map((sq) => (
                <div key={sq.id} className="border rounded-lg p-4 space-y-2">
                  <div className="flex items-start justify-between gap-4">
                    <p className="text-sm flex-1">{sq.question_text}</p>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={`text-xs px-2 py-0.5 rounded ${bandColor(sq.match_band)}`}>
                        {sq.match_band || "—"}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${statusColor(sq.status)}`}>
                        {sq.status}
                      </span>
                    </div>
                  </div>
                  {sq.similarity_score !== null && (
                    <p className="text-xs text-gray-500">
                      Similarity: {(sq.similarity_score * 100).toFixed(1)}%
                      {sq.difficulty && <> · {sq.difficulty}</>}
                      {sq.question_type && <> · {sq.question_type}</>}
                    </p>
                  )}
                  {sq.options && sq.options.length > 0 && (
                    <div className="text-xs text-gray-600 pl-3">
                      {sq.options.map((o, i) => (
                        <div key={i} className={o.is_correct ? "font-semibold text-green-700" : ""}>
                          {String.fromCharCode(65 + i)}. {o.option_text}
                        </div>
                      ))}
                    </div>
                  )}
                  {sq.reference_answer && (
                    <p className="text-xs text-gray-500 italic">Ref: {sq.reference_answer.slice(0, 200)}</p>
                  )}
                  <div className="flex gap-2 pt-1">
                    {sq.matched_question_id && (
                      <button
                        onClick={() => handleCompare(sq)}
                        className="text-xs px-3 py-1 bg-purple-600 text-white rounded hover:bg-purple-700"
                      >
                        Compare
                      </button>
                    )}
                    {sq.status === "pending" && (
                      <>
                        <button
                          onClick={() => handleApprove(sq.id)}
                          className="text-xs px-3 py-1 bg-green-600 text-white rounded hover:bg-green-700"
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => handleReject(sq.id)}
                          className="text-xs px-3 py-1 bg-red-600 text-white rounded hover:bg-red-700"
                        >
                          Reject
                        </button>
                      </>
                    )}
                  </div>
                </div>
              ))}

              {/* Pagination */}
              {stagedTotal > 20 && (
                <div className="flex items-center justify-between pt-3">
                  <span className="text-xs text-gray-500">
                    Showing {(stagedPage - 1) * 20 + 1}–{Math.min(stagedPage * 20, stagedTotal)} of {stagedTotal}
                  </span>
                  <div className="flex gap-1">
                    <button
                      onClick={() => setStagedPage((p) => Math.max(1, p - 1))}
                      disabled={stagedPage === 1}
                      className="text-xs px-2 py-1 border rounded disabled:opacity-40"
                    >
                      Prev
                    </button>
                    <button
                      onClick={() => setStagedPage((p) => p + 1)}
                      disabled={stagedPage * 20 >= stagedTotal}
                      className="text-xs px-2 py-1 border rounded disabled:opacity-40"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Comparison Modal */}
      {compareItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={closeCompare}>
          <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[80vh] overflow-auto m-4" onClick={(e) => e.stopPropagation()}>
            <div className="sticky top-0 bg-white border-b px-6 py-4 flex items-center justify-between">
              <h3 className="text-base font-semibold">
                Similarity Comparison — {((compareItem.similarity_score || 0) * 100).toFixed(1)}% match
              </h3>
              <button onClick={closeCompare} className="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
            </div>
            <div className="p-6 grid grid-cols-2 gap-6">
              {/* Generated Question */}
              <div>
                <h4 className="text-sm font-semibold text-blue-700 mb-2">Generated (New)</h4>
                <div className="border rounded-lg p-4 space-y-2 bg-blue-50/50">
                  <p className="text-sm">{compareItem.question_text}</p>
                  {compareItem.options && compareItem.options.length > 0 && (
                    <div className="text-xs text-gray-600 pl-2 space-y-0.5">
                      {compareItem.options.map((o, i) => (
                        <div key={i} className={o.is_correct ? "font-semibold text-green-700" : ""}>
                          {String.fromCharCode(65 + i)}. {o.option_text}
                        </div>
                      ))}
                    </div>
                  )}
                  {compareItem.reference_answer && (
                    <p className="text-xs text-gray-500 italic mt-2">Ref: {compareItem.reference_answer}</p>
                  )}
                  <div className="text-xs text-gray-400 mt-2">
                    Type: {compareItem.question_type} · Difficulty: {compareItem.difficulty}
                  </div>
                </div>
              </div>

              {/* Matched Existing Question */}
              <div>
                <h4 className="text-sm font-semibold text-orange-700 mb-2">Existing (Match)</h4>
                {loadingCompare ? (
                  <p className="text-sm text-gray-500">Loading...</p>
                ) : matchedQuestion ? (
                  <div className="border rounded-lg p-4 space-y-2 bg-orange-50/50">
                    <p className="text-sm">{matchedQuestion.question_text}</p>
                    {matchedQuestion.options && matchedQuestion.options.length > 0 && (
                      <div className="text-xs text-gray-600 pl-2 space-y-0.5">
                        {matchedQuestion.options.map((o, i) => (
                          <div key={i} className={o.is_correct ? "font-semibold text-green-700" : ""}>
                            {String.fromCharCode(65 + i)}. {o.option_text}
                          </div>
                        ))}
                      </div>
                    )}
                    {matchedQuestion.reference_answer && (
                      <p className="text-xs text-gray-500 italic mt-2">Ref: {matchedQuestion.reference_answer}</p>
                    )}
                    <div className="text-xs text-gray-400 mt-2">
                      Type: {matchedQuestion.question_type} · Difficulty: {matchedQuestion.difficulty}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-gray-500">No match data available</p>
                )}
              </div>
            </div>
            {compareItem.status === "pending" && (
              <div className="border-t px-6 py-4 flex gap-3 justify-end">
                <button
                  onClick={() => { handleApprove(compareItem.id); closeCompare(); }}
                  className="text-sm px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
                >
                  Approve Anyway
                </button>
                <button
                  onClick={() => { handleReject(compareItem.id); closeCompare(); }}
                  className="text-sm px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
                >
                  Reject
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
