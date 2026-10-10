# SpectrumDeck desktop library companion

## Decision and evidence

The existing pack-import prototype supplies the visual baseline: paper and ink, Tamzen body text, Departure Mono branding, Choose → Review → Import, release list and summary. Pocket Sync 7.0.1's PluginMessage enum only provides Choice, Text and Exit; its PluginWindow renders a fixed large log with buttons or a text field. The open_url host function opens a URL externally. It cannot start a local companion process, embed custom HTML, provide a native folder picker or return rich UI edits to WASI. The prototype currently simulates publication.

A graphical companion must therefore execute outside the stock plugin window, or require an upstream Pocket Sync host extension. A custom Pocket Sync fork would introduce installation/update maintenance disproportionate to this feature. Recommended first implementation: reuse the existing layout in a local desktop companion with a real importer backend; retain the stock plugin as an optional card-only utility. A launchable packaged application and URL handler are a subsequent integration step; a browser page alone is insufficient to run the importer.

## Functional model

Actor: person managing their Pocket card and local game packs. Objects: selected card, source folder/archive, verified existing library, preview bound to source and base generation, per-release choices, import report. Source originals and controls remain user-owned. The existing Python pack importer owns extraction bounds, exact hash deduplication, stale review checks, exclusive publication lock and generation verification. UI must invoke it rather than duplicate its rules.

Success: user selects a card and a local pack, sees exact additions and exclusions, resolves or skips ambiguous formats, and explicitly imports a verified generation without entering card-relative paths or using CLI JSON. Import alone does not establish automatic launch compatibility. Online sources, covers, metadata editing and control editors are distinct later integrations, not promised by the import screen.

## Information architecture and flow

1. Choose: card selection, existing-library status, source folder or archive picker, model assumption and Preview pack action. A blank card says "No Spectrum library yet. Choose a local pack to create one." It does not ask users to supply a prebuilt library.
2. Review: selected card/source labels; searchable release list; All / New / Already present / Decisions / Unidentified filters; per-release Keep, Skip and candidate format choice; additions, duplicates and exclusions summary. Existing titles stay read-only. Technical hashes and excluded paths live under expandable details.
3. Import: action "Add N releases" available only for a current preview with actual additions and no unresolved decisions. Real operation status, no invented percentage or fake phase animation. Prevent double submission and navigation changes while writing.
4. Result: verified generation, actual additions/retained/skipped counts and report download. User can import another pack. Explain safe ejection; do not claim hardware readiness.

Card selection is distinct from input selection; neither may be silently inferred from a drive name. Automatically enumerate Pocket-shaped mounted volumes as suggestions, allow browsing to another folder and keep source paths inside explicitly selected roots. Source selection can be anywhere on the Mac, including card media, but generated-library input is rejected. Archives use the existing bounded Python extractor.

## State and recovery contract

| State | Allowed action | Result |
| --- | --- | --- |
| No card | Select card | Read-only inspection; no directory creation |
| Empty library | Choose pack | First-use guidance, no path entry |
| Choosing | Select folder/archive and model | Preview disabled until card/source are selected |
| Previewing | Wait | Native/backend operation; no publication |
| Reviewing | Keep/skip/resolve, filter | Recompute additions against verified base hashes |
| No additions | Choose another pack or revise selections | Import disabled with explanation |
| Stale review | Preview again | Keep old review visible; require fresh source/base verification |
| Invalid archive | Choose another pack | Explain actionable error; no publication |
| Importing | Wait | Disable repeat import and source/card changes |
| Import error | Inspect library / preview again | Re-read verified publication before describing outcome |
| Complete | Save report / import another | Show actual committed generation |

## Accessibility and validation

Target WCAG 2.2 AA, without claiming conformance before testing. Preserve native labels, buttons and selects, 44 px primary targets, visible keyboard focus, live status, focus movement to new phase headings, semantic release headings and full text status. Paper/ink uses the existing high-contrast palette; status must not depend on color. Use bitmap-friendly font sizes and the established 390 px reflow. No mandatory timing, drag-only interaction or animation. Test keyboard-only card/source/review/import flow, screen-reader announcements, 200% zoom, reduced motion and failures with retained decisions.

Backend tests must use disposable cards: first publication, additive archive/folder imports, duplicate-only input, unresolved format, stale source/base, malformed choices, unsafe archives, concurrent import, preset preservation and failure/readback. Browser tests should exercise the real backend using temporary sources rather than simulate commit. Actual hardware loading and FAT power-loss durability stay separate qualification gates.

## Implementation boundary

A local-only HTTP bridge is suitable for the first runnable development companion: bind 127.0.0.1 on an ephemeral port, require an unguessable session token for API operations, reject cross-origin requests and Host rebinding, restrict static files to the companion/font asset allowlist, limit request sizes and serialize filesystem mutations. Native pickers should grant explicit card/source roots; browser requests may not nominate arbitrary filesystem paths. Importer results and errors remain authoritative. Package the launcher only after the interaction and importer integration pass their checks.
