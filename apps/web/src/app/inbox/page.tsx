"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, DocumentOut, ReviewOut } from "@/lib/api";
import { useUser } from "@/lib/useUser";
import ReviewModal from "@/components/ReviewModal";
import {
  InboxIcon,
  SparklesIcon,
  SearchIcon,
  AlertTriangleIcon,
  Trash2Icon,
} from "@/components/Icons";

const STATUS_BADGE: Record<string, { label: string; class: string }> = {
  received: { label: "In Queue", class: "bg-stone-100 text-stone-600" },
  parsing: { label: "Reading content…", class: "bg-stone-100 text-stone-700 animate-pulse" },
  embedding: { label: "Connecting concepts…", class: "bg-stone-100 text-stone-700 animate-pulse" },
  extracting: { label: "Extracting facts…", class: "bg-stone-100 text-stone-700 animate-pulse" },
  review: { label: "Needs Date Review", class: "bg-amber-100 text-amber-800 font-semibold" },
  processed: { label: "✓ Connected", class: "bg-emerald-50 text-emerald-800" },
  failed: { label: "Could not read", class: "bg-rose-50 text-rose-700" },
};

export default function InboxPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [reviews, setReviews] = useState<ReviewOut[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedKind, setSelectedKind] = useState("all");

  // Review Modal state
  const [activeReviewItem, setActiveReviewItem] = useState<ReviewOut | null>(null);

  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    Promise.all([
      api.get<DocumentOut[]>("/documents"),
      api.get<ReviewOut[]>("/review"),
    ])
      .then(([nextDocuments, nextReviews]) => {
        setDocuments(nextDocuments);
        setReviews(nextReviews);
        setLoadError(false);
      })
      .catch(() => setLoadError(true));
  }, []);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) {
      refresh();
      const timer = setInterval(refresh, 4000);
      return () => clearInterval(timer);
    }
  }, [user, refresh]);

  const upload = async (files: FileList | File[]) => {
    setUploadMessage(null);
    try {
      const results = await api.upload(files);
      const duplicates = results.filter((r) => r.duplicate).length;
      setUploadMessage(
        `${results.length - duplicates} item(s) uploaded successfully${
          duplicates ? ` (${duplicates} duplicates skipped)` : ""
        }. Second Brain is reading and extracting facts…`
      );
      refresh();
    } catch (err) {
      setUploadMessage(err instanceof Error ? err.message : "Upload failed");
    }
  };

  const resolveReview = async (id: string, decision: string, correctedDate?: string) => {
    await api.post(`/review/${id}/resolve`, {
      decision,
      corrected_date: correctedDate,
    });
    setActiveReviewItem(null);
    refresh();
  };

  const handleDeleteDocument = async (docId: string, filename: string) => {
    if (!window.confirm(`Are you sure you want to remove "${filename}" from your brain?`)) {
      return;
    }
    try {
      await api.delete(`/documents/${docId}`);
      setUploadMessage(`Removed "${filename}".`);
      refresh();
    } catch (err) {
      setUploadMessage(err instanceof Error ? err.message : "Failed to remove document");
    }
  };

  if (loading || !user) return null;

  const filteredDocuments = documents.filter((doc) => {
    const matchesSearch =
      (doc.title || doc.original_filename || "")
        .toLowerCase()
        .includes(searchQuery.toLowerCase()) ||
      (doc.summary || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
      (doc.topic || "").toLowerCase().includes(searchQuery.toLowerCase());

    const matchesKind =
      selectedKind === "all" ||
      doc.doc_kind.toLowerCase().includes(selectedKind.toLowerCase());

    return matchesSearch && matchesKind;
  });

  const kinds = ["all", ...new Set(documents.map((d) => d.doc_kind))];

  return (
    <AppShell>
      <div className="space-y-8 animate-in fade-in duration-200">
        {/* Header */}
        <div className="border-b border-stone-200/60 pb-2">
          <div>
            <h1 className="text-2xl sm:text-3xl font-bold text-stone-900 tracking-tight">
              Inbox
            </h1>
            <p className="text-sm text-stone-500 mt-1">
              Add files here. Use Quick capture in the header for notes.
            </p>
          </div>
        </div>

        <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              if (e.dataTransfer.files.length) upload(e.dataTransfer.files);
            }}
            onClick={() => fileInput.current?.click()}
            className={`cursor-pointer border-2 border-dashed rounded-3xl p-10 sm:p-12 text-center transition-all ${
              dragging
                ? "border-amber-500 bg-amber-50/40 scale-[0.99]"
                : "border-stone-300 bg-white hover:border-stone-400 hover:shadow-xs"
            }`}
          >
            <div className="mx-auto w-12 h-12 rounded-2xl bg-stone-50 border border-stone-200 flex items-center justify-center text-stone-600 mb-3 shadow-2xs">
              <InboxIcon size={24} className="text-stone-700" />
            </div>
            <p className="text-sm font-semibold text-stone-800">
              Drag & drop files here, or click to browse
            </p>
            <p className="text-xs text-stone-400 mt-1.5 max-w-md mx-auto">
              PDF · DOCX · PPTX · XLSX · CSV · TXT · Markdown · ZIP · ICS
            </p>

            <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
              <span className="text-[11px] px-2.5 py-1 rounded-full bg-stone-100 text-stone-600 font-medium">
                Bulk upload supported
              </span>
              <span className="text-[11px] px-2.5 py-1 rounded-full bg-stone-100 text-stone-600 font-medium">
                Local-first privacy
              </span>
              <span className="text-[11px] px-2.5 py-1 rounded-full bg-stone-100 text-stone-600 font-medium">
                Auto-extracted provenance
              </span>
            </div>

            <input
              ref={fileInput}
              type="file"
              multiple
              className="hidden"
              onChange={(e) => e.target.files && upload(e.target.files)}
            />
          </div>

        {loadError && (
          <div role="alert" className="flex items-center justify-between gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-xs text-rose-700">
            <span>Could not refresh your documents.</span>
            <button type="button" onClick={refresh} className="font-semibold underline underline-offset-4">Try again</button>
          </div>
        )}

        {/* Upload Status Alert */}
        {uploadMessage && (
          <div className="p-4 rounded-2xl bg-amber-50/80 border border-amber-200 text-xs text-amber-900 flex items-center gap-2 animate-in fade-in">
            <SparklesIcon size={16} className="text-amber-600 shrink-0" />
            <span>{uploadMessage}</span>
          </div>
        )}

        {/* Review Queue (Needs User Decision) */}
        {reviews.length > 0 && (
          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <AlertTriangleIcon size={16} className="text-amber-600" />
                <h2 className="text-xs font-semibold uppercase tracking-wider text-amber-700">
                  Needs Your Clarification ({reviews.length})
                </h2>
              </div>
              <p className="text-xs text-stone-400">
                Ambiguous dates are reviewed by you, never assumed
              </p>
            </div>

            <ul className="space-y-3">
              {reviews.map((review) => (
                <li
                  key={review.id}
                  className="bg-amber-50/60 border border-amber-200/90 rounded-2xl p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-2xs"
                >
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-amber-950">{review.question}</p>
                    <p className="text-xs text-amber-800/80">
                      The AI detected an ambiguous date expression and wants to ensure your calendar is accurate.
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {review.kind === "deadline" && (
                      <>
                        <button
                          onClick={() => setActiveReviewItem(review)}
                          className="text-xs rounded-xl bg-amber-700 text-white px-3.5 py-1.5 font-medium hover:bg-amber-800 shadow-2xs transition-colors"
                        >
                          Correct date…
                        </button>
                        <button
                          onClick={() => resolveReview(review.id, "dismissed")}
                          className="text-xs rounded-xl border border-amber-300 bg-white px-3 py-1.5 text-amber-800 hover:bg-amber-100 transition-colors"
                        >
                          Ignore
                        </button>
                      </>
                    )}
                    {review.kind !== "deadline" && (
                      <button
                        onClick={() => resolveReview(review.id, "dismissed")}
                        className="text-xs rounded-xl bg-amber-700 text-white px-3.5 py-1.5 font-medium hover:bg-amber-800 shadow-2xs"
                      >
                        Acknowledge
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Documents Knowledge Base */}
        <section className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-stone-900">
                Ingested Materials ({documents.length})
              </h2>
              <p className="text-xs text-stone-500 mt-0.5">
                Processed, segmented, and linked into your knowledge graph
              </p>
            </div>

            {/* Filter and Search */}
            <div className="flex items-center gap-2">
              <div className="relative">
                <SearchIcon size={14} className="absolute left-3 top-2.5 text-stone-400" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search documents…"
                  className="text-xs rounded-xl border border-stone-200 pl-8 pr-3 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-stone-900/10"
                />
              </div>
              {kinds.length > 2 && (
                <select
                  value={selectedKind}
                  onChange={(e) => setSelectedKind(e.target.value)}
                  className="text-xs rounded-xl border border-stone-200 px-2.5 py-1.5 bg-white text-stone-600 focus:outline-none"
                >
                  {kinds.map((k) => (
                    <option key={k} value={k}>
                      {k === "all" ? "All types" : k.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>

          {filteredDocuments.length === 0 ? (
            <div className="bg-white border border-stone-200/80 rounded-3xl p-10 text-center space-y-2">
              <p className="text-sm text-stone-500 font-medium">No documents match your query.</p>
              <p className="text-xs text-stone-400">
                Drop your design briefs, lecture notes, or project plans above to populate your brain.
              </p>
            </div>
          ) : (
            <div className="bg-white border border-stone-200/90 rounded-3xl divide-y divide-stone-100 shadow-2xs overflow-hidden">
              {filteredDocuments.map((doc) => {
                const statusInfo = STATUS_BADGE[doc.status] ?? {
                  label: doc.status,
                  class: "bg-stone-100 text-stone-500",
                };

                return (
                  <div key={doc.id} className="p-4 sm:p-5 flex items-start justify-between gap-4 hover:bg-stone-50/50 transition-colors">
                    <div className="min-w-0 space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-semibold text-stone-800 truncate">
                          {doc.title || doc.original_filename}
                        </p>
                        <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-stone-100 text-stone-600">
                          {doc.doc_kind.replace(/_/g, " ")}
                        </span>
                        {doc.topic && (
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-200/60">
                            {doc.topic}
                          </span>
                        )}
                      </div>

                      {doc.summary ? (
                        <p className="text-xs text-stone-500 line-clamp-2 leading-relaxed">
                          {doc.summary}
                        </p>
                      ) : (
                        <p className="text-xs text-stone-400 italic">
                          Summary will be generated once fully understood.
                        </p>
                      )}

                      <div className="flex items-center gap-3 text-[11px] text-stone-400 pt-1">
                        <span>{doc.chunk_count} verified segments</span>
                        <span>·</span>
                        <span>{new Date(doc.created_at).toLocaleDateString([], { month: "short", day: "numeric" })}</span>
                        {doc.importance != null && (
                          <>
                            <span>·</span>
                            <span>Importance: {(doc.importance * 100).toFixed(0)}%</span>
                          </>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <span
                        className={`text-xs px-2.5 py-1 rounded-full font-medium ${statusInfo.class}`}
                      >
                        {statusInfo.label}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleDeleteDocument(doc.id, doc.title || doc.original_filename)}
                        className="p-1.5 rounded-xl text-stone-400 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                        title="Remove file"
                        aria-label={`Remove ${doc.title || doc.original_filename}`}
                      >
                        <Trash2Icon size={14} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {/* Review Modal for Date Clarification */}
      {activeReviewItem && (
        <ReviewModal
          isOpen={true}
          question={activeReviewItem.question}
          onClose={() => setActiveReviewItem(null)}
          onConfirm={(date) => resolveReview(activeReviewItem.id, "corrected", date)}
        />
      )}
    </AppShell>
  );
}
