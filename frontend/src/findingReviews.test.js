import assert from "node:assert/strict";
import test from "node:test";

import { applyFindingReviewToScan, findingReviewLabel, findingReviewSummary } from "./findingReviews.js";

test("review-aware summary preserves raw findings and highest unreviewed severity", () => {
  const result = {
    overall_risk: "high",
    findings: [
      { fingerprint: "one", severity: "high", review: { status: "expected" } },
      { fingerprint: "two", severity: "low", review: null },
      { fingerprint: "three", severity: "high", review: { status: "reviewed" } },
    ],
  };
  assert.deepEqual(findingReviewSummary(result), {
    rawFindingCount: 3,
    reviewedFindingCount: 2,
    unreviewedFindingCount: 1,
    highestUnreviewedSeverity: "low",
  });
  assert.equal(result.overall_risk, "high");
});

test("applying and reopening a review changes only the exact fingerprint", () => {
  const scan = {
    findings: [
      { fingerprint: "same", severity: "high", path: "tests/a.py", review: null },
      { fingerprint: "changed", severity: "high", path: "tests/a.py", review: null },
    ],
  };
  const reviewed = applyFindingReviewToScan(scan, "same", { status: "expected", note: "Fixture" });
  assert.equal(reviewed.findings[0].review.note, "Fixture");
  assert.equal(reviewed.findings[1].review, null);
  assert.equal(reviewed.reviewSummary.unreviewedFindingCount, 1);
  assert.equal(scan.findings[0].review, null);

  const reopened = applyFindingReviewToScan(reviewed, "same", null);
  assert.equal(reopened.findings[0].review, null);
  assert.equal(reopened.reviewSummary.unreviewedFindingCount, 2);
});

test("review labels distinguish expected, reviewed, and unresolved evidence", () => {
  assert.equal(findingReviewLabel(null), "Unreviewed");
  assert.equal(findingReviewLabel({ status: "reviewed" }), "Reviewed");
  assert.equal(findingReviewLabel({ status: "expected" }), "Reviewed as expected");
});

test("unknown unreviewed severities fail closed as high", () => {
  const summary = findingReviewSummary({ findings: [{ severity: "future-critical", review: null }] });
  assert.equal(summary.highestUnreviewedSeverity, "high");
  assert.equal(summary.unreviewedFindingCount, 1);
});
