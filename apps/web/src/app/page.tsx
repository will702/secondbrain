"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, Briefing } from "@/lib/api";
import { useUser } from "@/lib/useUser";
import { fmtTime } from "@/lib/useUser";

export default function HomePage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [briefing, setBriefing] = useState<Briefing | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) {
      api.get<Briefing>("/briefing").then(setBriefing).catch(() => setBriefing(null));
    }
  }, [user]);

  if (loading || !user) return null;

  return (
    <AppShell>
      {!briefing ? (
        <p className="text-stone-400 text-sm">Preparing your briefing…</p>
      ) : (
        <div className="space-y-8">
          <section>
            <h1 className="text-2xl font-semibold text-stone-900">
              {briefing.greeting}, {user.display_name.split(" ")[0]}.
            </h1>
            <p className="text-sm text-stone-500 mt-1">
              Here is what deserves your attention today.
            </p>
          </section>

          <div className="grid md:grid-cols-2 gap-6">
            <Card title="Today">
              {briefing.today.length === 0 ? (
                <Empty text="Nothing scheduled today." />
              ) : (
                <ul className="divide-y divide-stone-100">
                  {briefing.today.map((event) => (
                    <li key={event.id} className="py-2 flex items-center justify-between text-sm">
                      <span className="text-stone-700">{event.title}</span>
                      <span className="text-stone-400 tabular-nums">
                        {fmtTime(event.starts_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Top priorities">
              {briefing.top_priorities.length === 0 ? (
                <Empty text="No open tasks. Enjoy the calm." />
              ) : (
                <ol className="divide-y divide-stone-100">
                  {briefing.top_priorities.map((p, i) => (
                    <li key={p.task_id} className="py-2">
                      <Why why={p.why}>
                        <span className="text-sm text-stone-700">
                          {i + 1}. {p.title}
                        </span>
                      </Why>
                    </li>
                  ))}
                </ol>
              )}
            </Card>

            <Card title="Risks">
              {briefing.risks.length === 0 ? (
                <Empty text="No risks detected." />
              ) : (
                <ul className="space-y-2">
                  {briefing.risks.map((risk, i) => (
                    <li
                      key={i}
                      className={`text-sm rounded-lg px-3 py-2 ${
                        risk.severity === "high"
                          ? "bg-amber-50 text-amber-800"
                          : "bg-stone-100 text-stone-600"
                      }`}
                    >
                      ⚠ {risk.message}
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="AI suggestions">
              {briefing.suggestions.length === 0 ? (
                <Empty text="Drop documents into the Inbox to get suggestions." />
              ) : (
                <ul className="space-y-2">
                  {briefing.suggestions.map((s, i) => (
                    <li key={i} className="text-sm">
                      <Why why={s.why}>
                        <span className="text-stone-700">→ {s.action}</span>
                      </Why>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <div className="grid md:grid-cols-2 gap-6">
            <Card title="Readiness">
              {briefing.readiness.length === 0 ? (
                <Empty text="No upcoming assessments." />
              ) : (
                <ul className="space-y-4">
                  {briefing.readiness.map((r) => (
                    <li key={r.deadline_id}>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-stone-700">{r.title}</span>
                        <span className="text-stone-500 tabular-nums">{r.score}%</span>
                      </div>
                      <div className="h-1.5 bg-stone-100 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-stone-800 rounded-full"
                          style={{ width: `${r.score}%` }}
                        />
                      </div>
                      <p className="text-xs text-stone-400 mt-1">
                        {String(r.components.tasks_completed)} tasks done ·{" "}
                        {String(r.components.time_remaining_hours)}h remaining
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Upcoming deadlines">
              <div className="grid grid-cols-3 gap-4 text-center">
                {(["3_days", "7_days", "30_days"] as const).map((key) => (
                  <div key={key} className="py-4 rounded-xl bg-stone-50">
                    <div className="text-2xl font-semibold text-stone-900">
                      {briefing.upcoming[key] ?? 0}
                    </div>
                    <div className="text-xs text-stone-400 mt-1">
                      {key.replace("_", " ")}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      )}
    </AppShell>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-white border border-stone-200 rounded-2xl p-5">
      <h2 className="text-xs font-medium uppercase tracking-wider text-stone-400 mb-3">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm text-stone-400">{text}</p>;
}

function Why({ why, children }: { why: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen(!open)} className="text-left w-full">
        {children}
        <span className="text-xs text-stone-300 ml-1 hover:text-stone-500">why?</span>
      </button>
      {open && (
        <p className="text-xs text-stone-400 mt-1 pl-1 border-l-2 border-stone-200">{why}</p>
      )}
    </div>
  );
}
