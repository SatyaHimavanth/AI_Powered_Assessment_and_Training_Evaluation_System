import { useEffect, useState } from "react";
import type { PendingRequest } from "./types";
import { card } from "./types";
import api from "../../api";

interface PracticeAccessReq {
  id: string;
  user_id: string;
  user_name: string;
  username: string;
  reason?: string | null;
  requested_days?: number | null;
  requested_tests_per_day?: number | null;
  status: string;
  requested_at: string;
}

interface InterviewAccessReq {
  id: string;
  user_id: string;
  user_name: string;
  username: string;
  template_id: string;
  template_title: string;
  request_type: string;
  reason?: string | null;
  status: string;
  requested_at: string;
}

interface Props {
  pending: PendingRequest[];
  setMessage: (msg: string) => void;
  reload: () => void;
}

export default function Approvals({ pending, setMessage, reload }: Props) {
  const [practiceRequests, setPracticeRequests] = useState<PracticeAccessReq[]>([]);
  const [interviewRequests, setInterviewRequests] = useState<InterviewAccessReq[]>([]);
  const [daysMap, setDaysMap] = useState<Record<string, number>>({});
  const [testsMap, setTestsMap] = useState<Record<string, number>>({});

  useEffect(() => {
    loadPracticeRequests();
    loadInterviewRequests();
  }, []);

  async function loadPracticeRequests() {
    try {
      const res = await api.get("/admin/practice-access-requests");
      setPracticeRequests(res.data);
      const defaults: Record<string, number> = {};
      const testsDefaults: Record<string, number> = {};
      res.data.forEach((r: PracticeAccessReq) => {
        defaults[r.id] = (r.requested_days ?? 14);
        testsDefaults[r.id] = (r.requested_tests_per_day ?? 1);
      });
      setDaysMap(defaults);
      setTestsMap(testsDefaults);
    } catch { /* ignore */ }
  }

  async function loadInterviewRequests() {
    try {
      const res = await api.get("/admin/interviews/access-requests?status=pending");
      setInterviewRequests(Array.isArray(res.data) ? res.data : []);
    } catch {
      // ignore
    }
  }

  const handleApprove = async (id: string) => {
    try {
      const res = await api.post(`/admin/approve/${id}`);
      setMessage(res.data.message);
      reload();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to approve");
    }
  };

  const handleReject = async (id: string) => {
    try {
      const res = await api.post(`/admin/reject/${id}`);
      setMessage(res.data.message);
      reload();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to reject");
    }
  };

  const handleApprovePractice = async (id: string) => {
    try {
      const days = daysMap[id] || 14;
      const tests_per_day = testsMap[id] || 1;
      const res = await api.post(`/admin/practice-access-requests/${id}/approve`, { days, tests_per_day });
      setMessage(res.data.message);
      loadPracticeRequests();
      reload();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to approve");
    }
  };

  const handleRejectPractice = async (id: string) => {
    try {
      const res = await api.post(`/admin/practice-access-requests/${id}/reject`);
      setMessage(res.data.message);
      loadPracticeRequests();
      reload();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to reject");
    }
  };

  const handleApproveInterview = async (id: string) => {
    try {
      const res = await api.post(`/admin/interviews/access-requests/${id}/approve`, { days: 14 });
      setMessage(res.data.message);
      loadInterviewRequests();
      reload();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to approve interview request");
    }
  };

  const handleRejectInterview = async (id: string) => {
    try {
      const res = await api.post(`/admin/interviews/access-requests/${id}/reject`);
      setMessage(res.data.message);
      loadInterviewRequests();
      reload();
    } catch (err: unknown) {
      console.error(err);
      setMessage("Failed to reject interview request");
    }
  };

  return (
    <div className="space-y-8">
      {/* User Registration Requests */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3 uppercase tracking-wide">User Registrations</h3>
        {pending.length === 0 ? (
          <div className={`${card} p-12 text-center`}>
            <p className="text-[var(--color-text-secondary)] text-sm">No pending registration requests.</p>
          </div>
        ) : (
          <div className={`${card} overflow-hidden`}>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] bg-gray-50/50">
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Name</th>
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Username</th>
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Email</th>
                  {/* <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Contact Email</th> */}
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Account</th>
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Requested</th>
                  <th className="text-right px-5 py-3 font-medium text-[var(--color-text-secondary)]">Actions</th>
                </tr>
              </thead>
              <tbody>
                {pending.map((req) => (
                  <tr key={req.id} className="border-b border-[var(--color-border)] last:border-0 hover:bg-gray-50/50 transition-colors">
                    <td className="px-5 py-3.5 font-medium">{req.name}</td>
                    <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{req.username}</td>
                    <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{req.email}</td>
                    {/* <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{req.contact_email}</td> */}
                    <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{req.account || "—"}</td>
                    <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">
                      {new Date(req.requested_at).toLocaleDateString()}
                    </td>
                    <td className="px-5 py-3.5 text-right space-x-2">
                      <button
                        onClick={() => handleApprove(req.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-green-50 text-[var(--color-success)] hover:bg-green-100 cursor-pointer transition-colors"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleReject(req.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-red-50 text-[var(--color-danger)] hover:bg-red-100 cursor-pointer transition-colors"
                      >
                        Reject
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Practice Access Requests */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3 uppercase tracking-wide">Practice Test Access Requests</h3>
        {practiceRequests.length === 0 ? (
          <div className={`${card} p-12 text-center`}>
            <p className="text-[var(--color-text-secondary)] text-sm">No pending practice access requests.</p>
          </div>
        ) : (
          <div className={`${card} overflow-hidden`}>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] bg-gray-50/50">
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Name</th>
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Username</th>
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Reason</th>
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Requested</th>
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Days</th>
                  <th className="text-right px-5 py-3 font-medium text-[var(--color-text-secondary)]">Actions</th>
                </tr>
              </thead>
              <tbody>
                {practiceRequests.map((req) => (
                  <tr key={req.id} className="border-b border-[var(--color-border)] last:border-0 hover:bg-gray-50/50 transition-colors">
                    <td className="px-5 py-3.5 font-medium">{req.user_name}</td>
                    <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{req.username}</td>
                    <td className="px-5 py-3.5 text-[var(--color-text-secondary)]" title={req.reason || undefined}>
                      {req.reason ? (req.reason.length > 15 ? `${req.reason.slice(0,15)}...` : req.reason) : "—"}
                    </td>
                    <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">
                      {new Date(req.requested_at).toLocaleDateString()}
                    </td>
                    <td className="px-5 py-3.5">
                      <input
                        type="number"
                        min={1}
                        max={30}
                        value={daysMap[req.id] || 14}
                        onChange={(e) => setDaysMap((prev) => ({ ...prev, [req.id]: Math.min(30, Math.max(1, Number(e.target.value))) }))}
                        className="w-16 px-2 py-1 border border-gray-300 rounded text-xs text-center focus:border-blue-500 focus:outline-none"
                      />
                      <label className="text-xs font-medium text-gray-600 ml-4 mr-2">Tests/day:</label>
                      <input
                        type="number"
                        min={1}
                        max={3}
                        value={testsMap[req.id] || 1}
                        onChange={(e) => setTestsMap((prev) => ({ ...prev, [req.id]: Math.min(3, Math.max(1, Number(e.target.value))) }))}
                        className="w-12 px-2 py-1 border border-gray-300 rounded text-xs text-center focus:border-blue-500 focus:outline-none"
                      />
                    </td>
                    <td className="px-5 py-3.5 text-right space-x-2">
                      <button
                        onClick={() => handleApprovePractice(req.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-green-50 text-[var(--color-success)] hover:bg-green-100 cursor-pointer transition-colors"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleRejectPractice(req.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-red-50 text-[var(--color-danger)] hover:bg-red-100 cursor-pointer transition-colors"
                      >
                        Reject
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Interview Access Requests */}
      <div>
        <h3 className="text-sm font-semibold text-gray-700 mb-3 uppercase tracking-wide">Interview Access Requests</h3>
        {interviewRequests.length === 0 ? (
          <div className={`${card} p-12 text-center`}>
            <p className="text-[var(--color-text-secondary)] text-sm">No pending interview access requests.</p>
          </div>
        ) : (
          <div className={`${card} overflow-hidden`}>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--color-border)] bg-gray-50/50">
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Name</th>
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Template</th>
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Type</th>
                  <th className="text-left px-5 py-3 font-medium text-[var(--color-text-secondary)]">Requested</th>
                  <th className="text-right px-5 py-3 font-medium text-[var(--color-text-secondary)]">Actions</th>
                </tr>
              </thead>
              <tbody>
                {interviewRequests.map((req) => (
                  <tr key={req.id} className="border-b border-[var(--color-border)] last:border-0 hover:bg-gray-50/50 transition-colors">
                    <td className="px-5 py-3.5 font-medium">{req.user_name}</td>
                    <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{req.template_title}</td>
                    <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{req.request_type}</td>
                    <td className="px-5 py-3.5 text-[var(--color-text-secondary)]">{new Date(req.requested_at).toLocaleDateString()}</td>
                    <td className="px-5 py-3.5 text-right space-x-2">
                      <button
                        onClick={() => handleApproveInterview(req.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-green-50 text-[var(--color-success)] hover:bg-green-100 cursor-pointer transition-colors"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleRejectInterview(req.id)}
                        className="inline-flex items-center h-8 px-3 text-xs font-medium rounded-[var(--radius-sm)] bg-red-50 text-[var(--color-danger)] hover:bg-red-100 cursor-pointer transition-colors"
                      >
                        Reject
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
