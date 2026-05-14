import { useEffect, useState } from "react";
import { card } from "./types";
import api from "../../api";

interface PracticeAccessReq {
  id: string;
  user_id: string;
  user_name: string;
  username: string;
  reason: string | null;
  requested_days: number | null;
  requested_tests_per_day?: number | null;
  tests_per_day_granted?: number | null;
  status: string;
  requested_at: string;
  approved_at: string | null;
  expires_at: string | null;
  days_granted: number | null;
}

interface Props {
  setMessage: (msg: string) => void;
}

export default function PracticeAccess({ setMessage }: Props) {
  const [requests, setRequests] = useState<PracticeAccessReq[]>([]);
  const [daysMap, setDaysMap] = useState<Record<string, number>>({});
  const [testsMap, setTestsMap] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadRequests();
  }, []);

  async function loadRequests() {
    setLoading(true);
    try {
      const res = await api.get("/admin/practice-access-requests");
      setRequests(res.data);
      const defaults: Record<string, number> = {};
      const testsDefaults: Record<string, number> = {};
      res.data.forEach((r: PracticeAccessReq) => {
        defaults[r.id] = r.requested_days ?? 14;
        testsDefaults[r.id] = (r.requested_tests_per_day ?? 1);
      });
      setDaysMap(defaults);
      setTestsMap(testsDefaults);
    } catch (err: unknown) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  const handleApprove = async (id: string) => {
    try {
      const days = daysMap[id] || 14;
      const tests_per_day = testsMap[id] || 1;
      const res = await api.post(`/admin/practice-access-requests/${id}/approve`, { days, tests_per_day });
      setMessage(res.data.message);
      loadRequests();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to approve");
    }
  };

  const handleReject = async (id: string) => {
    try {
      const res = await api.post(`/admin/practice-access-requests/${id}/reject`);
      setMessage(res.data.message);
      loadRequests();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to reject");
    }
  };

  if (loading) {
    return (
      <div className={`${card} p-12 text-center`}>
        <div className="animate-spin w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full mx-auto" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {requests.length === 0 ? (
        <div className={`${card} p-12 text-center`}>
          <p className="text-[var(--color-text-secondary)] text-sm">No pending practice access requests.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {requests.map((req) => (
            <div key={req.id} className={`${card} p-5`}>
              <div className="flex items-start justify-between">
                <div className="space-y-2">
                  <div className="flex items-center gap-3">
                    <h3 className="text-sm font-semibold text-gray-900">{req.user_name}</h3>
                    <span className="text-xs text-gray-500">@{req.username}</span>
                  </div>

                  {req.reason && (
                    <div className="bg-gray-50 border border-gray-100 rounded-lg px-3 py-2">
                      <p className="text-xs font-medium text-gray-500 mb-0.5">Reason</p>
                      <p className="text-sm text-gray-700">{req.reason}</p>
                    </div>
                  )}

                  <div className="flex items-center gap-4 text-xs text-gray-500">
                    <span>Requested: {new Date(req.requested_at).toLocaleDateString()}</span>
                    <span>Duration requested: <strong className="text-gray-700">{req.requested_days || 14} days</strong></span>
                  </div>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <label className="text-xs font-medium text-gray-600">Grant access for:</label>
                  <input
                    type="number"
                    min={1}
                    max={30}
                    value={daysMap[req.id] || 14}
                    onChange={(e) => setDaysMap((prev) => ({
                      ...prev,
                      [req.id]: Math.min(30, Math.max(1, Number(e.target.value))),
                    }))}
                    className="w-16 px-2 py-1.5 border border-gray-300 rounded text-xs text-center focus:border-blue-500 focus:outline-none"
                  />
                  <span className="text-xs text-gray-500">days (max 30)</span>
                    <label className="text-xs font-medium text-gray-600 ml-4">Tests/day:</label>
                    <input
                      type="number"
                      min={1}
                      max={3}
                      value={testsMap[req.id] || 1}
                      onChange={(e) => setTestsMap((prev) => ({ ...prev, [req.id]: Math.min(3, Math.max(1, Number(e.target.value))) }))}
                      className="w-12 px-2 py-1.5 border border-gray-300 rounded text-xs text-center focus:border-blue-500 focus:outline-none"
                    />
                    <span className="text-xs text-gray-500">/day (max 3)</span>
                </div>

                <div className="flex gap-2">
                  <button
                    onClick={() => handleApprove(req.id)}
                    className="inline-flex items-center h-8 px-4 text-xs font-medium rounded-[var(--radius-sm)] bg-green-50 text-[var(--color-success)] hover:bg-green-100 cursor-pointer transition-colors"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => handleReject(req.id)}
                    className="inline-flex items-center h-8 px-4 text-xs font-medium rounded-[var(--radius-sm)] bg-red-50 text-[var(--color-danger)] hover:bg-red-100 cursor-pointer transition-colors"
                  >
                    Reject
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
