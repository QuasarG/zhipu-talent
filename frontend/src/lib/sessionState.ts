import { useEffect, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

export interface SessionEnvelope<T> {
  version: number;
  data: T;
}

// 用户命名空间：sessionStorage 按用户隔离，换号不继承前一账号的选择和会话。
// App 在登录态变化时调用 setSessionNamespace；登出清空时顺带清掉所有用户态前缀键。
let _namespace = "";

export function setSessionNamespace(userId: string) {
  if (_namespace === userId) return;
  if (typeof window !== "undefined" && _namespace) {
    // 切换/登出：清旧用户的所有键，避免泄露到下一个会话
    try {
      const stale = Object.keys(window.sessionStorage).filter((k) => k.startsWith(`u:${_namespace}:`));
      for (const key of stale) window.sessionStorage.removeItem(key);
    } catch {
      /* storage 不可用时静默 */
    }
  }
  _namespace = userId;
}

export const sessionKey = (key: string) => (_namespace ? `u:${_namespace}:${key}` : key);

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
      const stored = window.sessionStorage.getItem(sessionKey(key));
      return stored === null ? fallback : JSON.parse(stored) as T;
    } catch {
      return fallback;
    }
  });

  useEffect(() => {
    try {
      if (typeof window === "undefined") return;
      window.sessionStorage.setItem(sessionKey(key), JSON.stringify(value));
    } catch {
      // Storage may be unavailable in hardened browser contexts.
    }
  }, [key, value]);

  return [value, setValue];
}
