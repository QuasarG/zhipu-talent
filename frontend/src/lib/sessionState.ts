import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

export interface SessionEnvelope<T> {
  version: number;
  data: T;
}

export function parseSessionEnvelope<T>(
  raw: string | null,
  version: number,
  fallback: T,
  migrateLegacy: (parsed: unknown) => T,
): { value: T; migrated: boolean } {
  if (!raw) return { value: fallback, migrated: false };
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed && typeof parsed === "object"
      && "version" in parsed && "data" in parsed
      && (parsed as SessionEnvelope<unknown>).version === version
    ) {
      return { value: (parsed as SessionEnvelope<T>).data, migrated: false };
    }
    return { value: migrateLegacy(parsed), migrated: true };
  } catch {
    return { value: fallback, migrated: false };
  }
}

export function useSessionState<T>(
  key: string,
  initialValue: T | (() => T),
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    const fallback = typeof initialValue === "function"
      ? (initialValue as () => T)()
      : initialValue;
    try {
      if (typeof window === "undefined") return fallback;
      const stored = window.sessionStorage.getItem(key);
      return stored === null ? fallback : JSON.parse(stored) as T;
    } catch {
      return fallback;
    }
  });

  useEffect(() => {
    try {
      if (typeof window === "undefined") return;
      window.sessionStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Storage may be unavailable in hardened browser contexts.
    }
  }, [key, value]);

  return [value, setValue];
}
