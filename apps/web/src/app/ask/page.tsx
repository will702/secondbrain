"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, AskAnswer } from "@/lib/api";
import { useUser } from "@/lib/useUser";

const EXAMPLES = [
  "What should I work on tonight?",
  "What's due this semester?",
  "What deadlines am I forgetting?",
  "Find everything about my midterm",
  "What am I behind on?",
];

export default function AskPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
    if (user) inputRef.current?.focus();
  }, [loading, user, router]);

  const ask = async (q: string) => {
    if (!q.trim()) return;
    setBusy(true);
    setAnswer(null);
    try {
      setAnswer(await api.post<AskAnswer>("/ask", { question: q }));
    } catch {
      setAnswer({
        answer: "Something went wrong reaching the API.",
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
      <div className="max-w-2xl mx-auto space-y-6">
        <div className="text-center pt-4">
          <h1 className="text-xl font-semibold text-stone-900">Ask</h1>
          <p className="text-sm text-stone-500 mt-1">
            Ask anything about your documents, deadlines, tasks, and plans.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
          className="flex gap-2"
        >
          <input
            ref={inputRef}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="What should I do?"
            className="flex-1 rounded-full border border-stone-300 bg-white px-5 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-stone-300"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-full bg-stone-900 text-white px-6 text-sm hover:bg-stone-700 disabled:opacity-50"
          >
            {busy ? "Thinking…" : "Ask"}
          </button>
        </form>

        <div className="flex flex-wrap gap-2 justify-center">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              onClick={() => {
                setQuestion(example);
                ask(example);
              }}
              className="text-xs rounded-full border border-stone-200 bg-white px-3 py-1.5 text-stone-600 hover:border-stone-400"
            >
              {example}
            </button>
          ))}
        </div>

        {answer && (
          <div className="bg-white border border-stone-200 rounded-2xl p-6 space-y-4">
            <p className="text-sm leading-relaxed text-stone-800 whitespace-pre-line">
              {answer.answer}
            </p>
            <p className="text-xs text-stone-300">
              answered via {answer.path === "retrieval" ? "document retrieval" : `structured ${answer.path} query`}
            </p>
            {answer.citations.length > 0 && (
              <div>
                <h3 className="text-xs uppercase tracking-wider text-stone-400 mb-2">
                  Sources
                </h3>
                <ul className="space-y-2">
                  {answer.citations.map((citation, i) => (
                    <li
                      key={i}
                      className="text-xs text-stone-500 border-l-2 border-stone-200 pl-3"
                    >
                      {citation.title && (
                        <span className="text-stone-700">{citation.title}</span>
                      )}
                      {citation.page != null && ` · page ${citation.page}`}
                      <p className="text-stone-400 italic mt-0.5">
                        &ldquo;{String(citation.quote).slice(0, 160)}&rdquo;
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
