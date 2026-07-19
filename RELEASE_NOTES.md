# Glacial 0.3.0 Release Candidate

Glacial 0.3.0 strengthens scan integrity and makes the documented local security boundary fail closed. This release candidate does not add remote deployment support or change Glacial's non-elevated Windows desktop privilege model.

## Highlights

- Repository-controlled `.glacialignore` exclusions remain visible, but any excluded file now makes the scan incomplete and unverified rather than allowing a Complete result.
- Malformed, invalid-UTF-8, non-object, and excessively nested `package.json` inputs now become explicit conservative inspection evidence instead of aborting the scan. Inspection continues for other supported files.
- Deterministic directory, file, filesystem-entry, inspected-byte, finding, and result-record budgets stop hostile or unusually large scans safely while preserving evidence collected before the stop.
- Trusted dependency baselines now include sanitized, opaque VCS selector and resolved-revision identity, so revision-only dependency drift is no longer treated as unchanged.
- Backend API authentication now fails closed when token configuration is missing, empty, or malformed. Missing or incorrect request credentials are rejected.
- The new root `SECURITY.md` defines hostile repository inputs, the authenticated loopback API boundary, workspace-root assumptions, the non-elevated privilege model, and supported deployment surfaces.

## Compatibility and migration

- Trusted dependency baseline schema 2 includes VCS revision identity. Existing schema-1 baselines cannot prove the stronger identity and must be explicitly recreated or reapproved from a current complete dependency analysis.
- Scans that use repository-controlled ignore rules now report incomplete coverage. Ignored paths and counts remain available, and legitimate noise suppression remains supported with this conservative completeness result.
- The supported authenticated full-stack development command is:

  ```powershell
  cd frontend
  npm.cmd run tauri:dev
  ```

- Direct browser-to-Uvicorn development is unsupported because browser-visible configuration is not an acceptable bearer-token store. Backend-only debugging requires an explicit ephemeral `GLACIAL_DESKTOP_AUTH_TOKEN` and an authenticated client, as documented in the README.

## Packaging scope

Glacial remains a Windows desktop application with a Tauri-supervised loopback backend. Remote and `0.0.0.0` deployments remain unsupported. The Windows NSIS installer remains English-only.
