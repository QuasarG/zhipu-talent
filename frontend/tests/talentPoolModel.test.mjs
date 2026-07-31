import assert from "node:assert/strict";
import test from "node:test";

import {
  dominantTrack,
  transitionEngagementSelection,
} from "../src/features/pool/talentPoolModel.ts";

test("uses the highest weighted evaluated track", () => {
  assert.equal(dominantTrack([
    { track: "agent", weight: 0.3529 },
    { track: "safety", weight: 0.6471 },
  ]), "safety");
});

test("requires two deliberate clicks before committing an HR status", () => {
  const first = transitionEngagementSelection("newly_admitted", null, "contacted");
  assert.deepEqual(first, { pending: "contacted", commit: null });

  const second = transitionEngagementSelection("newly_admitted", first.pending, "contacted");
  assert.deepEqual(second, { pending: null, commit: "contacted" });
});

test("clicking another HR status moves the pending confirmation", () => {
  assert.deepEqual(
    transitionEngagementSelection("newly_admitted", "contacted", "interviewing"),
    { pending: "interviewing", commit: null },
  );
});
