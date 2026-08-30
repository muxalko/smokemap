# M2 exit evidence

Status: **Demonstrated**

Recorded: 2026-08-30

This record closes **M2 — Viewport map vertical slice** against the ordered work
and exit criteria in [ROADMAP.md](ROADMAP.md). Evidence comes from merged root
`74383bc`, backend `48d1a8a`, and frontend `ad334dd`; those are the exact
revisions pinned by this workspace.

The 2026-08-29 draft closeout was used only as historical gap analysis. It
correctly failed closed while the real cross-application pan and representative
performance evidence were absent. Both gaps were subsequently resolved in the
merged baseline evaluated here.

## Ordered-work evidence

| ROADMAP M2 work item | Decision | Merged implementation and verification evidence |
| --- | --- | --- |
| 1. Define the bounded places GeoJSON contract | **Complete** | Backend `GET /api/v1/places/?bbox=minx,miny,maxx,maxy&zoom=…&categories=…` is public and read-only. It returns a GeoJSON `FeatureCollection` with stable map-only properties. The frontend exposes the same contract to browser code through `/api/smokemap/locations`. |
| 2. Query the authoritative geometry model directly | **Complete** | `ViewportPlaceView` filters approved `Place` rows through their authoritative `Address.location` SRID 4326 point using `address__location__coveredby`. It does not query the legacy denormalized `Location.geom` read model. |
| 3. Validate coordinate count/order, ranges, and maximum viewport area | **Complete** | The parser requires four finite bbox coordinates in `minx,miny,maxx,maxy` order, longitude in `[-180, 180]`, latitude in `[-90, 90]`, strict minimum-before-maximum ordering, and no span above 10 degrees on either axis. It also requires integer zoom `0`–`22` and accepts at most 20 positive category IDs. Parameterized backend tests cover malformed, non-finite, out-of-range, reversed, and excessive bounds. |
| 4. Define result caps and oversized-viewport behavior | **Complete** | More than 500 matching places or more than 512 KiB of encoded GeoJSON fails with HTTP 400 and `viewport_result_limit_exceeded`; invalid or geographically oversized input fails with HTTP 400 and `invalid_viewport`. Results are never silently truncated. |
| 5. Confirm the PostGIS spatial index and query plan | **Complete** | The schema requests a GiST index for `Address.location`. The representative run analyzed the populated tables and captured the endpoint queryset with natural `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`: `enable_seqscan=on`, no planner settings overridden, and a Bitmap Index Scan using `backend_address_location_698a0c50_id`. |
| 6. Add representative backend integration tests | **Complete** | `ViewportPlaceApiTests` covers in-, out-, and on-boundary points; empty and category-filtered results; stable public properties; two-query execution; validation; result and byte caps; indexed geometry; and read-only methods. Ten benchmark tests cover the deterministic grid, the real endpoint and category isolation, natural-plan capture, every fail-closed budget check, canonical evidence, safe cleanup, and refusal outside debug mode. The final backend suite passed 44/44 tests. |
| 7. Create a focused frontend map-data module | **Complete** | `viewport-places.ts` owns query construction, URL generation, GeoJSON validation and normalization, debounce, cancellation, response sequencing, error state, and retry. |
| 8. Refetch settled viewports with cancellation and stale-response protection | **Complete** | Frontend tests cover initial load, settled pan and zoom, rapid move-end coalescing, request abort, and suppression of a late stale response both in the data hook and at the MapLibre source. |
| 9. Render explicit initial, refreshing, empty, error, and success states | **Complete** | `ViewportStatus` and the map tests cover initial loading, non-blocking refresh, retryable error, empty, and success-without-overlay. MapLibre remains mounted and interactive through error, retry, refresh, and empty results. |
| 10. Add an end-to-end pan test across disjoint regions | **Complete** | Root `make test-e2e` uses real Chromium pointer drags against the pinned applications. It proves Region A is returned and opened from its MapLibre marker, reaches a disjoint viewport, proves the live response contains Region B and excludes stale Region A, and opens Region B. Root CI runs this test on pull requests and `development` pushes. |
| 11. Decompose the map only along slice responsibilities | **Complete** | Frontend `ad334dd` reduces `MapComponent` to composition and separates viewport data/status, MapLibre lifecycle, canvas, categories, interactions, search, dialogs, and basemap-style loading. Strict Mode lifecycle tests verify exact attachment and listener cleanup. The final frontend suite passed 48/48 tests. |

## Exit-criterion decision

| M2 exit criterion | Decision | Evidence |
| --- | --- | --- |
| Panning loads only current-viewport places | **Demonstrated** | The real browser test starts with Region A present and Region B absent, performs one or more actual MapLibre pointer drags until the bounds are disjoint, then observes Region B present and Region A absent before opening the Region B marker. Backend integration tests independently prove spatial inclusion, exclusion, and boundary behavior. |
| Stale responses cannot replace newer responses | **Demonstrated** | Superseded requests are aborted and response application is sequence-guarded. Focused frontend tests resolve an older request late and prove it cannot replace the current MapLibre source; rapid settled events are coalesced to the newest viewport. |
| Empty and error states remain interactive | **Demonstrated** | Status overlays do not replace the map, error provides Retry, and the same MapLibre instance remains mounted through error, retry, and empty results. |
| Invalid or oversized bounds fail predictably | **Demonstrated** | Stable HTTP 400 `invalid_viewport` cases cover malformed, reversed, out-of-range, non-finite, and over-10-degree bounds. Stable `viewport_result_limit_exceeded` cases cover the 500-feature and 512 KiB response budgets. |
| The query meets an agreed performance budget | **Demonstrated** | The final combined verification at exact root `74383bc`, backend `48d1a8a`, and frontend `ad334dd` exercised the real endpoint over 20,000 synthetic places with exactly 400 benchmark viewport features. The five measured samples were 140.311, 97.444, 94.976, 97.033, and 88.422 ms, for a maximum of 140.311 ms below the 250 ms server budget. Every sample used 2 database queries, returned 400 benchmark and 0 non-benchmark features, and encoded 164,041 bytes. With `enable_seqscan=on`, the natural analyzed plan used the real `Address.location` GiST index without planner forcing. |

