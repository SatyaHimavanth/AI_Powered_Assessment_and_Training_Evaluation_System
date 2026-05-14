import { useEffect, useState } from "react";
import api from "../../api";
import CircularProgress from "../../components/CircularProgress";

interface UserPerformance {
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

export default function Performance() {
  const [performance, setPerformance] = useState<UserPerformance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadPerformance() {
      try {
        const res = await api.get("/user/assessments/me/performance");
        setPerformance(res.data);
      } catch (err: unknown) {
        console.error(err);
        setError("Failed to load performance data");
      } finally {
        setLoading(false);
      }
    }

    loadPerformance();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-50 flex items-center justify-center">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-600">Loading your performance report...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-50 p-6">
        <div className="max-w-4xl mx-auto">
          <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
            <p className="text-red-700 font-medium">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!performance) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-50 p-6">
        <div className="max-w-4xl mx-auto">
          <div className="bg-white rounded-lg shadow p-6 text-center">
            <p className="text-gray-600">No performance data available yet.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-50 p-6">
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-center">
          <h1 className="text-3xl font-bold text-gray-900">Complete Report</h1>
        </div>

        {/* User Info & Overall Stats */}
        <div className="bg-white rounded-lg shadow-lg p-8 space-y-6">
          {/* User Info */}
          <div className="flex items-center justify-between pb-6 border-b border-gray-200">
            <div>
              <h2 className="text-2xl font-semibold text-gray-900">{performance.user_name}</h2>
              <p className="text-gray-600">@{performance.username}</p>
              <p className="text-sm text-gray-500">{performance.email}</p>
            </div>
          </div>

          {/* Overall Stats */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div className="flex flex-col items-center p-6 bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg border border-blue-200">
              <p className="text-sm text-gray-600 mb-2">Assessments Taken</p>
              <p className="text-3xl font-bold text-blue-600">
                {performance.completed_assessments}/{performance.total_assessments}
              </p>
            </div>

            <div className="flex flex-col items-center p-6 bg-gradient-to-br from-indigo-50 to-indigo-100 rounded-lg border border-indigo-200">
              <p className="text-sm text-gray-600 mb-2">Average Score</p>
              <div className="flex items-end gap-2">
                <p className={`text-3xl font-bold ${
                  performance.average_score !== null && performance.average_score >= 70
                    ? "text-green-600"
                    : performance.average_score !== null && performance.average_score >= 40
                    ? "text-yellow-600"
                    : "text-red-600"
                }`}>
                  {performance.average_score !== null ? performance.average_score : "—"}
                </p>
                {performance.average_score !== null && <p className="text-gray-600">%</p>}
              </div>
            </div>

            <div className="flex flex-col items-center p-6 bg-gradient-to-br from-purple-50 to-purple-100 rounded-lg border border-purple-200">
              <p className="text-sm text-gray-600 mb-2">Topics Covered</p>
              <p className="text-3xl font-bold text-purple-600">{performance.topic_performance.length}</p>
            </div>

            <div className="flex flex-col items-center p-6 bg-gradient-to-br from-pink-50 to-pink-100 rounded-lg border border-pink-200">
              <p className="text-sm text-gray-600 mb-2">Completion Rate</p>
              <p className="text-3xl font-bold text-pink-600">
                {performance.total_assessments > 0
                  ? Math.round((performance.completed_assessments / performance.total_assessments) * 100)
                  : 0}
                %
              </p>
            </div>
          </div>
        </div>

        {/* Topic Performance */}
        {performance.topic_performance.length > 0 && (
            <div className="bg-white rounded-lg shadow-lg p-8">
            <h3 className="text-2xl font-bold text-gray-900 mb-8">Topic Mastery</h3>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-8 place-items-center">
              {performance.topic_performance.map((tp, idx) => (
                <div key={idx} className="flex flex-col items-center w-full">
                  <CircularProgress
                    percentage={tp.average_percentage}
                    label={tp.topic_name}
                    size={150}
                    strokeWidth={11}
                  />
                  <p className="text-xs text-gray-500 mt-2">
                    {tp.assessment_count} test{tp.assessment_count !== 1 ? "s" : ""}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Improvement Suggestions (per-topic messages based on score) */}
        {performance.topic_performance.length > 0 && (
          <div className="bg-white rounded-lg shadow-lg p-8">
            <h3 className="text-2xl font-bold text-gray-900 mb-6">Focus Areas for Improvement</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {performance.topic_performance.map((tp, idx) => {
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
                  <div
                    key={idx}
                    className={`p-4 bg-gradient-to-r ${from} ${to} ${border} rounded-lg flex items-start gap-3 border`}
                  >
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
        )}
      </div>
    </div>
  );
}
