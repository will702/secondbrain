"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") {
        await api.post("/auth/register", {
          email,
          password,
          display_name: displayName || email.split("@")[0],
        });
      } else {
        await api.post("/auth/login", { email, password });
      }
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Invalid credentials or server unavailable");
    } finally {
      setBusy(false);
    }
  };

  const fillDemo = () => {
    setEmail("demo@secondbrain.dev");
    setPassword("demo-password-1");
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#fcfbf9] px-4 py-12 selection:bg-amber-100 selection:text-amber-900">
      <div className="w-full max-w-md space-y-6">
        {/* Brand Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex h-12 w-12 items-center justify-center rounded-2xl bg-stone-900 text-sm font-bold text-amber-400 shadow-md">
            SB
          </div>
          <h1 className="text-2xl font-bold text-stone-900 tracking-tight">
            Second Brain OS
          </h1>
          <p className="text-xs text-stone-500 max-w-xs mx-auto">
            Your personal operating system: drop information in, get connected knowledge and protected focus.
          </p>
        </div>

        {/* Form Card */}
        <form
          onSubmit={submit}
          className="bg-white border border-stone-200/90 rounded-3xl p-7 shadow-xs space-y-4"
        >
          <div className="flex items-center justify-between pb-1">
            <h2 className="text-sm font-semibold text-stone-900">
              {mode === "login" ? "Sign in to your space" : "Create your account"}
            </h2>
            <button
              type="button"
              onClick={fillDemo}
              className="text-[11px] text-amber-700 hover:text-amber-800 font-medium underline underline-offset-2"
            >
              Fill demo credentials
            </button>
          </div>

          {mode === "register" && (
            <div>
              <label className="block text-[11px] font-medium text-stone-600 mb-1">
                Display Name
              </label>
              <input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Willson (or your name)"
                className="w-full text-xs rounded-xl border border-stone-200 px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:ring-stone-900/10 focus:border-stone-400"
              />
            </div>
          )}

          <div>
            <label className="block text-[11px] font-medium text-stone-600 mb-1">
              Email Address
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full text-xs rounded-xl border border-stone-200 px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:ring-stone-900/10 focus:border-stone-400"
            />
          </div>

          <div>
            <label className="block text-[11px] font-medium text-stone-600 mb-1">
              Password
            </label>
            <input
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="8+ characters"
              className="w-full text-xs rounded-xl border border-stone-200 px-3.5 py-2.5 focus:outline-none focus:ring-2 focus:ring-stone-900/10 focus:border-stone-400"
            />
          </div>

          {error && (
            <p className="text-xs text-rose-600 bg-rose-50 p-2.5 rounded-xl border border-rose-200">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-xl bg-stone-900 text-white py-2.5 text-xs font-semibold hover:bg-stone-800 disabled:opacity-50 shadow-2xs transition-colors"
          >
            {busy ? "Working…" : mode === "login" ? "Sign in" : "Create account"}
          </button>

          <div className="pt-2 text-center border-t border-stone-100">
            <button
              type="button"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError(null);
              }}
              className="text-xs text-stone-500 hover:text-stone-800 transition-colors"
            >
              {mode === "login"
                ? "First time here? Create an account"
                : "Already have an account? Sign in"}
            </button>
          </div>
        </form>

        <p className="text-center text-[11px] text-stone-400">
          Local-first architecture · 100% private on your machine
        </p>
      </div>
    </div>
  );
}
