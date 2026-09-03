"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, EventOut, ProposalOut } from "@/lib/api";
import { useUser } from "@/lib/useUser";
import { fmtTime } from "@/lib/useUser";

const KIND_STYLE: Record<string, string> = {
  hard: "bg-stone-800 text-white",
  soft: "bg-stone-100 text-stone-700 border border-stone-200",
  deadline: "bg-red-50 text-red-700 border border-red-200",
  focus: "bg-emerald-50 text-emerald-800 border border-emerald-200",
  reminder: "bg-blue-50 text-blue-700 border border-blue-200",
};

export default function CalendarPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [events, setEvents] = useState<EventOut[]>([]);
  const [proposals, setProposals] = useState<ProposalOut[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.get<EventOut[]>("/calendar?days=14").then(setEvents).catch(() => {});
    api
      .get<ProposalOut[]>("/proposals?status_filter=pending")
      .then(setProposals)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) refresh();
  }, [user, refresh]);

  const weeks = useMemo(() => groupByDay(events), [events]);

  const recompute = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await api.post<{
        applied: boolean;
        sessions: number;
        proposals: number;
      }>("/schedule/recompute");
      setMessage(
        result.applied
          ? `Plan applied — ${result.sessions} focus sessions scheduled.`
          : `${result.proposals} suggestions prepared for your approval below.`,
      );
      refresh();
    } finally {
      setBusy(false);
    }
  };

  const decide = async (id: string, decision: string) => {
    await api.post(`/proposals/${id}/decide`, { decision });
    refresh();
  };

  const approveAll = async () => {
    await api.post("/proposals/approve-batch", {
      proposal_ids: proposals.map((p) => p.id),
    });
    refresh();
  };

  if (loading || !user) return null;

  return (
    <AppShell>
      <div className="space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-stone-900">Calendar</h1>
            <p className="text-sm text-stone-500 mt-1">
              Hard events are yours; focus blocks are the planner&apos;s suggestions.
            </p>
          </div>
          <button
            onClick={recompute}
            disabled={busy}
            className="text-sm rounded-full bg-stone-900 text-white px-4 py-2 hover:bg-stone-700 disabled:opacity-50"
          >
            {busy ? "Planning…" : "Recompute plan"}
          </button>
        </div>

        {message && <p className="text-sm text-stone-500">{message}</p>}

        <div className="flex gap-4 text-xs text-stone-500">
          {Object.entries(KIND_STYLE).map(([kind, style]) => (
            <span key={kind} className="inline-flex items-center gap-1.5">
              <span className={`inline-block h-2.5 w-2.5 rounded-full ${style}`} />
              {kind}
            </span>
          ))}
        </div>

        {proposals.length > 0 && (
          <section className="bg-white border border-stone-200 rounded-2xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xs font-medium uppercase tracking-wider text-stone-400">
                Proposed changes ({proposals.length})
              </h2>
              <button
                onClick={approveAll}
                className="text-xs rounded-full bg-stone-900 text-white px-3 py-1.5 hover:bg-stone-700"
              >
                Approve all {proposals.length}
              </button>
            </div>
            <ul className="space-y-3">
              {proposals.map((proposal) => {
                const payload = proposal.payload as {
                  title?: string;
                  starts_at?: string;
                  ends_at?: string;
                };
                return (
                  <li
                    key={proposal.id}
                    className="flex items-start justify-between gap-4 border border-stone-100 rounded-xl p-4"
                  >
                    <div>
                      <p className="text-sm font-medium text-stone-800">{payload.title}</p>
                      {payload.starts_at && (
                        <p className="text-xs text-stone-400 mt-0.5 tabular-nums">
                          {new Date(payload.starts_at).toLocaleString([], {
                            weekday: "short",
                            day: "numeric",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                          {" – "}
                          {payload.ends_at ? fmtTime(payload.ends_at) : ""}
                        </p>
                      )}
                      <p className="text-xs text-stone-500 mt-1">
                        Reason: {proposal.reason}
                      </p>
                    </div>
                    <div className="flex gap-2 shrink-0">
                      <button
                        onClick={() => decide(proposal.id, "approve")}
                        className="text-xs rounded-full bg-stone-900 text-white px-3 py-1.5 hover:bg-stone-700"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => decide(proposal.id, "reject")}
                        className="text-xs rounded-full border border-stone-200 px-3 py-1.5 text-stone-600 hover:bg-stone-50"
                      >
                        Reject
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <div className="grid grid-cols-1 md:grid-cols-7 gap-3">
          {weeks.map(([day, dayEvents]) => (
            <div key={day} className="bg-white border border-stone-200 rounded-xl p-3 min-h-40">
              <p className="text-xs font-medium text-stone-500 mb-2">{day}</p>
              <ul className="space-y-1.5">
                {dayEvents.map((event) => (
                  <li
                    key={event.id}
                    className={`rounded-lg px-2 py-1.5 text-xs ${KIND_STYLE[event.kind] ?? "bg-stone-100"}`}
                  >
                    <span className="opacity-70 tabular-nums">{fmtTime(event.starts_at)}</span>{" "}
                    {event.title}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}

function groupByDay(events: EventOut[]): [string, EventOut[]][] {
  const byDay = new Map<string, EventOut[]>();
  for (const event of events) {
    const key = new Date(event.starts_at).toLocaleDateString([], {
      weekday: "short",
      day: "numeric",
      month: "short",
    });
    byDay.set(key, [...(byDay.get(key) ?? []), event]);
  }
  return [...byDay.entries()];
}
