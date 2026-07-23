# Glacial 0.5.0 Guided Review Release

Glacial 0.5.0 makes the path from registering a project to completing the available review workflow clearer and more evidence-backed. A completed review records what was examined; it does not prove that a project is safe, secure, clean, or fully verified.

## Unified finding review

- Added one priority-ordered finding-review workbench with review-status, severity, and category filters; title and project-relative-path search; visible progress; and Next unresolved navigation.
- Preserved persisted finding review and reopen behavior, stable finding identities, historical scans, and the existing category-based detail views.
- Reduced the prominence of immutable raw-risk metrics after findings are reviewed while keeping scanner context available.

## Bounded scanner evidence

- Suspicious-text-pattern findings now include the first one-based matching line, deterministic match count, rule identifier, and a short sanitized excerpt.
- Evidence remains bounded and redacts credential-like values, authorization material, URLs containing credentials, private-key text, and long high-entropy values.
- Existing secret-designated files never contribute excerpts.
- The same safe scanner context appears in the Reports workbench and Markdown reports; legacy findings without evidence continue to render normally.

## Honest completion and coverage

- “Review complete for this scan” appears only when every finding has a review state, scan coverage is known and complete, and any applicable dependency snapshot exactly matches a valid explicitly approved baseline.
- Incomplete or unavailable coverage, unresolved findings, dependency drift, malformed dependency data, and approval-required dependency snapshots remain visible and keep the workflow incomplete.
- Current and historical scans receive separate conservative summaries. No completion state claims that Glacial verified project safety.

## Guided first-project flow

- Added a compact, dismissible five-step checklist covering project registration, first scan, finding review, coverage understanding, and dependency review when applicable.
- New or registered projects lead directly toward the first scan, and successful scans lead to the Reports workbench.
- Checklist dismissal is local UI state only and does not alter project, scan, finding-review, coverage, or dependency data.

## Desktop presentation

- Refined Projects into compact project entries with a separate selected-project metadata editor.
- Preserved the Icefields-branded OLED interface, local owned-backend lifecycle, English-only NSIS packaging, and signed installer and portable release semantics.
- Validated the guided-review and project flows at normal desktop and narrower responsive widths, including empty, unresolved, incomplete, complete, dependency-action, dismissed-checklist, and historical-scan states.
