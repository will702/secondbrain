"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, EventOut, ProposalOut } from "@/lib/api";
import { useUser, fmtTime } from "@/lib/useUser";
import {
  CalendarIcon,
  ClockIcon,
  SparklesIcon,
  CheckCircleIcon,
  RefreshCwIcon,
} from "@/components/Icons";

const KIND_STYLE: Record<string, { badge: string; pill: string; label: string }> = {
  hard: {
    badge: "bg-stone-900 text-white",
    pill: "bg-stone-900 text-white border-stone-900",
    label: "Commitment / Meeting",
  },
  soft: {
    badge: "bg-stone-100 text-stone-700 border border-stone-300",
    pill: "bg-stone-50 text-stone-700 border border-stone-200",
    label: "Soft Plan",
  },
  deadline: {
    badge: "bg-rose-50 text-rose-800 border border-rose-200",
    pill: "bg-rose-50 text-rose-800 border border-rose-200",
    label: "Hard Deadline",
  },
  focus: {
    badge: "bg-emerald-50 text-emerald-800 border border-emerald-200",
    pill: "bg-emerald-50/80 text-emerald-900 border border-emerald-300 shadow-2xs",
    label: "Deep Work / Focus",
  },
  reminder: {
    badge: "bg-amber-50 text-amber-800 border border-amber-200",
    pill: "bg-amber-50 text-amber-900 border border-amber-200",
    label: "Reminder",
  },
};

