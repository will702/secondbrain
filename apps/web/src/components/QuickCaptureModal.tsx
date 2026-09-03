"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { CheckCircleIcon, SparklesIcon, XIcon } from "./Icons";

interface QuickCaptureModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export default function QuickCaptureModal({ isOpen, onClose, onSuccess }: QuickCaptureModalProps) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  if (!isOpen) return null;

  const close = () => {
    if (!busy) onClose();
  };

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!content.trim()) return;
    setBusy(true);
    setMessage(null);
    try {
      const safeTitle = (title.trim() || "quick-note").toLowerCase().replace(/[^a-z0-9_-]/g, "-");
      const file = new File([content], `${safeTitle}-${Date.now().toString().slice(-4)}.md`, { type: "text/markdown" });
      await api.upload([file]);
      setTitle("");
      setContent("");
      onClose();
      onSuccess?.();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save this note.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/45 p-4 backdrop-blur-xs" onMouseDown={(event) => event.target === event.currentTarget && close()}>
      <div role="dialog" aria-modal="true" aria-labelledby="quick-capture-title" className="flex max-h-[90dvh] w-full max-w-xl flex-col gap-5 overflow-auto rounded-3xl border border-stone-200 bg-white p-5 shadow-2xl sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <span className="rounded-xl bg-amber-50 p-2 text-amber-700"><SparklesIcon size={20} /></span>
            <div>
              <h2 id="quick-capture-title" className="text-base font-semibold text-stone-900">Quick capture</h2>
              <p className="text-xs text-stone-500">Add a note; dates, people, projects, and commitments will be extracted.</p>
            </div>
          </div>
          <button type="button" onClick={close} aria-label="Close quick capture" className="rounded-full p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700"><XIcon size={18} /></button>
        </div>
        <form onSubmit={save} className="space-y-3">
          <label className="block text-xs font-medium text-stone-700">
            Title <span className="font-normal text-stone-400">(optional)</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Meeting notes" className="mt-1.5 w-full rounded-xl border border-stone-200 px-3.5 py-2.5 text-sm" />
          </label>
          <label className="block text-xs font-medium text-stone-700">
            Note
            <textarea required value={content} onChange={(event) => setContent(event.target.value)} placeholder="Write a thought, decision, or commitment…" rows={9} className="mt-1.5 w-full resize-y rounded-xl border border-stone-200 bg-stone-50/40 p-3.5 text-sm leading-relaxed" />
          </label>
          {message && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">{message}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={close} className="rounded-xl border border-stone-200 px-4 py-2 text-xs font-medium text-stone-600 hover:bg-stone-50">Cancel</button>
            <button type="submit" disabled={busy || !content.trim()} className="flex items-center gap-1.5 rounded-xl bg-stone-900 px-5 py-2 text-xs font-medium text-white hover:bg-stone-800 disabled:opacity-50"><CheckCircleIcon size={14} />{busy ? "Saving…" : "Save note"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}
