# Decision: read the admitted CEX files directly

The original boundary required a permanent Nautilus catalog, but the delivered consumer
checker used and removed a temporary catalog. The complete source tables already exist.
HT-004 supplies the missing consumer: pinned publication/manifests and read-only streamed
Parquet access, projecting native Bar/custom events in memory. This replaces the physical
second-catalog requirement for data access and avoids duplicating the release.

The owner authorizes delivery before unrelated CMB full-suite closure; unfinished checks
remain unfinished. This permits data access, not a scored strategy or claimed profitability.
Unknown availability, original units and missing values remain visible. Explicit event-time
playback is an assumption, not historical source-availability evidence. Existing strict
research semantic types remain unchanged; a consumer may use the original released fields.
