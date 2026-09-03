"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AppShell from "@/components/AppShell";
import { api, DeadlineOut, GraphOut } from "@/lib/api";
import { useUser, fmtDateTime } from "@/lib/useUser";
import {
  BrainIcon,
  SearchIcon,
  SparklesIcon,
  PaletteIcon,
  UserIcon,
  BriefcaseIcon,
  BookOpenIcon,
  LayersIcon,
  LayoutGridIcon,
  NetworkIcon,
  ClockIcon,
  PlusIcon,
} from "@/components/Icons";

const KIND_META: Record<
  string,
  { label: string; icon: React.ComponentType<{ size?: number; className?: string }>; color: string; bg: string }
> = {
  project: { label: "Projects", icon: BriefcaseIcon, color: "text-amber-700", bg: "bg-amber-50 border-amber-200" },
  person: { label: "People", icon: UserIcon, color: "text-stone-700", bg: "bg-stone-50 border-stone-200" },
  course: { label: "Courses & Programs", icon: BookOpenIcon, color: "text-stone-700", bg: "bg-stone-50 border-stone-200" },
  concept: { label: "Concepts", icon: PaletteIcon, color: "text-stone-700", bg: "bg-stone-50 border-stone-200" },
  topic: { label: "Topics & Tags", icon: LayersIcon, color: "text-stone-700", bg: "bg-stone-50 border-stone-200" },
  organization: { label: "Organizations & Clients", icon: BriefcaseIcon, color: "text-stone-700", bg: "bg-stone-50 border-stone-200" },
  goal: { label: "Milestones & Goals", icon: SparklesIcon, color: "text-stone-700", bg: "bg-stone-50 border-stone-200" },
  location: { label: "Locations", icon: BrainIcon, color: "text-stone-700", bg: "bg-stone-50 border-stone-200" },
};

