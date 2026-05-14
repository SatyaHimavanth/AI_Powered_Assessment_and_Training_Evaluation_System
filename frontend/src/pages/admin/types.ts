export interface PendingRequest {
  id: string;
  username: string;
  email: string;
  contact_email: string;
  name: string;
  account: string | null;
  status: string;
  requested_at: string;
}

export interface UserInfo {
  id: string;
  username: string;
  email: string;
  contact_email: string;
  name: string;
  account: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface TopicInfo {
  id: string;
  name: string;
  description: string | null;
}

export interface QuestionInfo {
  id: string;
  topic: string;
  type: string;
  difficulty: string;
  question: string;
  reference_answer: string | null;
  options: { text: string; is_correct: boolean }[] | null;
}

export interface UploadResult {
  topic: string;
  total_rows: number;
  imported: number;
  skipped: number;
  errors: string[];
}

export interface TopicConfig {
  topic_id: string;
  question_type: string;
  difficulty: string;
  question_count: number;
  section_name?: string;
  [key: string]: string | number | undefined;
}

export interface AssessmentListItem {
  id: string;
  title: string;
  description: string | null;
  duration: number;
  negative_marking: boolean;
  is_archived?: boolean;
  total_questions: number;
  batch_names: string[];
  start_time: string | null;
  end_time: string | null;
  created_at: string;
}

export interface AssessmentResult {
  id: string;
  title: string;
  description: string | null;
  duration: number;
  negative_marking: boolean;
  is_archived?: boolean;
  total_questions: number;
  topics: { topic_name: string; question_type: string; difficulty: string; question_count: number; selected_count: number; section_name?: string }[];
  batch_names: string[];
  start_time: string | null;
  end_time: string | null;
  created_at: string;
}

export interface BatchInfo {
  id: string;
  name: string;
  description: string | null;
  status: string;
  user_count: number;
}

/* Shared style constants */
export const card = "bg-white rounded-[var(--radius)] shadow-[var(--shadow)] border border-[var(--color-border)]";
export const inputClass =
  "h-10 px-3 border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-white text-sm placeholder:text-gray-400 hover:border-gray-400 focus:border-[var(--color-primary)] focus:ring-2 focus:ring-blue-100";
export const selectClass =
  "h-10 px-3 border border-[var(--color-border)] rounded-[var(--radius-sm)] bg-white text-sm hover:border-gray-400 focus:border-[var(--color-primary)] focus:ring-2 focus:ring-blue-100 cursor-pointer";
export const btnPrimary =
  "h-10 px-5 bg-[var(--color-primary)] text-white text-sm font-medium rounded-[var(--radius-sm)] hover:bg-[var(--color-primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer";