export default function CalendarPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [events, setEvents] = useState<EventOut[]>([]);
  const [proposals, setProposals] = useState<ProposalOut[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);

  const refresh = useCallback(() => {
    Promise.all([
      api.get<EventOut[]>("/calendar?days=14"),
      api.get<ProposalOut[]>("/proposals?status_filter=pending"),
    ])
      .then(([nextEvents, nextProposals]) => {
        setEvents(nextEvents);
        setProposals(nextProposals);
        setLoadError(false);
      })
      .catch(() => setLoadError(true));
  }, []);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) refresh();
  }, [user, refresh]);

  const days = useMemo(() => groupByDay(events), [events]);

  const focusHours = useMemo(() => {
    return events
      .filter((e) => e.kind === "focus")
      .reduce((acc, e) => {
        const start = new Date(e.starts_at).getTime();
        const end = new Date(e.ends_at).getTime();
        return acc + (end - start) / (1000 * 60 * 60);
      }, 0);
  }, [events]);

  const meetingHours = useMemo(() => {
    return events
      .filter((e) => e.kind === "hard")
      .reduce((acc, e) => {
        const start = new Date(e.starts_at).getTime();
        const end = new Date(e.ends_at).getTime();
        return acc + (end - start) / (1000 * 60 * 60);
      }, 0);
  }, [events]);

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
          ? `Plan applied! ${result.sessions} deep work sessions scheduled onto your calendar.`
          : `${result.proposals} schedule proposals ready for your review below.`
      );
      refresh();
    } catch {
      setMessage("Failed to recompute plan. Please check that calendar events exist.");
    } finally {
      setBusy(false);
    }
  };

  const decide = async (id: string, decision: string) => {
    try {
      await api.post(`/proposals/${id}/decide`, { decision });
      refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not update this proposal.");
    }
  };

  const approveAll = async () => {
    try {
      await api.post("/proposals/approve-batch", {
        proposal_ids: proposals.map((p) => p.id),
      });
      refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not approve the proposals.");
    }
  };

  if (loading || !user) return null;

  return (
    <AppShell>
      <div className="space-y-8 animate-in fade-in duration-200">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-stone-200/60">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200/70">
                Step 4: Plan & Act
              </span>
              <span className="text-xs text-stone-400">·</span>
              <span className="text-xs text-stone-500">Protecting your focus time</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold text-stone-900 tracking-tight">
              Calendar & Focus Engine
            </h1>
            <p className="text-sm text-stone-500 mt-1">
              Your real commitments stay untouched; the AI scheduler proposes optimal focus sessions before upcoming deadlines.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={recompute}
              disabled={busy}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-stone-900 text-white hover:bg-stone-800 disabled:opacity-50 text-xs font-medium shadow-2xs transition-colors"
            >
              <RefreshCwIcon size={14} className={busy ? "animate-spin text-amber-400" : "text-amber-400"} />
              {busy ? "Analyzing availability…" : "Recompute Plan"}
            </button>
          </div>
        </div>

        {message && (
          <div className="p-4 rounded-2xl bg-amber-50/80 border border-amber-200 text-xs text-amber-900 flex items-center gap-2 animate-in fade-in">
            <SparklesIcon size={16} className="text-amber-600 shrink-0" />
            <span>{message}</span>
          </div>
        )}

        {loadError && (
          <div role="alert" className="flex items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700">
            <span>Could not refresh the calendar.</span>
            <button type="button" onClick={refresh} className="font-semibold underline underline-offset-4">Try again</button>
          </div>
        )}

        {/* Focus & Energy Metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-white border border-stone-200 rounded-2xl p-4 shadow-2xs">
            <p className="text-[11px] font-medium uppercase tracking-wider text-stone-400">Planned Focus</p>
            <p className="text-2xl font-bold text-emerald-700 mt-1">{focusHours.toFixed(1)} hrs</p>
            <p className="text-[10px] text-stone-500 mt-0.5">protected deep work blocks</p>
          </div>
          <div className="bg-white border border-stone-200 rounded-2xl p-4 shadow-2xs">
            <p className="text-[11px] font-medium uppercase tracking-wider text-stone-400">Fixed Meetings</p>
            <p className="text-2xl font-bold text-stone-900 mt-1">{meetingHours.toFixed(1)} hrs</p>
            <p className="text-[10px] text-stone-500 mt-0.5">hard calendar commitments</p>
          </div>
          <div className="bg-white border border-stone-200 rounded-2xl p-4 shadow-2xs">
            <p className="text-[11px] font-medium uppercase tracking-wider text-stone-400">Pending Proposals</p>
            <p className="text-2xl font-bold text-amber-600 mt-1">{proposals.length}</p>
            <p className="text-[10px] text-stone-500 mt-0.5">awaiting your approval</p>
          </div>
          <div className="bg-white border border-stone-200 rounded-2xl p-4 shadow-2xs">
            <p className="text-[11px] font-medium uppercase tracking-wider text-stone-400">Next 14 Days</p>
            <p className="text-2xl font-bold text-stone-900 mt-1">{events.length} events</p>
            <p className="text-[10px] text-stone-500 mt-0.5">synced across schedule</p>
          </div>
        </div>

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-3 p-3 bg-white border border-stone-200/80 rounded-2xl text-xs text-stone-600">
          <span className="font-semibold text-stone-800 text-[11px] uppercase tracking-wider">
            Event Types:
          </span>
          {Object.entries(KIND_STYLE).map(([kind, style]) => (
            <span key={kind} className="inline-flex items-center gap-1.5 text-[11px]">
              <span className={`inline-block h-2 w-2 rounded-full ${style.badge}`} />
              {style.label}
            </span>
          ))}
        </div>

        {/* Proposed Changes Drawer (AI Action Proposals) */}
        {proposals.length > 0 && (
          <section className="bg-white border border-amber-200/90 rounded-3xl p-5 sm:p-6 shadow-2xs space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <SparklesIcon size={18} className="text-amber-600" />
                <div>
                  <h2 className="text-sm font-semibold text-stone-900">
                    Proposed Schedule Changes ({proposals.length})
                  </h2>
                  <p className="text-xs text-stone-500">
                    The planner prepared these focus blocks to help you meet your deadlines on time.
                  </p>
                </div>
              </div>
              <button
                onClick={approveAll}
                className="text-xs rounded-xl bg-stone-900 text-white px-4 py-2 font-medium hover:bg-stone-800 shadow-2xs transition-colors"
              >
                Approve All ({proposals.length})
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {proposals.map((proposal) => {
                const payload = proposal.payload as {
                  title?: string;
                  starts_at?: string;
                  ends_at?: string;
                };

                return (
                  <div
                    key={proposal.id}
                    className="border border-stone-200/90 rounded-2xl p-4 bg-stone-50/50 flex flex-col justify-between space-y-3"
                  >
                    <div>
                      <div className="flex items-start justify-between gap-2">
                        <p className="text-sm font-semibold text-stone-900">
                          {payload.title ?? "Focus Session"}
                        </p>
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-800 border border-emerald-200">
                          Proposed Focus
                        </span>
                      </div>

                      {payload.starts_at && (
                        <p className="text-xs font-mono text-stone-500 mt-1 flex items-center gap-1">
                          <ClockIcon size={12} className="text-stone-400" />
                          {new Date(payload.starts_at).toLocaleString([], {
                            weekday: "short",
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                          {" – "}
                          {payload.ends_at ? fmtTime(payload.ends_at) : ""}
                        </p>
                      )}

                      <p className="text-xs text-stone-600 mt-2 pl-2 border-l-2 border-amber-300 leading-relaxed">
                        Reason: {proposal.reason}
                      </p>
                    </div>

                    <div className="flex items-center justify-end gap-2 pt-2 border-t border-stone-200/60">
                      <button
                        onClick={() => decide(proposal.id, "reject")}
                        className="text-xs px-3 py-1.5 rounded-xl border border-stone-200 text-stone-600 hover:bg-stone-100"
                      >
                        Decline
                      </button>
                      <button
                        onClick={() => decide(proposal.id, "approve")}
                        className="text-xs px-4 py-1.5 rounded-xl bg-stone-900 text-white hover:bg-stone-800 flex items-center gap-1 shadow-2xs"
                      >
                        <CheckCircleIcon size={13} />
                        Approve
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Multi-Day Visual Timeline Grid */}
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-stone-900">14-Day Outlook</h2>
            <span className="text-xs text-stone-400">Week-by-week calendar availability</span>
          </div>

          {days.length === 0 ? (
            <div className="bg-white border border-stone-200/80 rounded-3xl p-12 text-center space-y-3">
              <div className="mx-auto w-12 h-12 rounded-2xl bg-emerald-50 text-emerald-600 flex items-center justify-center">
                <CalendarIcon size={24} />
              </div>
              <p className="text-sm font-semibold text-stone-800">Your calendar is clear</p>
              <p className="text-xs text-stone-400 max-w-sm mx-auto">
                No events in the next 14 days. Click &ldquo;Recompute Plan&rdquo; above to automatically schedule focus sessions for your active deadlines.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-3">
              {days.map(([dayKey, dayEvents]) => {
                const isToday =
                  new Date().toLocaleDateString([], {
                    weekday: "short",
                    day: "numeric",
                    month: "short",
                  }) === dayKey;

                return (
                  <div
                    key={dayKey}
                    className={`bg-white border rounded-2xl p-3 min-h-[220px] flex flex-col justify-between transition-all ${
                      isToday
                        ? "border-amber-400 ring-2 ring-amber-100 shadow-2xs"
                        : "border-stone-200/90"
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between pb-2 mb-2 border-b border-stone-100">
                        <span
                          className={`text-xs font-semibold ${
                            isToday ? "text-amber-800" : "text-stone-700"
                          }`}
                        >
                          {dayKey}
                        </span>
                        {isToday && (
                          <span className="text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
                            Today
                          </span>
                        )}
                      </div>

                      <ul className="space-y-1.5">
                        {dayEvents.map((event) => {
                          const style = KIND_STYLE[event.kind] ?? KIND_STYLE.soft;
                          return (
                            <li
                              key={event.id}
                              className={`p-2 rounded-xl text-xs space-y-0.5 transition-transform hover:scale-[1.01] ${style.pill}`}
                            >
                              <div className="flex items-center justify-between text-[10px] font-mono opacity-80">
                                <span>{fmtTime(event.starts_at)}</span>
                                {event.ends_at && <span>{fmtTime(event.ends_at)}</span>}
                              </div>
                              <p className="font-medium truncate leading-tight">{event.title}</p>
                            </li>
                          );
                        })}
                      </ul>
                    </div>

                    <div className="pt-2 text-[10px] text-stone-400 text-right">
                      {dayEvents.length} event{dayEvents.length !== 1 ? "s" : ""}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
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
