import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

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
