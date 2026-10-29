import type { TopicInfo, UserInfo, PendingRequest, BatchInfo } from "./types";
import { card } from "./types";

interface Props {
  users: UserInfo[];
  pending: PendingRequest[];
  topics: TopicInfo[];
  batches: BatchInfo[];
  onNavigate: (tab: "approvals" | "assessments" | "results" | "questions" | "batches") => void;
  counts?: {
    total_users: number;
    pending_registrations: number;
    total_topics: number;
    total_batches: number;
  };
}

export default function Dashboard({ users, pending, topics, batches, counts, onNavigate }: Props) {
  const totalUsers = counts?.total_users ?? users.length;
  const pendingReqs = counts?.pending_registrations ?? pending.length;
  const totalTopics = counts?.total_topics ?? topics.length;
  const totalBatches = counts?.total_batches ?? batches.length;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-4 gap-5">
        <div className={`${card} p-6`}>
          <p className="text-sm text-[var(--color-text-secondary)] mb-1">Total Users</p>
          <p className="text-3xl font-semibold">{totalUsers}</p>
        </div>
        <div className={`${card} p-6`}>
          <p className="text-sm text-[var(--color-text-secondary)] mb-1">Pending Requests</p>
          <p className="text-3xl font-semibold text-[var(--color-warning)]">{pendingReqs}</p>
        </div>
        <div className={`${card} p-6`}>
          <p className="text-sm text-[var(--color-text-secondary)] mb-1">Topics</p>
          <p className="text-3xl font-semibold text-[var(--color-primary)]">{totalTopics}</p>
        </div>
        <div className={`${card} p-6`}>
          <p className="text-sm text-[var(--color-text-secondary)] mb-1">Batches</p>
          <p className="text-3xl font-semibold text-purple-600">{totalBatches}</p>
        </div>
      </div>
      <section className={`${card} p-6`} aria-labelledby="admin-quick-actions">
        <h2 id="admin-quick-actions" className="text-sm font-semibold mb-1">Quick actions</h2>
        <p className="text-sm text-[var(--color-text-secondary)] mb-4">Go straight to the most common admin tasks.</p>
        <div className="flex flex-wrap gap-3">
          <button onClick={() => onNavigate("approvals")} className="rounded-[var(--radius-sm)] bg-amber-50 px-4 py-2 text-sm font-medium text-amber-800 hover:bg-amber-100">Review requests</button>
          <button onClick={() => onNavigate("assessments")} className="rounded-[var(--radius-sm)] bg-blue-50 px-4 py-2 text-sm font-medium text-[var(--color-primary)] hover:bg-blue-100">Create or schedule assessment</button>
          <button onClick={() => onNavigate("results")} className="rounded-[var(--radius-sm)] bg-purple-50 px-4 py-2 text-sm font-medium text-purple-700 hover:bg-purple-100">Review results</button>
          <button onClick={() => onNavigate("questions")} className="rounded-[var(--radius-sm)] bg-gray-100 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-200">Manage question bank</button>
        </div>
      </section>
    </div>
  );
}
