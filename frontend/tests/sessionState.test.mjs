import assert from "node:assert/strict";
import test from "node:test";

import { parseSessionEnvelope } from "../src/lib/sessionState.ts";

const migrateDeck = (parsed) => Array.isArray(parsed) ? parsed : [];

test("reads the current versioned session envelope without migration", () => {
  const parsed = parseSessionEnvelope(
    JSON.stringify({ version: 2, data: [{ personId: "p1", name: "甲" }] }),
    2,
    [],
    migrateDeck,
  );
  assert.equal(parsed.migrated, false);
  assert.deepEqual(parsed.value, [{ personId: "p1", name: "甲" }]);
});

test("migrates legacy arrays and safely rejects malformed data", () => {
  const legacy = parseSessionEnvelope(JSON.stringify(["candidate-old"]), 2, [], migrateDeck);
  assert.equal(legacy.migrated, true);
  assert.deepEqual(legacy.value, ["candidate-old"]);

  const malformed = parseSessionEnvelope("{broken", 2, [], migrateDeck);
  assert.equal(malformed.migrated, false);
  assert.deepEqual(malformed.value, []);
});
