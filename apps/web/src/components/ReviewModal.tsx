"use client";

import { useState } from "react";
import { ClockIcon, XIcon, CheckCircleIcon } from "./Icons";

interface ReviewModalProps {
  isOpen: boolean;
  question: string;
  initialDate?: string;
  onClose: () => void;
  onConfirm: (correctedDate: string) => void;
}

function jakartaDateTime(date: Date): string {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Jakarta",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(date)
      .map(({ type, value }) => [type, value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function jakartaPreset(daysFromNow: number, hour: number, minute = 0): string {
  const [date] = jakartaDateTime(new Date()).split("T");
  const [year, month, day] = date.split("-").map(Number);
  const target = new Date(Date.UTC(year, month - 1, day + daysFromNow, hour, minute));
  return `${target.getUTCFullYear()}-${String(target.getUTCMonth() + 1).padStart(2, "0")}-${String(target.getUTCDate()).padStart(2, "0")}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export default function ReviewModal({
  isOpen,
  question,
  initialDate,
  onClose,
  onConfirm,
}: ReviewModalProps) {
  const [dateValue, setDateValue] = useState<string>(() => {
    if (initialDate) return jakartaDateTime(new Date(initialDate));
    return jakartaPreset(1, 9);
  });

  if (!isOpen) return null;

  const setPreset = (daysFromNow: number, hour: number, minute = 0) =>
    setDateValue(jakartaPreset(daysFromNow, hour, minute));

  const getDaysUntilFriday = () => {
    const day = new Date(`${jakartaDateTime(new Date()).split("T")[0]}T00:00:00Z`).getUTCDay();
    const diff = (5 - day + 7) % 7;
    return diff === 0 ? 7 : diff;
  };

  const getDaysUntilNextMonday = () => {
    const day = new Date(`${jakartaDateTime(new Date()).split("T")[0]}T00:00:00Z`).getUTCDay();
    const diff = (1 - day + 7) % 7;
    return diff === 0 ? 7 : diff;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!dateValue) return;
    onConfirm(dateValue);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 backdrop-blur-xs p-4 animate-in fade-in duration-150">
      <div role="dialog" aria-modal="true" aria-labelledby="review-title" className="w-full max-w-md bg-white border border-stone-200 rounded-3xl shadow-xl overflow-hidden p-6 space-y-5">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-amber-50 text-amber-600">
              <ClockIcon size={20} />
            </div>
            <div>
              <h3 id="review-title" className="text-base font-semibold text-stone-900">Clarify deadline</h3>
              <p className="text-xs text-stone-500">Confirm the date and time in Jakarta time</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close deadline review"
            className="p-1 rounded-full text-stone-400 hover:text-stone-700 hover:bg-stone-100 transition-colors"
          >
            <XIcon size={18} />
          </button>
        </div>

        <div className="bg-stone-50 border border-stone-200/80 rounded-2xl p-3.5 text-xs text-stone-700 leading-relaxed">
          <span className="font-medium text-amber-800 uppercase tracking-wide text-[10px] block mb-1">
            Source question
          </span>
          {question}
        </div>

        <div>
          <label className="block text-xs font-medium text-stone-700 mb-2">
            Quick Presets
          </label>
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setPreset(0, 17, 0)}
              className="text-xs px-2.5 py-1 rounded-lg border border-stone-200 bg-white hover:bg-stone-50 text-stone-600"
            >
              Today 5:00 PM
            </button>
            <button
              type="button"
              onClick={() => setPreset(1, 9, 0)}
              className="text-xs px-2.5 py-1 rounded-lg border border-stone-200 bg-white hover:bg-stone-50 text-stone-600"
            >
              Tomorrow 9:00 AM
            </button>
            <button
              type="button"
              onClick={() => setPreset(getDaysUntilFriday(), 17, 0)}
              className="text-xs px-2.5 py-1 rounded-lg border border-stone-200 bg-white hover:bg-stone-50 text-stone-600"
            >
              This Friday 5:00 PM
            </button>
            <button
              type="button"
              onClick={() => setPreset(getDaysUntilNextMonday(), 9, 0)}
              className="text-xs px-2.5 py-1 rounded-lg border border-stone-200 bg-white hover:bg-stone-50 text-stone-600"
            >
              Next Monday 9:00 AM
            </button>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-stone-700 mb-1.5">
              Exact Date & Time
            </label>
            <input
              type="datetime-local"
              required
              value={dateValue}
              onChange={(e) => setDateValue(e.target.value)}
              className="w-full text-sm rounded-xl border border-stone-200 px-3.5 py-2.5 bg-stone-50/50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-stone-900/10 focus:border-stone-400"
            />
          </div>

          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 rounded-xl border border-stone-200 text-xs font-medium text-stone-600 hover:bg-stone-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex-1 py-2 rounded-xl bg-stone-900 text-xs font-medium text-white hover:bg-stone-800 flex items-center justify-center gap-1.5"
            >
              <CheckCircleIcon size={14} />
              Confirm Date
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
