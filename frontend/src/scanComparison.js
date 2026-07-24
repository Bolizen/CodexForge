import { compareProjectMetadataScans } from "./projectDrift.js";

export const EMPTY_SCAN_COMPARISON = Object.freeze({
  options: [],
  hasMoreOptions: false,
  nextOptionsOffset: null,
  baseScanId: null,
  targetScanId: null,
  result: null,
  loading: false,
  error: "",
});

const STATUS_LABELS = {
  comparable: "Comparable",
  "partially-comparable": "Partially comparable",
  indeterminate: "Indeterminate",
  unavailable: "Unavailable",
};

export function normalizeComparisonOptionsPage(value) {
  const scans = Array.isArray(value?.scans)
    ? value.scans.map(normalizeScanSummary).filter(Boolean)
    : [];
  return {
    scans,
    hasMore: value?.hasMore === true,
    nextOffset: Number.isSafeInteger(value?.nextOffset) && value.nextOffset >= 0
      ? value.nextOffset
      : null,
  };
}

export function normalizeScanComparison(value) {
  const baseScan = normalizeScanSummary(value?.baseScan);
  const targetScan = normalizeScanSummary(value?.targetScan);
  const metadata = metadataComparison(value?.baseScan, value?.targetScan);
  const sections = {
    findings: normalizeSection(value?.sections?.findings),
    dependencies: normalizeSection(value?.sections?.dependencies),
    coverage: normalizeCoverage(value?.sections?.coverage),
    projectMetadata: metadata,
  };
  const overallStatus = combinedStatus([
    normalizeStatus(value?.overallStatus),
    ...Object.values(sections).map((section) => section.status),
  ]);
  return { baseScan, targetScan, overallStatus, sections };
}

export function comparisonStatusLabel(status) {
  return STATUS_LABELS[normalizeStatus(status)];
}

export function comparisonCountLabel(value) {
  return Number.isSafeInteger(value) && value >= 0 ? String(value) : "Indeterminate";
}

export function comparisonScanOptionLabel(scan) {
  if (!scan) return "Select a scan";
  const date = scan.scanDate ? new Date(scan.scanDate) : null;
  const timestamp = date && !Number.isNaN(date.getTime())
    ? date.toLocaleString()
    : "Unknown time";
  return `Scan #${scan.id} · ${timestamp} · ${capitalize(scan.completionState)} · ${capitalize(scan.reliabilityStatus)}`;
}

export function comparisonExampleLabel(example, type) {
  if (!example || typeof example !== "object") return "Unavailable detail";
  if (type === "dependency") {
    const identity = [bounded(example.ecosystem, 40), bounded(example.name, 120)].filter(Boolean).join(":");
    const version = bounded(example.version || example.afterVersion, 100);
    const before = bounded(example.beforeVersion, 100);
    return before ? `${identity} ${before || "unknown"} → ${version || "unknown"}` : `${identity}${version ? ` ${version}` : ""}`;
  }
  const finding = [bounded(example.type, 100), bounded(example.path, 160)].filter(Boolean).join(" · ");
  const changes = Array.isArray(example.changedProperties)
    ? ` (${example.changedProperties.map((item) => bounded(item, 60)).filter(Boolean).join(", ")})`
    : "";
  return `${finding || "Persisted finding"}${changes}`;
}

function metadataComparison(base, target) {
  if (
    base?.metadataSource?.reliable !== true
    || target?.metadataSource?.reliable !== true
    || !base.metadataSource.scan
    || !target.metadataSource.scan
  ) {
    const reasons = [
      base?.metadataSource?.reason,
      target?.metadataSource?.reason,
    ].map((item) => bounded(item, 300)).filter(Boolean);
    return {
      status: "indeterminate",
      message: reasons.join(" ") || "Persisted project metadata is unavailable or malformed.",
      counts: { unchanged: 0, added: 0, removed: 0, changed: 0, unavailable: 7 },
      categories: [],
    };
  }
  return compareProjectMetadataScans(base.metadataSource.scan, target.metadataSource.scan);
}

function normalizeScanSummary(value) {
  if (!value || !Number.isSafeInteger(value.id) || value.id <= 0) return null;
  return {
    id: value.id,
    scanDate: typeof value.scanDate === "string" ? value.scanDate.slice(0, 80) : "",
    completionState: ["complete", "incomplete", "unknown"].includes(value.completionState)
      ? value.completionState
      : "unknown",
    reliabilityStatus: ["reliable", "limited", "indeterminate"].includes(value.reliabilityStatus)
      ? value.reliabilityStatus
      : "indeterminate",
  };
}

function normalizeSection(value) {
  const counts = {};
  if (value?.counts && typeof value.counts === "object" && !Array.isArray(value.counts)) {
    for (const [key, count] of Object.entries(value.counts).slice(0, 20)) {
      counts[bounded(key, 60)] = Number.isSafeInteger(count) && count >= 0 ? count : null;
    }
  }
  const examples = {};
  if (value?.examples && typeof value.examples === "object" && !Array.isArray(value.examples)) {
    for (const [key, items] of Object.entries(value.examples).slice(0, 20)) {
      examples[bounded(key, 60)] = Array.isArray(items) ? items.slice(0, 10) : [];
    }
  }
  return {
    status: normalizeStatus(value?.status),
    message: bounded(value?.message, 500),
    counts,
    examples,
    baseAnalysisStatus: bounded(value?.baseAnalysisStatus, 60),
    targetAnalysisStatus: bounded(value?.targetAnalysisStatus, 60),
  };
}

function normalizeCoverage(value) {
  const section = normalizeSection(value);
  const metrics = {};
  if (value?.metrics && typeof value.metrics === "object" && !Array.isArray(value.metrics)) {
    for (const [key, metric] of Object.entries(value.metrics).slice(0, 10)) {
      metrics[bounded(key, 60)] = {
        base: validCount(metric?.base),
        target: validCount(metric?.target),
        change: Number.isSafeInteger(metric?.change) ? metric.change : null,
      };
    }
  }
  return {
    ...section,
    metrics,
    baseComplete: typeof value?.baseComplete === "boolean" ? value.baseComplete : null,
    targetComplete: typeof value?.targetComplete === "boolean" ? value.targetComplete : null,
  };
}

function combinedStatus(statuses) {
  const normalized = statuses.map(normalizeStatus);
  if (normalized.every((status) => status === "comparable")) return "comparable";
  if (normalized.some((status) => ["comparable", "partially-comparable"].includes(status))) {
    return "partially-comparable";
  }
  return normalized.some((status) => status === "indeterminate")
    ? "indeterminate"
    : "unavailable";
}

function normalizeStatus(value) {
  return Object.hasOwn(STATUS_LABELS, value) ? value : "indeterminate";
}

function validCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function bounded(value, limit) {
  return typeof value === "string" ? value.trim().slice(0, limit) : "";
}

function capitalize(value) {
  const text = bounded(value, 60);
  return text ? `${text[0].toUpperCase()}${text.slice(1)}` : "Unknown";
}