All ordered work and every exit criterion are demonstrated at the exact merged
and pinned revisions. M2 is therefore **Done**.

## Browser and database paths

The cross-application test exercises the deployed local boundaries rather than
joining the application repositories or replacing an application layer with a
mock:

```text
Chromium pointer drag
  → MapLibre settled viewport
  → browser GET /api/smokemap/locations?bbox=…&zoom=…
  → Next.js same-origin rewrite
  → backend GET /api/v1/places/?bbox=…&zoom=…
  → Django ViewportPlaceView
  → Place.address → Address.location PostGIS predicate
  → GeoJSON response through the frontend origin
  → guarded frontend data module
  → current MapLibre source and clickable marker
```

The isolated `smokemap-e2e` Compose project removes host ports, uses an
internal-only network, seeds two namespaced PostGIS fixtures at
`(-77.01215461524441, 38.89630256339336)` and
`(-76.86715461524441, 38.89630256339336)`, and supplies a local blank basemap
and font response. A browser request guard rejects external traffic. Fixture
and container cleanup runs on success or failure; isolated named volumes are
preserved.

The representative performance path uses the same backend route in-process,
including middleware and GeoJSON rendering, and the endpoint's real two ORM
queries:

```text
Django test client GET /api/v1/places/
  → viewport parsing and public read-only view
  → Place filtered by Address.location covered-by bbox and reserved category
  → natural PostgreSQL/PostGIS plan
  → Address.location GiST Bitmap Index Scan
  → related category/address and prefetched tags
  → GeoJSON serialization and encoded-size enforcement
```

The deterministic Washington, DC dataset is a row-major 200×100 grid spanning
`[-77.200, 38.750, -76.800, 38.950]`. The fixed bbox
`[-77.020, 38.830, -76.980, 38.870]` at zoom 13 contains exactly 400 of 20,000
synthetic places. A reserved category isolates measurements from unrelated
rows. Inserts run in a rollback-only transaction; namespaced cleanup refuses
cross-namespace references, and table statistics are refreshed after rollback.

## Final combined verification record

The canonical combined verification at exact merged and pinned root `74383bc`,
backend `48d1a8a`, and frontend `ad334dd` records:

- focused PostGIS benchmark tests: 10/10 passed, including a database state
  with 401 unfiltered in-bounds rows while the category-filtered endpoint
  returned exactly 400 benchmark rows and preserved the unrelated row;
- complete backend suite: 44/44 passed;
- Django system check: passed;
- representative dataset: 20,000 total synthetic places and 400 viewport
  matches;
- warmups and samples: 3 warmups followed by 5 measured samples;
- measured server times: 140.311, 97.444, 94.976, 97.033, and 88.422 ms;
- maximum measured server time: 140.311 ms, below 250 ms;
- every sample: 2 database queries, 400 benchmark features, 0 non-benchmark
  features, and 164,041 encoded bytes, below 512 KiB;
- planner: `enable_seqscan=on`, no harness override, and natural
  `Address.location` GiST usage through a Bitmap Index Scan on
  `backend_address_location_698a0c50_id`;
- benchmark result: PASS with canonical text/JSON evidence generation and no
  benchmark namespace rows retained.

Earlier backend PR #80 strategic-host corroboration recorded samples of
136.382, 93.374, 89.814, 92.006, and 162.338 ms, with a 162.338 ms maximum.
That backend-only run corroborates the performance result, but it is not a
final-pair measurement and is not the canonical timing record for the exact
root/backend/frontend combined verification above.

The merged frontend change records 48/48 tests passing plus TypeScript and
ESLint checks, with only the already documented request-form/PlaceList
warnings. The merged root baseline contains the deterministic real-browser
pan and runs it as the `viewport-pan` CI job. Root CI also checks the exact
submodule revisions and Compose configuration.

CI and host performance evidence have deliberately different roles. Backend
CI runs the complete correctness suite, including the ten benchmark harness
tests for isolation, plan inspection, and fail-closed contracts. Root CI runs the
real cross-application browser pan. The numeric 250 ms exit gate is supported
by the recorded strategic-host reproduction above; it is not presented as a
stable shared-runner timing assertion or as a replacement for the deterministic
CI gates. The numeric 250 ms exit gate is supported by the canonical final
combined verification above; the earlier backend PR #80 strategic-host result
is retained only as corroboration, not as a final-pair measurement.

## M3 gate

M3 remains **Blocked** even though M2 is Done. The
[M1 security policy](M1_SECURITY_POLICY.md) approves authenticated ownership,
denies guest submission, and requires future uploads to be owner-bound and
verified, but deliberately does not approve the complete submission and media
contract required by M3 entry criteria. No authoritative approved policy yet
defines the full state/transition and retention model; coordinate/address,
category, tag, website, description, and uniqueness rules; zero-or-more media
behavior and limits; retry and partial-failure semantics; object visibility and
attachment rules; or abandoned intent/object cleanup. M3 implementation must
not begin until that complete policy is approved.
