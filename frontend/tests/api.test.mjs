import assert from "node:assert/strict";
import test from "node:test";

import { api, UnauthorizedError } from "../src/lib/api.ts";

test("turns API 401 responses into a structured UnauthorizedError", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(
    JSON.stringify({ detail: "登录态已过期" }),
    { status: 401, headers: { "Content-Type": "application/json" } },
  );
  try {
    await assert.rejects(
      () => api.persons.list(),
      (error) => error instanceof UnauthorizedError
        && error.status === 401
        && error.message === "登录态已过期",
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
