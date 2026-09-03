"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, DocumentOut, ReviewOut } from "@/lib/api";
import { useUser } from "@/lib/useUser";

const STATUS_STYLE: Record<string, string> = {
  received: "text-stone-400",
  parsing: "text-blue-500",
  embedding: "text-blue-500",
  extracting: "text-blue-500",
  review: "text-amber-600",
  processed: "text-emerald-600",
  failed: "text-red-500",
};

export default function InboxPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [reviews, setReviews] = useState<ReviewOut[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    api.get<DocumentOut[]>("/documents").then(setDocuments).catch(() => {});
    api.get<ReviewOut[]>("/review").then(setReviews).catch(() => {});
  }, []);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) {
      refresh();
      const timer = setInterval(refresh, 4000); // live processing status
      return () => clearInterval(timer);
    }
  }, [user, refresh]);

  const upload = async (files: FileList | File[]) => {
    setUploadMessage(null);
    try {
      const results = await api.upload(files);
      const duplicates = results.filter((r) => r.duplicate).length;
      setUploadMessage(
        `${results.length - duplicates} uploaded, ${duplicates} duplicates skipped. Processing…`,
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
    refresh();
  };

  if (loading || !user) return null;

  return (
    <AppShell>
      <div className="space-y-8">
        <div>
          <h1 className="text-xl font-semibold text-stone-900">Inbox</h1>
          <p className="text-sm text-stone-500 mt-1">
            Drop anything in. The system files, extracts, and connects it for you.
          </p>
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
          className={`cursor-pointer border-2 border-dashed rounded-2xl p-12 text-center transition-colors ${
            dragging
              ? "border-stone-800 bg-stone-100"
              : "border-stone-300 bg-white hover:border-stone-400"
          }`}
        >
          <p className="text-sm text-stone-600">
            Drag & drop files here, or click to choose
          </p>
          <p className="text-xs text-stone-400 mt-1">
            PDF · DOCX · PPTX · XLSX · CSV · TXT · MD · ZIP · ICS — bulk supported
          </p>
          <input
            ref={fileInput}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => e.target.files && upload(e.target.files)}
          />
        </div>

        {uploadMessage && <p className="text-sm text-stone-500">{uploadMessage}</p>}

        {reviews.length > 0 && (
          <section>
            <h2 className="text-xs font-medium uppercase tracking-wider text-amber-600 mb-3">
              Needs your review ({reviews.length})
            </h2>
            <ul className="space-y-3">
              {reviews.map((review) => (
                <li
                  key={review.id}
                  className="bg-amber-50/60 border border-amber-200 rounded-xl p-4"
                >
                  <p className="text-sm text-amber-900">{review.question}</p>
                  <div className="flex gap-2 mt-3">
                    {review.kind === "deadline" && (
                      <>
                        <ReviewButton onClick={() => resolveReview(review.id, "corrected", promptDate())}>
                          Correct date…
                        </ReviewButton>
                        <ReviewButton onClick={() => resolveReview(review.id, "dismissed")}>
                          Ignore
                        </ReviewButton>
                      </>
                    )}
                    {review.kind !== "deadline" && (
                      <ReviewButton onClick={() => resolveReview(review.id, "dismissed")}>
                        Acknowledge
                      </ReviewButton>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <h2 className="text-xs font-medium uppercase tracking-wider text-stone-400 mb-3">
            Documents ({documents.length})
          </h2>
          {documents.length === 0 ? (
            <p className="text-sm text-stone-400">Nothing here yet.</p>
          ) : (
            <ul className="bg-white border border-stone-200 rounded-2xl divide-y divide-stone-100">
              {documents.map((doc) => (
                <li key={doc.id} className="p-4 flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-stone-800 truncate">
                      {doc.title || doc.original_filename}
                    </p>
                    <p className="text-xs text-stone-400 mt-0.5">
                      {doc.doc_kind.replace(/_/g, " ")}
                      {doc.topic ? ` · ${doc.topic}` : ""} · {doc.chunk_count} chunks
                      {doc.summary ? ` — ${doc.summary.slice(0, 90)}…` : ""}
                    </p>
                  </div>
                  <span
                    className={`text-xs whitespace-nowrap ${
                      STATUS_STYLE[doc.status] ?? "text-stone-400"
                    }`}
                  >
                    {doc.status === "processed" ? "✓ understood" : doc.status}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </AppShell>
  );
}

function ReviewButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="text-xs rounded-full border border-amber-300 bg-white px-3 py-1 text-amber-800 hover:bg-amber-100"
    >
      {children}
    </button>
  );
}

function promptDate(): string | undefined {
  const value = window.prompt("Correct date (YYYY-MM-DDTHH:MM, 24h):");
  return value?.trim() || undefined;
}
