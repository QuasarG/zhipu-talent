import assert from "node:assert/strict";
import test from "node:test";

import { canSubmitProfile } from "../src/features/grill/grillModel.ts";

test("blocks an empty 0/7 profile", () => {
  assert.equal(canSubmitProfile(0, 7), false);
});

test("blocks a partially confirmed profile", () => {
  assert.equal(canSubmitProfile(6, 7), false);
});

test("allows submission only when every required field is confirmed", () => {
  assert.equal(canSubmitProfile(7, 7), true);
});

test("does not treat an empty requirement schema as complete", () => {
  assert.equal(canSubmitProfile(0, 0), false);
});
