"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, AskAnswer } from "@/lib/api";
import { useUser } from "@/lib/useUser";
import {
  SearchIcon,
  SparklesIcon,
  BookOpenIcon,
  SendIcon,
} from "@/components/Icons";

export default function AskPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [recentQuestions, setRecentQuestions] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
    if (user) inputRef.current?.focus();
  }, [loading, user, router]);

  const ask = async (q: string) => {
    if (!q.trim()) return;
    setBusy(true);
    setAnswer(null);

    // Add to recent questions
    setRecentQuestions((prev) => [q, ...prev.filter((item) => item !== q)].slice(0, 5));

    try {
      const res = await api.post<AskAnswer>("/ask", { question: q });
      setAnswer(res);
    } catch {
      setAnswer({
        answer: "Something went wrong contacting the Second Brain API. Please verify the backend is running.",
        path: "error",
        citations: [],
        facts: {},
      });
    } finally {
      setBusy(false);
    }
  };

  if (loading || !user) return null;

  return (
    <AppShell>
      <div className="max-w-3xl mx-auto space-y-8 animate-in fade-in duration-200">
        {/* Header */}
        <div className="text-center space-y-2 pt-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-50 text-amber-800 border border-amber-200/70 text-xs font-medium">
            <SparklesIcon size={14} className="text-amber-600" />
            <span>Evidence-backed answers</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold text-stone-900 tracking-tight">
            Ask Your Second Brain
          </h1>
          <p className="text-sm text-stone-500 max-w-lg mx-auto">
            Ask about your notes, projects, and calendar. Retrieved facts are linked to their original source.
          </p>
        </div>

        {/* Question Form */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
          className="relative"
        >
          <div className="flex items-center bg-white border border-stone-300 hover:border-stone-400 focus-within:border-stone-900 rounded-2xl shadow-xs transition-all px-4 py-2">
            <SearchIcon size={18} className="text-stone-400 shrink-0 mr-3" />
            <input
              ref={inputRef}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask anything (e.g. 'What should I do next?', 'Find client feedback on the prototype')..."
              className="w-full text-sm py-2 bg-transparent focus:outline-none text-stone-800 placeholder:text-stone-400"
            />
            <button
              type="submit"
              disabled={busy || !question.trim()}
              className="shrink-0 ml-2 px-4 py-2 rounded-xl bg-stone-900 text-white hover:bg-stone-800 disabled:opacity-40 text-xs font-medium flex items-center gap-1.5 shadow-2xs transition-colors"
            >
              <SendIcon size={13} />
              {busy ? "Thinking…" : "Ask"}
            </button>
          </div>
        </form>

        {/* Suggested prompts */}
        <div className="space-y-2 text-center">
          <span className="text-[11px] font-medium uppercase tracking-wider text-stone-400">
            Try asking
          </span>
          <div className="flex flex-wrap gap-2 justify-center">
            {["What should I focus on next?", "What deadlines are coming up?", "Summarize my latest notes."].map((example) => (
              <button
                key={example}
                onClick={() => {
                  setQuestion(example);
                  ask(example);
                }}
                className="text-xs rounded-xl border border-stone-200/90 bg-white hover:bg-amber-50/50 hover:border-amber-300 px-3.5 py-2 text-stone-700 shadow-2xs transition-all text-left"
              >
                &ldquo;{example}&rdquo;
              </button>
            ))}
          </div>
        </div>

        {/* Recent Questions */}
        {recentQuestions.length > 0 && !answer && (
          <div className="space-y-1.5 pt-4 text-center">
            <span className="text-[10px] uppercase font-semibold tracking-wider text-stone-400">
              Recent Queries
            </span>
            <div className="flex flex-wrap gap-1.5 justify-center">
              {recentQuestions.map((q, i) => (
                <button
                  key={i}
                  onClick={() => {
                    setQuestion(q);
                    ask(q);
                  }}
                  className="text-xs px-2.5 py-1 rounded-lg bg-stone-100 hover:bg-stone-200 text-stone-600 truncate max-w-xs transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Answer Output */}
        {answer && (
          <div className="bg-white border border-stone-200/90 rounded-3xl p-6 sm:p-8 shadow-xs space-y-6 animate-in fade-in">
            {/* Header info */}
            <div className="flex items-center justify-between pb-3 border-b border-stone-100">
              <div className="flex items-center gap-2 text-xs text-stone-500">
                <SparklesIcon size={16} className="text-amber-600" />
                <span>
                  Answered via{" "}
                  <strong className="text-stone-800 capitalize">
                    {answer.path === "retrieval" ? "document retrieval" : `${answer.path} reasoning`}
                  </strong>
                </span>
              </div>
              <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-stone-100 text-stone-600">
                Provenanced Fact
              </span>
            </div>

            {/* Answer Content */}
            <div className="text-sm leading-relaxed text-stone-800 whitespace-pre-line space-y-2">
              {answer.answer}
            </div>

            {/* Extracted Facts */}
            {answer.facts && Object.keys(answer.facts).length > 0 && (
              <div className="bg-stone-50/70 border border-stone-200/70 rounded-2xl p-4 space-y-2">
                <h4 className="text-[11px] font-semibold uppercase tracking-wider text-stone-500">
                  Key Extracted Data Points
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                  {Object.entries(answer.facts).map(([key, value]) => (
                    <div key={key} className="flex items-start gap-1.5 text-stone-700">
                      <span className="text-stone-400 font-mono text-[11px]">{key}:</span>
                      <span className="font-medium truncate">
                        {typeof value === "object" ? JSON.stringify(value) : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Citations and Provenance */}
            {answer.citations.length > 0 && (
              <div className="space-y-3 pt-2">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-stone-400 flex items-center gap-1.5">
                  <BookOpenIcon size={14} />
                  Cited Sources ({answer.citations.length})
                </h3>

                <div className="space-y-2.5">
                  {answer.citations.map((citation, i) => (
                    <div
                      key={i}
                      className="p-3.5 rounded-2xl bg-stone-50/60 border border-stone-200/80 space-y-1.5 hover:bg-white hover:shadow-2xs transition-all"
                    >
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-semibold text-stone-900">
                          {citation.title || "Untitled Document"}
                        </span>
                        {citation.page != null && (
                          <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-stone-200/70 text-stone-700">
                            Page {citation.page}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-stone-600 italic pl-2 border-l-2 border-amber-300 leading-relaxed">
                        &ldquo;{String(citation.quote)}&rdquo;
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
