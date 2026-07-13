const SEVERITY_ORDER = { none: 0, low: 1, medium: 2, high: 3 };

export function findingReviewSummary(result) {
  const findings = Array.isArray(result?.findings) ? result.findings : [];
  const reviewed = findings.filter((finding) => finding?.review && typeof finding.review === "object");
  const unreviewed = findings.filter((finding) => !finding?.review || typeof finding.review !== "object");
  const highestUnreviewedSeverity = unreviewed.reduce((highest, finding) => {
    const severity = normalizedSeverity(finding?.severity);
    return SEVERITY_ORDER[severity] > SEVERITY_ORDER[highest] ? severity : highest;
  }, "none");
  return {
    rawFindingCount: findings.length,
    reviewedFindingCount: reviewed.length,
    unreviewedFindingCount: unreviewed.length,
    highestUnreviewedSeverity,
  };
}

export function applyFindingReviewToScan(scan, fingerprint, review) {
  if (!scan || !fingerprint || !Array.isArray(scan.findings)) return scan;
  let changed = false;
  const findings = scan.findings.map((finding) => {
    if (finding?.fingerprint !== fingerprint) return finding;
    changed = true;
    return { ...finding, review: review && typeof review === "object" ? { ...review } : null };
  });
  if (!changed) return scan;
  const updated = { ...scan, findings };
  return { ...updated, reviewSummary: findingReviewSummary(updated) };
}

export function findingReviewLabel(review) {
  if (!review || typeof review !== "object") return "Unreviewed";
  return review.status === "expected" ? "Reviewed as expected" : "Reviewed";
}

function normalizedSeverity(value) {
  const severity = String(value || "low").toLowerCase();
  return Object.hasOwn(SEVERITY_ORDER, severity) ? severity : "high";
}