export default function BrainPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [graph, setGraph] = useState<GraphOut | null>(null);
  const [deadlines, setDeadlines] = useState<DeadlineOut[]>([]);
  const [loadError, setLoadError] = useState(false);
  const [selectedKind, setSelectedKind] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [viewMode, setViewMode] = useState<"cards" | "explorer">("cards");
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) {
      Promise.all([api.get<GraphOut>("/graph"), api.get<DeadlineOut[]>("/deadlines")])
        .then(([nextGraph, nextDeadlines]) => {
          setGraph(nextGraph);
          setDeadlines(nextDeadlines);
        })
        .catch(() => setLoadError(true));
    }
  }, [user]);

  if (loading || !user) return null;

  const kinds = graph ? [...new Set(graph.entities.map((e) => e.kind))].sort() : [];

  const filteredEntities = (graph?.entities ?? []).filter((entity) => {
    const matchesKind = selectedKind === "all" || entity.kind === selectedKind;
    const matchesSearch =
      entity.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      entity.aliases?.some((a) => a.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchesKind && matchesSearch;
  });

  // Selected entity's relations for explorer view
  const selectedEntity = graph?.entities.find((e) => e.id === selectedEntityId);
  const entityRelations =
    graph?.relations.filter((r) => {
      if (!selectedEntity) return false;
      return (
        r.subject_id === selectedEntityId ||
        r.object_id === selectedEntityId ||
        r.subject_name === selectedEntity.name ||
        r.object_name === selectedEntity.name
      );
    }) ?? [];

  return (
    <AppShell>
      <div className="space-y-8 animate-in fade-in duration-200">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-stone-200/60">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold text-stone-900 tracking-tight">
              Brain
            </h1>
            <p className="text-sm text-stone-500 mt-1">
              Your projects, people, topics, and deadlines — connected to their sources.
            </p>
          </div>

          {/* View Mode Switcher */}
          <div className="flex items-center p-1 rounded-2xl bg-stone-100 border border-stone-200/80 self-start sm:self-center">
            <button
              onClick={() => setViewMode("cards")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
                viewMode === "cards"
                  ? "bg-white text-stone-900 shadow-2xs"
                  : "text-stone-600 hover:text-stone-900"
              }`}
            >
              <LayoutGridIcon size={14} />
              Visual Cards
            </button>
            <button
              onClick={() => setViewMode("explorer")}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-all ${
                viewMode === "explorer"
                  ? "bg-white text-stone-900 shadow-2xs"
                  : "text-stone-600 hover:text-stone-900"
              }`}
            >
              <NetworkIcon size={14} />
              Relationship Explorer
            </button>
          </div>
        </div>

        {loadError && (
          <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700">
            Could not load the knowledge graph. Refresh the page to try again.
          </div>
        )}

        {/* Search & Kind Filters */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2 overflow-x-auto pb-1 sm:pb-0">
            <button
              onClick={() => setSelectedKind("all")}
              className={`text-xs px-3 py-1.5 rounded-full font-medium whitespace-nowrap transition-colors ${
                selectedKind === "all"
                  ? "bg-stone-900 text-white shadow-2xs"
                  : "bg-white border border-stone-200 text-stone-600 hover:bg-stone-50"
              }`}
            >
              All Entities ({graph?.entities.length ?? 0})
            </button>
            {kinds.map((kind) => {
              const meta = KIND_META[kind] ?? {
                label: kind,
                color: "text-stone-700",
                bg: "bg-stone-50",
              };
              const count = graph?.entities.filter((e) => e.kind === kind).length ?? 0;
              return (
                <button
                  key={kind}
                  onClick={() => setSelectedKind(kind)}
                  className={`text-xs px-3 py-1.5 rounded-full font-medium whitespace-nowrap transition-colors ${
                    selectedKind === kind
                      ? "bg-stone-900 text-white shadow-2xs"
                      : "bg-white border border-stone-200 text-stone-600 hover:bg-stone-50"
                  }`}
                >
                  {meta.label} ({count})
                </button>
              );
            })}
          </div>

          <div className="relative shrink-0">
            <SearchIcon size={14} className="absolute left-3 top-2.5 text-stone-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search people, projects, concepts…"
              className="text-xs rounded-xl border border-stone-200 pl-8 pr-3 py-1.5 bg-white w-full sm:w-64 focus:outline-none focus:ring-2 focus:ring-stone-900/10"
            />
          </div>
        </div>

        {/* Content View: Cards vs Explorer */}
        {viewMode === "cards" ? (
          <div className="grid lg:grid-cols-3 gap-6">
            {/* Left 2 Cols: Entities Grid */}
            <div className="lg:col-span-2 space-y-4">
              {!graph || filteredEntities.length === 0 ? (
                <div className="bg-white border border-stone-200/90 rounded-3xl p-10 text-center space-y-3">
                  <div className="mx-auto w-12 h-12 rounded-2xl bg-amber-50 text-amber-700 flex items-center justify-center">
                    <BrainIcon size={24} />
                  </div>
                  <p className="text-sm font-semibold text-stone-800">Your Knowledge Brain is ready</p>
                  <p className="text-xs text-stone-500 max-w-sm mx-auto">
                    As you drop documents or write quick notes, people, projects, and creative concepts are automatically connected here.
                  </p>
                  <div className="pt-2">
                    <Link
                      href="/inbox"
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-stone-900 text-white text-xs font-medium hover:bg-stone-800"
                    >
                      <PlusIcon size={14} />
                      Drop First Document or Note
                    </Link>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {filteredEntities.map((entity) => {
                    const meta = KIND_META[entity.kind] ?? {
                      label: entity.kind,
                      icon: BrainIcon,
                      color: "text-stone-700",
                      bg: "bg-stone-50 border-stone-200",
                    };
                    const Icon = meta.icon;

                    return (
                      <div
                        key={entity.id}
                        onClick={() => {
                          setSelectedEntityId(entity.id);
                          setViewMode("explorer");
                        }}
                        className="bg-white border border-stone-200/90 rounded-2xl p-4 hover:shadow-xs hover:border-amber-300 transition-all cursor-pointer group flex flex-col justify-between"
                      >
                        <div>
                          <div className="flex items-center justify-between mb-2">
                            <span
                              className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md border ${meta.bg} ${meta.color}`}
                            >
                              {meta.label}
                            </span>
                            <div className="p-1 rounded-lg bg-stone-50 text-stone-400 group-hover:text-stone-700">
                              <Icon size={14} />
                            </div>
                          </div>

                          <h3 className="text-sm font-semibold text-stone-900 group-hover:text-amber-700 transition-colors">
                            {entity.name}
                          </h3>

                          {entity.aliases && entity.aliases.length > 0 && (
                            <p className="text-[11px] text-stone-400 mt-1 truncate">
                              aka: {entity.aliases.join(", ")}
                            </p>
                          )}
                        </div>

                        <div className="mt-3 pt-2 border-t border-stone-100 flex items-center justify-between text-[10px] text-stone-400">
                          <span>Confidence: {(entity.confidence * 100).toFixed(0)}%</span>
                          <span className="text-amber-600 font-medium group-hover:underline">
                            View connections →
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Right Col: Verified Deadlines & Milestones */}
            <div className="space-y-4">
              <div className="bg-white border border-stone-200/90 rounded-3xl p-5 shadow-2xs space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ClockIcon size={16} className="text-stone-700" />
                    <h2 className="text-sm font-semibold text-stone-900">
                      Verified Deadlines ({deadlines.length})
                    </h2>
                  </div>
                  <span className="text-[10px] text-stone-400">Provenance-backed</span>
                </div>

                {deadlines.length === 0 ? (
                  <p className="text-xs text-stone-400 py-4 text-center">
                    No deadlines extracted yet.
                  </p>
                ) : (
                  <ul className="divide-y divide-stone-100 max-h-[600px] overflow-y-auto pr-1">
                    {deadlines.map((deadline) => (
                      <li key={deadline.id} className="py-3 space-y-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <span className="text-xs font-semibold text-stone-800">
                            {deadline.title}
                          </span>
                          <span
                            className={`text-[10px] font-mono px-2 py-0.5 rounded-md ${
                              deadline.status === "confirmed"
                                ? "bg-stone-100 text-stone-700"
                                : "bg-amber-50 text-amber-800"
                            }`}
                          >
                            {deadline.normalized_at
                              ? fmtDateTime(deadline.normalized_at)
                              : "Unresolved"}
                          </span>
                        </div>

                        <p className="text-[11px] text-stone-500 italic">
                          &ldquo;{deadline.raw_expression}&rdquo;
                        </p>

                        <div className="flex items-center gap-2 text-[10px] text-stone-400">
                          <span>{deadline.explicit ? "Explicitly stated" : "Inferred by AI"}</span>
                          <span>·</span>
                          <span>{(deadline.confidence * 100).toFixed(0)}% confidence</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </div>
        ) : (
          /* Explorer View */
          <div className="bg-white border border-stone-200/90 rounded-3xl p-6 shadow-2xs space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-stone-100">
              <div>
                <h2 className="text-sm font-semibold text-stone-900">
                  Interactive Relationship Explorer
                </h2>
                <p className="text-xs text-stone-500">
                  Select an entity to reveal who and what it connects to across your digital life
                </p>
              </div>

              {/* Entity Picker Dropdown */}
              <select
                value={selectedEntityId ?? ""}
                onChange={(e) => setSelectedEntityId(e.target.value || null)}
                className="text-xs rounded-xl border border-stone-200 px-3 py-2 bg-stone-50 text-stone-800 focus:outline-none"
              >
                <option value="">-- Choose an entity to inspect --</option>
                {(graph?.entities ?? []).map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name} ({e.kind})
                  </option>
                ))}
              </select>
            </div>

            {selectedEntity ? (
              <div className="space-y-6">
                {/* Active Entity Card */}
                <div className="bg-amber-50/60 border border-amber-200/80 rounded-2xl p-5 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="p-3 rounded-xl bg-white shadow-2xs text-amber-700">
                      <BrainIcon size={24} />
                    </div>
                    <div>
                      <span className="text-[10px] font-bold uppercase tracking-wider text-stone-400">
                        Inspecting Entity ({selectedEntity.kind})
                      </span>
                      <h3 className="text-lg font-bold text-stone-900">{selectedEntity.name}</h3>
                      {selectedEntity.aliases && selectedEntity.aliases.length > 0 && (
                        <p className="text-xs text-stone-500 mt-0.5">
                          Also known as: {selectedEntity.aliases.join(", ")}
                        </p>
                      )}
                    </div>
                  </div>

                  <span className="text-xs font-semibold px-3 py-1 rounded-full bg-white text-stone-700 shadow-2xs border border-stone-200/60">
                    {entityRelations.length} connection{entityRelations.length !== 1 ? "s" : ""}
                  </span>
                </div>

                {/* Connections List */}
                <div className="space-y-3">
                  <h4 className="text-xs font-semibold uppercase tracking-wider text-stone-400">
                    Natural Language Relationships
                  </h4>

                  {entityRelations.length === 0 ? (
                    <p className="text-xs text-stone-400 italic py-3">
                      No direct relationships recorded yet for this entity. Ingest more documents to enrich connections.
                    </p>
                  ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {entityRelations.map((r) => {
                        const isSubject = r.subject_id
                          ? r.subject_id === selectedEntityId
                          : r.subject_name === selectedEntity?.name;
                        const relatedName = isSubject ? r.object_name : r.subject_name;
                        const predicateClean = r.predicate.replace(/_/g, " ");

                        return (
                          <div
                            key={r.id}
                            className="p-4 rounded-2xl border border-stone-200/80 bg-stone-50/50 space-y-2 hover:bg-white hover:shadow-2xs transition-all"
                          >
                            <div className="flex items-center gap-2 text-xs font-medium text-stone-800">
                              <span className="text-amber-600 font-bold">●</span>
                              <span>
                                {isSubject ? (
                                  <>
                                    <strong className="text-stone-900">{selectedEntity.name}</strong>{" "}
                                    <span className="text-stone-500 font-normal">{predicateClean}</span>{" "}
                                    <strong className="text-amber-800">{relatedName}</strong>
                                  </>
                                ) : (
                                  <>
                                    <strong className="text-amber-800">{relatedName}</strong>{" "}
                                    <span className="text-stone-500 font-normal">{predicateClean}</span>{" "}
                                    <strong className="text-stone-900">{selectedEntity.name}</strong>
                                  </>
                                )}
                              </span>
                            </div>

                            <div className="flex items-center justify-between text-[10px] text-stone-400 pt-1 border-t border-stone-200/60">
                              <span>Confidence: {(r.confidence * 100).toFixed(0)}%</span>
                              <span className="capitalize">{isSubject ? "Outgoing" : "Incoming"}</span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="py-12 text-center space-y-2">
                <p className="text-xs text-stone-500 font-medium">
                  Select an entity from the dropdown above or click any card in Visual Cards view.
                </p>
                <p className="text-[11px] text-stone-400">
                  Second Brain maps multi-hop relationships between people, projects, assignments, and concepts.
                </p>
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
