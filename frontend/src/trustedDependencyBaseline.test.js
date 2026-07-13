import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeTrustedDependencyBaseline,
  shortBaselineFingerprint,
  trustedBaselineComparisonLabel,
} from "./trustedDependencyBaseline.js";


test("normalizes absent and configured trusted baseline states conservatively", () => {
  const absent = normalizeTrustedDependencyBaseline(null);
  assert.equal(absent.configured, false);
  assert.equal(absent.comparison.status, "not-configured");

  const configured = normalizeTrustedDependencyBaseline({
    configured: true,
    valid: true,
    fingerprint: `cfdb1_${"a".repeat(64)}`,
    sourceScanId: 7,
    note: "Approved.",
    approval: { eligible: true, fingerprint: `cfdb1_${"b".repeat(64)}` },
    comparison: {
      status: "drift",
      changeCount: 2,
      highestSeverity: "high",
      changes: [{ changeType: "version-changed" }],
      findings: [{ type: "trusted-baseline-version-changed", severity: "low" }],
    },
  });
  assert.equal(configured.configured, true);
  assert.equal(configured.comparison.status, "drift");
  assert.equal(configured.comparison.changeCount, 2);
  assert.equal(configured.approval.eligible, true);
  assert.equal(trustedBaselineComparisonLabel("drift"), "Drift detected");
  assert.equal(shortBaselineFingerprint(configured.fingerprint), "cfdb1_aaaaaa...aaaaaa");
});

test("invalid comparison data fails closed without inventing eligibility", () => {
  const value = normalizeTrustedDependencyBaseline({
    configured: true,
    valid: false,
    approval: { eligible: "yes" },
    comparison: { status: "unexpected", changeCount: -4, highestSeverity: "future" },
  });
  assert.equal(value.approval.eligible, false);
  assert.equal(value.comparison.status, "invalid");
  assert.equal(value.comparison.changeCount, 0);
  assert.equal(value.comparison.highestSeverity, "high");
});
