# glib 0.18.5 soundness backport provenance

- Package: `glib 0.18.5`
- Source: the checksum-verified crates.io archive from Cargo's standard registry cache
- Verified crates.io SHA-256: `233daaf6e83ae6a12a52055f568f9d7cf4671dabb78ff9560ab6da230ce00ee5`
- Recorded crate VCS commit: `42b9caf98e03ded086362d9653ca58fe94dc8658`
- Advisories: `GHSA-wrw7-89jp-8q8g`, `RUSTSEC-2024-0429`
- Upstream fix: gtk-rs/gtk-rs-core PR #1343
- Local modification: in `VariantStrIter::impl_get`, make the `p` pointer binding mutable and pass `&mut p` to `g_variant_get_child`
- Integrity finding: the cached archive matched the official crates.io checksum, and the provenance review found no evidence of publisher compromise or local tampering
- Retirement condition: remove this override once Tauri uses an officially patched glib release line
- Shipping scope: Glacial currently ships Windows x64 only

`GHSA-wrw7-89jp-8q8g.patch` records the complete two-line source modification applied to the verified upstream package.
