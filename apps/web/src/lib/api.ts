"use client";

// Thin typed API client. All requests carry the session cookie (credentials).
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let detail = text || response.statusText || "Request failed";
    try {
      const body = JSON.parse(text) as { detail?: string };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // Plain-text API errors are already useful.
    }
    throw new ApiError(response.status, detail.slice(0, 300));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: (files: FileList | File[]) => {
    const form = new FormData();
    for (const file of Array.from(files)) form.append("files", file);
    return request<{ document_id: string; filename: string; duplicate: boolean }[]>(
      "/inbox/upload",
      { method: "POST", body: form },
    );
  },
  uploadIcs: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ imported: number; skipped: number }>("/calendar/import-ics", {
      method: "POST",
      body: form,
    });
  },
};

// ---- shared types (hand-written; regenerate from OpenAPI later) ----

export interface DocumentOut {
  id: string;
  original_filename: string;
  doc_kind: string;
  title: string | null;
  topic: string | null;
  summary: string | null;
  importance: number | null;
  status: string;
  error: string | null;
  chunk_count: number;
  created_at: string;
  processed_at: string | null;
}

export interface ReviewOut {
  id: string;
  kind: string;
  question: string;
  payload: Record<string, unknown>;
  status: string;
}

export interface DeadlineOut {
  id: string;
  title: string;
  normalized_at: string | null;
  date_is_exact: boolean;
  raw_expression: string;
  confidence: number;
  explicit: boolean;
  status: string;
  provenance: Record<string, unknown>;
}

export interface EventOut {
  id: string;
  kind: "hard" | "soft" | "deadline" | "focus" | "reminder";
  title: string;
  starts_at: string;
  ends_at: string;
  all_day: boolean;
  provider: string;
  editable: boolean;
  task_id: string | null;
}

export interface ProposalOut {
  id: string;
  action_type: string;
  payload: Record<string, unknown>;
  reason: string;
  risk_level: string;
  proposed_by: string;
  status: string;
  created_at: string;
}

export interface Briefing {
  greeting: string;
  today: { id: string; title: string; kind: string; starts_at: string; ends_at: string }[];
  top_priorities: { task_id: string; title: string; score: number; why: string; status: string }[];
  risks: { message: string; severity: string }[];
  suggestions: { action: string; why: string }[];
  upcoming: Record<string, number>;
  readiness: {
    deadline_id: string;
    title: string;
    score: number;
    components: Record<string, unknown>;
  }[];
}

export interface GraphOut {
  entities: { id: string; kind: string; name: string; aliases: string[]; confidence: number }[];
  relations: {
    id: string;
    subject_id?: string;
    subject_name: string;
    predicate: string;
    object_id?: string;
    object_name: string;
    confidence: number;
    provenance?: Record<string, unknown>;
  }[];
  projects: { id: string; name: string; kind: string }[];
}

export interface AskAnswer {
  answer: string;
  path: string;
  citations: { title?: string | null; page?: number | null; quote: string; document_id?: string | null }[];
  facts: Record<string, unknown>;
}
