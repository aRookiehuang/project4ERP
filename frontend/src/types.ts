export type Cell = string | number | null;
export interface Column {
  key: string;
  label: string;
  unit: string;
  type: string;
}
export interface ChartSpec {
  type: string;
  x?: string;
  series?: string[];
  group?: string;
  data?: Record<string, Cell>[];
  reason?: string;
}
export interface Result {
  status: string;
  answer: string;
  query_id?: string;
  result_id?: string;
  question?: string;
  code?: string;
  assumptions?: string[];
  rows?: Record<string, Cell>[];
  columns?: Column[];
  total_rows?: number;
  page?: number;
  page_size?: number;
  chart_spec?: ChartSpec;
  sql_display?: string;
  snapshot_at?: string;
  truncated?: boolean;
  time_range?: { start: string; end: string };
  timing?: { server_ms: number };
  versions?: { data: string; mode: string };
  metric_definitions?: Record<string, { label: string; definition: string }>;
}
export interface Message {
  id: string;
  question: string;
  status: string;
  response?: Result;
}
export interface Conversation {
  id: string;
  title: string;
}
export interface User {
  username: string;
  role: string;
  csrf_token: string;
}
