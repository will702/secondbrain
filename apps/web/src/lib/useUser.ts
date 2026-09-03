"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function useUser() {
  const [user, setUser] = useState<{ display_name: string; autonomy_level: number } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<{ display_name: string; autonomy_level: number }>("/auth/me")
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  return { user, loading };
}

export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString([], {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
