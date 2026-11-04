"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  BrainIcon,
  CalendarIcon,
  InboxIcon,
  PlusIcon,
  SearchIcon,
  SparklesIcon,
} from "./Icons";
import QuickCaptureModal from "./QuickCaptureModal";

const NAV = [
  { href: "/", label: "Home", icon: SparklesIcon },
  { href: "/inbox", label: "Inbox", icon: InboxIcon },
  { href: "/calendar", label: "Calendar", icon: CalendarIcon },
  { href: "/brain", label: "Brain", icon: BrainIcon },
  { href: "/ask", label: "Ask", icon: SearchIcon },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [captureOpen, setCaptureOpen] = useState(false);
  const [showAiBanner, setShowAiBanner] = useState(false);

  // Surface AI setup only when the guided installer exists and hasn't run.
  useEffect(() => {
    let cancelled = false;
    api
      .get<{ available: boolean; phase: string; server_online: boolean }>("/ai/status")
      .then((s) => {
        if (cancelled) return;
        setShowAiBanner(s.available && !s.server_online && s.phase !== "installing");
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      router.push("/login");
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-[#fcfbf9] text-stone-800 selection:bg-amber-100 selection:text-amber-900">
      <a
        href="#main-content"
        className="fixed left-4 top-3 z-50 -translate-y-20 rounded-lg bg-stone-900 px-3 py-2 text-xs font-medium text-white focus:translate-y-0"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-stone-200/80 bg-white/90 backdrop-blur-md">
        <div className="mx-auto flex h-15 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-5">
            <Link href="/" className="group flex items-center gap-2.5" aria-label="Second Brain home">
              <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-stone-900 text-xs font-bold text-amber-400 transition-transform group-hover:scale-105">
                SB
              </span>
              <span className="hidden sm:block">
                <span className="block text-sm font-semibold leading-tight text-stone-900">Second Brain</span>
                <span className="block text-[10px] font-medium uppercase tracking-wider text-stone-400">Personal workspace</span>
              </span>
            </Link>
            <nav className="hidden items-center gap-1 md:flex" aria-label="Primary navigation">
              {NAV.map((item) => {
                const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                      active ? "bg-stone-900 text-white" : "text-stone-600 hover:bg-stone-100 hover:text-stone-900"
                    }`}
                  >
                    <Icon size={14} className={active ? "text-amber-400" : "opacity-70"} />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setCaptureOpen(true)}
              className="flex items-center gap-1.5 rounded-full bg-stone-900 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-stone-800"
            >
              <PlusIcon size={14} className="text-amber-400" />
              <span className="hidden sm:inline">Quick capture</span>
              <span className="sm:hidden">Capture</span>
            </button>
            <button type="button" onClick={logout} className="rounded-lg px-2 py-1.5 text-xs text-stone-500 hover:bg-stone-100 hover:text-stone-800">
              Sign out
            </button>
          </div>
        </div>
        <nav className="flex items-center justify-around border-t border-stone-100 bg-stone-50/70 px-3 py-2 md:hidden" aria-label="Mobile navigation">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined} className={`flex min-w-12 flex-col items-center gap-0.5 rounded-lg px-2 py-1 text-[10px] font-medium ${active ? "text-stone-900" : "text-stone-500"}`}>
                <Icon size={16} className={active ? "text-amber-600" : "opacity-60"} />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>
      {showAiBanner && pathname !== "/setup" && (
        <div className="border-b border-amber-200/70 bg-amber-50/90">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-2 sm:px-6">
            <p className="text-[11px] text-amber-900">
              AI features (document understanding, Ask) need a one-time local download.
            </p>
            <Link
              href="/setup"
              className="shrink-0 rounded-full bg-stone-900 px-3 py-1 text-[11px] font-medium text-white transition-transform hover:bg-stone-800 active:scale-[0.97] motion-reduce:transition-none"
            >
              Enable AI
            </Link>
          </div>
        </div>
      )}
      <main id="main-content" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
        {children}
      </main>
      <footer className="border-t border-stone-200/60 py-5 text-center text-xs text-stone-400">Second Brain · Your sources, connected</footer>
      <QuickCaptureModal isOpen={captureOpen} onClose={() => setCaptureOpen(false)} onSuccess={() => window.location.reload()} />
    </div>
  );
}
