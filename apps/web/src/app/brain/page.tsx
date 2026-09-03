"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, DeadlineOut, GraphOut } from "@/lib/api";
import { useUser } from "@/lib/useUser";
import { fmtDateTime } from "@/lib/useUser";

const KIND_ICON: Record<string, string> = {
  person: "👤",
  course: "🎓",
  project: "📁",
  organization: "🏢",
  topic: "🏷️",
  concept: "💡",
  location: "📍",
  goal: "🎯",
};

export default function BrainPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [graph, setGraph] = useState<GraphOut | null>(null);
  const [deadlines, setDeadlines] = useState<DeadlineOut[]>([]);
  const [selectedKind, setSelectedKind] = useState<string>("all");

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) {
      api.get<GraphOut>("/graph").then(setGraph).catch(() => {});
      api.get<DeadlineOut[]>("/deadlines").then(setDeadlines).catch(() => {});
    }
  }, [user]);

  if (loading || !user) return null;

  const kinds = graph
    ? [...new Set(graph.entities.map((e) => e.kind))].sort()
    : [];
  const entities =
    graph && selectedKind === "all"
      ? graph.entities
      : graph?.entities.filter((e) => e.kind === selectedKind) ?? [];

  return (
    <AppShell>
      <div className="space-y-8">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">Brain</h1>
          <p className="text-sm text-stone-500 mt-1">
            Everything the system knows — people, courses, projects, and how they connect.
          </p>
        </div>

        <div className="grid md:grid-cols-2 gap-6">
          <section className="bg-white border border-stone-200 rounded-2xl p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xs font-medium uppercase tracking-wider text-stone-400">
                Knowledge graph
              </h2>
              <select
                value={selectedKind}
                onChange={(e) => setSelectedKind(e.target.value)}
                className="text-xs border border-stone-200 rounded-full px-2 py-1"
              >
                <option value="all">all kinds</option>
                {kinds.map((kind) => (
                  <option key={kind} value={kind}>
                    {kind}
                  </option>
                ))}
              </select>
            </div>
            {!graph || graph.entities.length === 0 ? (
              <p className="text-sm text-stone-400">
                Empty for now — ingest documents in the Inbox to grow the graph.
              </p>
            ) : (
              <div className="space-y-4">
                {graph.projects.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {graph.projects.map((project) => (
                      <span
                        key={project.id}
                        className="text-xs rounded-full bg-stone-900 text-white px-3 py-1"
                      >
                        {project.name} · {project.kind}
                      </span>
                    ))}
                  </div>
                )}
                <ul className="grid grid-cols-2 gap-2">
                  {entities.map((entity) => (
                    <li
                      key={entity.id}
                      className="border border-stone-100 rounded-xl px-3 py-2 text-sm text-stone-700"
                    >
                      {KIND_ICON[entity.kind] ?? "•"} {entity.name}
                    </li>
                  ))}
                </ul>
                {graph.relations.length > 0 && (
                  <div>
                    <h3 className="text-xs text-stone-400 mb-2">Relationships</h3>
                    <ul className="space-y-1 text-xs text-stone-500 font-mono">
                      {graph.relations.slice(0, 12).map((relation) => (
                        <li key={relation.id}>
                          {relation.subject_name} → {relation.predicate} →{" "}
                          {relation.object_name}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="bg-white border border-stone-200 rounded-2xl p-5">
            <h2 className="text-xs font-medium uppercase tracking-wider text-stone-400 mb-4">
              Deadlines
            </h2>
            {deadlines.length === 0 ? (
              <p className="text-sm text-stone-400">No deadlines detected yet.</p>
            ) : (
              <ul className="divide-y divide-stone-100">
                {deadlines.map((deadline) => (
                  <li key={deadline.id} className="py-3">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-sm text-stone-800">{deadline.title}</span>
                      <span
                        className={`text-xs ${
                          deadline.status === "confirmed"
                            ? "text-stone-500"
                            : "text-amber-600"
                        }`}
                      >
                        {deadline.normalized_at
                          ? fmtDateTime(deadline.normalized_at)
                          : "unresolved"}
                      </span>
                    </div>
                    <p className="text-xs text-stone-400 mt-0.5">
                      &ldquo;{deadline.raw_expression}&rdquo; ·{" "}
                      {deadline.explicit ? "explicitly stated" : "inferred"} · confidence{" "}
                      {(deadline.confidence * 100).toFixed(0)}%
                      {deadline.provenance?.page ? ` · page ${deadline.provenance.page}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </AppShell>
  );
}
