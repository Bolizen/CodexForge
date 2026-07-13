const VALID_COMPARISON_STATUSES = new Set(["not-configured", "identical", "drift", "incomplete", "incompatible", "invalid"]);
const MAX_ITEMS = 300;

export function normalizeTrustedDependencyBaseline(value) {
  const baseline = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const comparisonValue = baseline.comparison && typeof baseline.comparison === "object" ? baseline.comparison : {};
  const approvalValue = baseline.approval && typeof baseline.approval === "object" ? baseline.approval : {};
  const comparisonStatus = VALID_COMPARISON_STATUSES.has(comparisonValue.status)
    ? comparisonValue.status
    : baseline.configured ? "invalid" : "not-configured";
  return {
    configured: baseline.configured === true,
    valid: baseline.valid === true,
    status: text(baseline.status) || (baseline.configured ? "invalid" : "not-configured"),
    fingerprint: text(baseline.fingerprint),
    sourceScanId: positiveInteger(baseline.sourceScanId),
    sourceScanDate: text(baseline.sourceScanDate),
    note: text(baseline.note),
    createdAt: text(baseline.createdAt),
    updatedAt: text(baseline.updatedAt),
    explanation: text(baseline.explanation),
    approval: {
      eligible: approvalValue.eligible === true,
      fingerprint: text(approvalValue.fingerprint),
      reason: text(approvalValue.reason),
    },
    comparison: {
      status: comparisonStatus,
      explanation: text(comparisonValue.explanation),
      changeCount: nonNegativeInteger(comparisonValue.changeCount),
      highestSeverity: severity(comparisonValue.highestSeverity),
      changes: objectArray(comparisonValue.changes).slice(0, MAX_ITEMS),
      findings: objectArray(comparisonValue.findings).slice(0, MAX_ITEMS),
      truncated: comparisonValue.truncated === true,
    },
  };
}

export function trustedBaselineComparisonLabel(status) {
  return {
    identical: "Matches approved baseline",
    drift: "Drift detected",
    incomplete: "Comparison incomplete",
    incompatible: "Incompatible",
    invalid: "Baseline unavailable",
    "not-configured": "Not configured",
  }[status] || "Baseline unavailable";
}

export function shortBaselineFingerprint(value) {
  const fingerprint = text(value);
  return fingerprint.length > 18 ? `${fingerprint.slice(0, 12)}...${fingerprint.slice(-6)}` : fingerprint;
}

function objectArray(value) {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === "object" && !Array.isArray(item)) : [];
}

function positiveInteger(value) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
}

function nonNegativeInteger(value) {
  const number = Number(value);
  return Number.isInteger(number) && number >= 0 ? number : 0;
}

function severity(value) {
  const normalized = text(value).toLowerCase();
  return new Set(["none", "low", "medium", "high"]).has(normalized) ? normalized : "high";
}

function text(value) {
  return value === undefined || value === null ? "" : String(value).replaceAll(/\s+/g, " ").trim();
}
