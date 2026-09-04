"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import AppShell from "@/components/AppShell";
import { api, ApiError } from "@/lib/api";
import { useUser } from "@/lib/useUser";
import { SparklesIcon } from "@/components/Icons";

interface AiProgress {
  bytes_done: number | null;
  bytes_total: number | null;
  current_repo: string | null;
}

interface AiStatus {
  available: boolean;
  phase: "unavailable" | "not_installed" | "installing" | "ready" | "error";
  detail: string | null;
  progress: AiProgress | null;
  server_online: boolean;
  free_gb: number | null;
}

const gb = (bytes: number | null) => (bytes == null ? null : bytes / 1024 ** 3);

export default function SetupPage() {
  const { user, loading } = useUser();
  const router = useRouter();
  const [status, setStatus] = useState<AiStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  const refresh = useCallback(async () => {
    try {
      const next = await api.get<AiStatus>("/ai/status");
      setStatus(next);
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    const interval = status?.phase === "installing" ? 1500 : 5000;
    pollRef.current = setInterval(refresh, interval);
    const initial = setTimeout(refresh, 0);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      clearTimeout(initial);
    };
  }, [refresh, status?.phase]);

  const beginInstall = async () => {
    setStarting(true);
    setError(null);
    try {
      await api.post("/ai/install");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the download");
    } finally {
      setStarting(false);
    }
  };

  const pct =
    status?.progress?.bytes_done != null && status.progress.bytes_total
      ? Math.min(100, (status.progress.bytes_done / status.progress.bytes_total) * 100)
      : status?.phase === "installing"
        ? null
        : 0;

  const done = gb(status?.progress?.bytes_done ?? null);
  const total = gb(status?.progress?.bytes_total ?? null);

  return (
    <AppShell>
      <div className="mx-auto max-w-2xl px-4 py-12 sm:px-6">
        <div className="text-center space-y-3 pb-8">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-stone-900 text-amber-400 shadow-md">
            <SparklesIcon size={20} />
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-stone-900">
            {status?.phase === "ready" ? "AI is ready" : "Enable AI"}
          </h1>
          <p className="mx-auto max-w-md text-xs leading-relaxed text-stone-500">
            Second Brain runs its own local AI engine — document understanding,
            embeddings, and Ask. Everything stays on this Mac; nothing is sent
            to any cloud.
          </p>
        </div>

        <div className="space-y-4 rounded-3xl border border-stone-200/90 bg-white p-7 shadow-xs">
          {status === null && (
            <p className="py-8 text-center text-xs text-stone-400">Checking AI status…</p>
          )}

          {status?.phase === "unavailable" && (
            <div className="space-y-3 text-xs leading-relaxed text-stone-600">
              <p>
                This build doesn&apos;t include the guided AI installer (it looks
                for the bundled runtime). You can still use Second Brain with an
                external local-ai server on <code className="rounded bg-stone-100 px-1 py-0.5 text-[11px]">127.0.0.1:8080</code>.
              </p>
            </div>
          )}

          {status?.phase === "not_installed" && (
            <div className="space-y-5">
              <ul className="space-y-2.5 text-xs text-stone-600">
                <li className="flex items-start gap-2.5">
                  <Dot /> Private local models (Qwen family, ~10 GB download)
                </li>
                <li className="flex items-start gap-2.5">
                  <Dot /> Resumable — pause or lose connection anytime
                </li>
                <li className="flex items-start gap-2.5">
                  <Dot /> Recommended: 16 GB RAM and ~15 GB free space
                  {status.free_gb != null && (
                    <span className={status.free_gb < 15 ? "text-rose-600" : "text-stone-400"}>
                      ({status.free_gb.toFixed(0)} GB available)
                    </span>
                  )}
                </li>
              </ul>
              {status.free_gb != null && status.free_gb < 15 && (
                <p className="rounded-xl border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-600">
                  Not enough free disk space. Free up space and refresh.
                </p>
              )}
              <button
                onClick={beginInstall}
                disabled={starting || (status.free_gb != null && status.free_gb < 15)}
                className="w-full rounded-xl bg-stone-900 py-2.5 text-xs font-semibold text-white shadow-2xs transition-all hover:bg-stone-800 active:scale-[0.99] disabled:opacity-50 motion-reduce:transition-none"
              >
                {starting ? "Starting…" : "Download & enable AI"}
              </button>
            </div>
          )}

          {status?.phase === "installing" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium text-stone-800">
                  {status.detail ?? "Preparing the AI engine"}
                </span>
                <span className="tabular-nums text-stone-400">
                  {pct != null ? `${pct.toFixed(0)}%` : "…"}
                </span>
              </div>
              <div
                role="progressbar"
                aria-valuenow={pct ?? undefined}
                aria-valuemin={0}
                aria-valuemax={100}
                className="h-2 overflow-hidden rounded-full bg-stone-100"
              >
                <div
                  className="h-full rounded-full bg-amber-500 transition-[width] duration-700 ease-out motion-reduce:transition-none"
                  style={{ width: `${pct ?? 100}%`, opacity: pct == null ? 0.35 : 1 }}
                />
              </div>
              <p className="text-[11px] text-stone-400">
                {done != null && total != null
                  ? `${done.toFixed(1)} of ${total.toFixed(1)} GB — you can keep using Second Brain; downloads resume automatically.`
                  : "Fetching model catalog… downloads resume automatically."}
              </p>
            </div>
          )}

          {status?.phase === "error" && (
            <div className="space-y-4">
              <p className="rounded-xl border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-600">
                {status.detail ?? "Something went wrong."}
              </p>
              <button
                onClick={beginInstall}
                className="w-full rounded-xl bg-stone-900 py-2.5 text-xs font-semibold text-white shadow-2xs transition-all hover:bg-stone-800 active:scale-[0.99] motion-reduce:transition-none"
              >
                Try again
              </button>
            </div>
          )}

          {status?.phase === "ready" && (
            <div className="space-y-4 text-center">
              <p className="text-xs text-stone-600">
                {status.server_online
                  ? "The local AI engine is running. Uploads, Ask, and knowledge search are fully active."
                  : "Models are installed. The AI engine will start with the app."}
              </p>
              <button
                onClick={() => router.push("/")}
                className="rounded-xl bg-stone-900 px-6 py-2.5 text-xs font-semibold text-white shadow-2xs transition-all hover:bg-stone-800 active:scale-[0.99] motion-reduce:transition-none"
              >
                Back to Home
              </button>
            </div>
          )}

          {error && (
            <p className="rounded-xl border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-600">
              {error}
            </p>
          )}
        </div>

        <p className="pt-5 text-center text-[11px] text-stone-400">
          Second Brain works without AI too — Ask falls back to a summary of your structured facts.
        </p>
      </div>
    </AppShell>
  );
}

function Dot() {
  return <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-500" />;
}
