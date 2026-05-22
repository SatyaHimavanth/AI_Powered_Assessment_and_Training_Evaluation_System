import type { TopicInfo, UserInfo, PendingRequest, BatchInfo } from "./types";
import { card } from "./types";

interface Props {
  users: UserInfo[];
  pending: PendingRequest[];
  topics: TopicInfo[];
  batches: BatchInfo[];
  counts?: {
    total_users: number;
    pending_registrations: number;
    total_topics: number;
    total_batches: number;
  };
}

export default function Dashboard({ users, pending, topics, batches, counts }: Props) {
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
    </div>
  );
}
