import type { TopicInfo, UserInfo, PendingRequest, BatchInfo } from "./types";
import { card } from "./types";

interface Props {
  users: UserInfo[];
  pending: PendingRequest[];
  topics: TopicInfo[];
  batches: BatchInfo[];
}

export default function Dashboard({ users, pending, topics, batches }: Props) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-4 gap-5">
        <div className={`${card} p-6`}>
          <p className="text-sm text-[var(--color-text-secondary)] mb-1">Total Users</p>
          <p className="text-3xl font-semibold">{users.length}</p>
        </div>
        <div className={`${card} p-6`}>
          <p className="text-sm text-[var(--color-text-secondary)] mb-1">Pending Requests</p>
          <p className="text-3xl font-semibold text-[var(--color-warning)]">{pending.length}</p>
        </div>
        <div className={`${card} p-6`}>
          <p className="text-sm text-[var(--color-text-secondary)] mb-1">Topics</p>
          <p className="text-3xl font-semibold text-[var(--color-primary)]">{topics.length}</p>
        </div>
        <div className={`${card} p-6`}>
          <p className="text-sm text-[var(--color-text-secondary)] mb-1">Batches</p>
          <p className="text-3xl font-semibold text-purple-600">{batches.length}</p>
        </div>
      </div>
    </div>
  );
}
