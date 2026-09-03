"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import { api, Briefing } from "@/lib/api";
import { useUser, fmtTime } from "@/lib/useUser";
import {
  SparklesIcon,
  CalendarIcon,
  AlertTriangleIcon,
  CheckCircleIcon,
  ChevronRightIcon,
} from "@/components/Icons";

export default function HomePage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [briefingError, setBriefingError] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) {
      api
        .get<Briefing>("/briefing")
        .then((nextBriefing) => {
          setBriefing(nextBriefing);
          setBriefingError(false);
        })
        .catch(() => setBriefingError(true));
    }
  }, [user]);

  if (loading || !user) return null;

  return (
    <AppShell>
      {!briefing ? (
        <div className="py-20 text-center space-y-3">
          <div className={`inline-block p-3 rounded-2xl ${briefingError ? "bg-rose-50 text-rose-600" : "bg-amber-50 text-amber-600 animate-pulse"}`}>
            <SparklesIcon size={28} />
          </div>
          <p className="text-stone-600 text-sm font-medium">{briefingError ? "Could not load your briefing." : "Assembling your briefing…"}</p>
          {briefingError ? (
            <button type="button" onClick={() => window.location.reload()} className="text-xs font-medium text-stone-700 underline underline-offset-4">Try again</button>
          ) : (
            <p className="text-xs text-stone-400">Reading calendar, tasks, and recent extractions</p>
          )}
        </div>
      ) : (
        <div className="space-y-8 animate-in fade-in duration-200">
          {/* Hero Section */}
          <section className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-stone-200/60">
            <div>
              <h1 className="text-2xl sm:text-3xl font-bold text-stone-900 tracking-tight">
                {briefing.greeting}, {user.display_name.split(" ")[0]}.
              </h1>
              <p className="text-sm text-stone-500 mt-1">
                Your priorities, focus blocks, and risks for today.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <Link
                href="/calendar"
                className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl border border-stone-200 bg-white hover:bg-stone-50 text-xs font-medium text-stone-700 shadow-2xs transition-colors"
              >
                <CalendarIcon size={14} className="text-stone-500" />
                View Schedule
              </Link>
              <Link
                href="/ask"
                className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-stone-900 text-white hover:bg-stone-800 text-xs font-medium shadow-2xs transition-colors"
              >
                <SparklesIcon size={14} className="text-amber-400" />
                Ask your brain
              </Link>
            </div>
          </section>

          {/* Quick Metrics Ribbon */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricCard
              label="Today's Events"
              value={briefing.today.length}
              subtext={briefing.today.filter((e) => e.kind === "focus").length + " focus sessions"}
            />
            <MetricCard
              label="Top Priorities"
              value={briefing.top_priorities.length}
              subtext="ranked by attention engine"
            />
            <MetricCard
              label="Active Risks"
              value={briefing.risks.length}
              subtext={briefing.risks.length === 0 ? "clear sailing" : "needs attention"}
              alert={briefing.risks.length > 0}
            />
            <MetricCard
              label="Upcoming (7 days)"
              value={briefing.upcoming["7_days"] ?? 0}
              subtext="approaching deadlines"
            />
          </div>

          {/* Main 2-Column Dashboard Layout */}
          <div className="grid lg:grid-cols-2 gap-6">
            {/* Left Column: Today's Schedule + Top Priorities */}
            <div className="space-y-6">
              {/* Today's Schedule */}
              <Card
                title="Today's Schedule"
                subtitle="Your calendar commitments & planned focus blocks"
                action={
                  <Link
                    href="/calendar"
                    className="text-xs font-medium text-stone-500 hover:text-stone-900 flex items-center gap-1"
                  >
                    Open Calendar <ChevronRightIcon size={12} />
                  </Link>
                }
              >
                {briefing.today.length === 0 ? (
                  <Empty
                    text="Nothing scheduled today. Your calendar is completely open."
                    actionHref="/calendar"
                    actionLabel="Plan focus blocks"
                  />
                ) : (
                  <ul className="divide-y divide-stone-100">
                    {briefing.today.map((event) => {
                      const isFocus = event.kind === "focus";
                      const isDeadline = event.kind === "deadline";
                      return (
                        <li key={event.id} className="py-2.5 flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2.5 min-w-0">
                            <span
                              className={`h-2.5 w-2.5 rounded-full shrink-0 ${
                                isFocus
                                  ? "bg-emerald-500 ring-4 ring-emerald-50"
                                  : isDeadline
                                  ? "bg-rose-500 ring-4 ring-rose-50"
                                  : "bg-stone-800"
                              }`}
                            />
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-stone-800 truncate">
                                {event.title}
                              </p>
                              <span className="text-[10px] text-stone-400 capitalize">
                                {event.kind.replace("_", " ")}
                              </span>
                            </div>
                          </div>
                          <span className="text-xs font-mono text-stone-500 bg-stone-50 px-2 py-1 rounded-lg shrink-0">
                            {fmtTime(event.starts_at)}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Card>

              {/* Top Priorities */}
              <Card
                title="Top Priorities"
                subtitle="Scored by urgency × importance × opportunity cost"
              >
                {briefing.top_priorities.length === 0 ? (
                  <Empty text="No high urgency tasks open. Enjoy the calm." />
                ) : (
                  <ol className="divide-y divide-stone-100">
                    {briefing.top_priorities.map((p, i) => (
                      <li key={p.task_id} className="py-3 space-y-1.5">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-start gap-2.5">
                            <span className="text-xs font-semibold text-stone-400 w-4 pt-0.5">
                              {i + 1}.
                            </span>
                            <div>
                              <p className="text-sm font-medium text-stone-800">{p.title}</p>
                              <Why why={p.why} />
                            </div>
                          </div>
                          <span className="text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full bg-stone-100 text-stone-600 shrink-0">
                            P{Math.min(3, i + 1)}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ol>
                )}
              </Card>
            </div>

            {/* Right Column: AI Suggestions, Risks & Readiness */}
            <div className="space-y-6">
              {/* Risks & Conflict Radar */}
              <Card
                title="Risks & Conflicts"
                subtitle="Overloaded days, tight turnarounds, or missing prep"
              >
                {briefing.risks.length === 0 ? (
                  <div className="flex items-center gap-3 p-3 rounded-xl bg-emerald-50/60 border border-emerald-200/60 text-emerald-900 text-xs">
                    <CheckCircleIcon size={18} className="text-emerald-600 shrink-0" />
                    <span>No schedule or deadline conflicts detected for the next 7 days.</span>
                  </div>
                ) : (
                  <ul className="space-y-2.5">
                    {briefing.risks.map((risk, i) => (
                      <li
                        key={i}
                        className={`text-xs rounded-xl p-3.5 border flex items-start gap-2.5 ${
                          risk.severity === "high"
                            ? "bg-amber-50/80 border-amber-200 text-amber-900"
                            : "bg-stone-50 border-stone-200 text-stone-700"
                        }`}
                      >
                        <AlertTriangleIcon
                          size={16}
                          className={`shrink-0 mt-0.5 ${
                            risk.severity === "high" ? "text-amber-600" : "text-stone-400"
                          }`}
                        />
                        <div className="min-w-0 flex-1 leading-relaxed">
                          <span className="font-semibold block mb-0.5 capitalize">
                            {risk.severity} Alert
                          </span>
                          {risk.message}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              {/* AI Suggestions */}
              <Card
                title="AI Proactive Suggestions"
                subtitle="Evidence-backed suggestions from your recent inputs"
              >
                {briefing.suggestions.length === 0 ? (
                  <Empty
                    text="Add documents or use Quick capture to generate suggestions."
                    actionHref="/inbox"
                    actionLabel="Open Inbox"
                  />
                ) : (
                  <ul className="space-y-3">
                    {briefing.suggestions.map((s, i) => (
                      <li
                        key={i}
                        className="bg-stone-50/70 border border-stone-200/70 rounded-xl p-3.5 space-y-1.5"
                      >
                        <div className="flex items-start gap-2">
                          <span className="text-amber-600 font-bold">→</span>
                          <p className="text-xs font-medium text-stone-800 leading-relaxed">
                            {s.action}
                          </p>
                        </div>
                        <p className="text-[11px] text-stone-500 pl-4 border-l-2 border-stone-200 ml-1">
                          {s.why}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              {/* Readiness Radar */}
              <Card
                title="Milestone Readiness"
                subtitle="Preparation scores based on completed work vs remaining time"
              >
                {briefing.readiness.length === 0 ? (
                  <Empty text="No upcoming major assessments or milestones." />
                ) : (
                  <ul className="space-y-4">
                    {briefing.readiness.map((r) => (
                      <li key={r.deadline_id} className="space-y-1.5">
                        <div className="flex justify-between items-baseline text-xs">
                          <span className="font-medium text-stone-800">{r.title}</span>
                          <span className="font-mono font-semibold text-stone-600">{r.score}%</span>
                        </div>
                        <div className="h-2 bg-stone-100 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${
                              r.score >= 70
                                ? "bg-emerald-500"
                                : r.score >= 40
                                ? "bg-amber-500"
                                : "bg-rose-500"
                            }`}
                            style={{ width: `${Math.max(5, r.score)}%` }}
                          />
                        </div>
                        <p className="text-[10px] text-stone-400">
                          {String(r.components.tasks_completed ?? 0)} tasks finished ·{" "}
                          {String(r.components.time_remaining_hours ?? 0)}h remaining
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}

function MetricCard({
  label,
  value,
  subtext,
  alert = false,
}: {
  label: string;
  value: number;
  subtext: string;
  alert?: boolean;
}) {
  return (
    <div
      className={`bg-white border rounded-2xl p-4 shadow-2xs ${
        alert ? "border-amber-200 bg-amber-50/30" : "border-stone-200"
      }`}
    >
      <p className="text-[11px] font-medium uppercase tracking-wider text-stone-400">{label}</p>
      <p className="text-2xl font-bold text-stone-900 mt-1">{value}</p>
      <p className="text-[10px] text-stone-500 mt-0.5 truncate">{subtext}</p>
    </div>
  );
}

function Card({
  title,
  subtitle,
  children,
  action,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <section className="bg-white border border-stone-200/90 rounded-3xl p-5 sm:p-6 shadow-2xs">
      <div className="flex items-start justify-between gap-2 mb-4">
        <div>
          <h2 className="text-sm font-semibold text-stone-900">{title}</h2>
          {subtitle && <p className="text-xs text-stone-400 mt-0.5">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function Empty({
  text,
  actionHref,
  actionLabel,
}: {
  text: string;
  actionHref?: string;
  actionLabel?: string;
}) {
  return (
    <div className="py-6 text-center space-y-2">
      <p className="text-xs text-stone-400">{text}</p>
      {actionHref && actionLabel && (
        <Link
          href={actionHref}
          className="inline-flex items-center gap-1 text-xs font-medium text-stone-700 hover:text-stone-900 underline underline-offset-4"
        >
          {actionLabel} <ChevronRightIcon size={10} />
        </Link>
      )}
    </div>
  );
}

function Why({ why }: { why: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1">
      <button
        onClick={() => setOpen(!open)}
        className="text-[11px] text-stone-400 hover:text-stone-700 flex items-center gap-1 transition-colors"
      >
        <span>{open ? "Hide reasoning" : "Why is this prioritized?"}</span>
        <span className="text-[10px]">▼</span>
      </button>
      {open && (
        <p className="text-xs text-stone-600 mt-1 pl-2 border-l-2 border-amber-300 bg-amber-50/40 p-1.5 rounded-r-lg leading-relaxed">
          {why}
        </p>
      )}
    </div>
  );
}
