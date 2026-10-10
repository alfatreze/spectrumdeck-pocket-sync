# Pocket Sync integration — first working boundary

## Host contract and installed app

Inspected the locally installed `/Applications/Pocket Sync.app`: bundle identifier `today.neil.pocket-sync`, version **7.0.1** (updated from the initially inspected 6.4.0). The app opens normally and currently offers “Connect to Pocket / SD Card”. No real card was selected or modified.

Upstream source inspected at Pocket Sync commit `dabad6641910e097580aa24e15e06c3108dff7a2` and reference plugin commit `39dae308f7db00d77a4314fc76ad5d8d5b09b81b`:

- [Pocket Sync host implementation](https://github.com/neil-morrison44/pocket-sync/blob/dabad6641910e097580aa24e15e06c3108dff7a2/src-tauri/src/commands/plugins.rs)
- [Reference plugin](https://github.com/openfpga-library/pocket-plugin/tree/39dae308f7db00d77a4314fc76ad5d8d5b09b81b/plugin)

Pocket Sync loads `plugin.wasm` with WASI, maps the card as `pocket` and a dedicated desktop folder as `host`, and exports `print_msg` / `open_url`. It presents `Choice`, `Text`, and `Exit` messages. Answers are `{"Answer":{"name":"...","value":"..."}}`. Actual Serde unit-variant cancellation is the JSON string `"Kill"` (the reference README's map illustration differs). Normal distribution is a GitHub release containing exactly named `plugin.wasm` and `plugin.json`; the plugin list comes from configured repository URLs. Copying files into an app-data directory alone does **not** register a plugin in the stock UI.

Rechecked after the app update: the plugin host implementation at the `v7.0.1` tag (`c8a3875f853750eb3f51d77a9a9501f98f5a4ef2`) is unchanged from the initially inspected source. The existing Rust/WASI integration therefore needs no host-ABI changes for 7.0.1.

These are source-level host observations. Installed-app runtime compatibility has not been demonstrated: its UI has been inspected, while plugin execution used Extism 1.41.0 with the same mounts/function signatures/messages. Do not modify the signed application bundle to add the plugin.

## Implemented Rust plugin

The repository root compiles to a genuine Rust WASI/Extism plugin. It provides:

1. Inspect the current verified SpectrumDeck generation.
2. Enter a prepared bundle's name within `host/bundles`.
3. Verify bundle inventory, SHA-256 digests, binary index header/CRC/sections, strings, media references, game ownership and supported fields.
4. Show added/retained/unidentified counts and an explicit publication choice.
5. Lock the target, reject a changed base library, copy an immutable generation, flush individual files, reverify, atomically replace the older A/B pointer, and verify readback.
6. Preserve files outside generated directories, including user presets. Reject any bundle removing prior media. Repeating the exact already-published bundle is idempotent.

No network hosts are permitted by the manifest. No downloads, ROM bundling or automatic qualification. This version accepts generated catalogs without artwork/recipe/control pointers; those features require their own versioned integration. Bounds: 16 MiB JSON, 64 MiB index, 256 MiB per generated file, 100,003 inventory entries, 8 GiB total library.

The namespace is `Assets/spectrumdeck/common/library` on the selected card. This is an **experimental desktop staging namespace**, not a claim that the FPGA/APF runtime already reads these files. Actual core slot/layout integration remains open.

## Prepare and publish

The first integration retains the Python archive scanner and compiler, using a reviewed bundle to cross the WASI boundary. The plugin cannot spawn Python or access arbitrary Mac paths.

```sh
# The existing catalog folder is on the intended card, or is an exact mirror.
python3 tools/pack_import.py preview /path/to/pack.zip \
  /path/to/card/Assets/spectrumdeck/common/library --plan /path/to/review.json
# Review/edit choices with the prototype or directly in JSON.
python3 tools/pocketsync_bundle.py /path/to/pack.zip \
  /path/to/card/Assets/spectrumdeck/common/library /path/to/prepared-bundle \
  --plan /path/to/review.json
```

Pass the same `--metadata`, `--default-model` and `--allow-fixtures` options used for preview. Bundle preparation copies the base generation into a private mirror and applies the reviewed additive import there. It does not publish to the card. The bundle includes the complete resulting generation and an exact expected-prior record. A changed source/card invalidates the review.

After installation through a real plugin release, place the prepared directory under the plugin's dedicated host directory as `host/bundles/my-pack`. On macOS the host's current app-data root is normally `~/Library/Application Support/today.neil.pocket-sync/<owner>-<repo>/host`; confirm the actual path in the installed host before placing files. Run SpectrumDeck Library → Publish prepared bundle → enter `my-pack` → review → Publish. No arbitrary folder picker exists in this upstream plugin ABI.

Build the release assets locally:

```sh
rustup target add wasm32-wasip1
cargo build \
  --release --target wasm32-wasip1 --locked
```

A packaged copy is in `dist/plugin.wasm` and `dist/plugin.json`. Release assets are distributed from this repository. The installed app has not been reconfigured. The plugin can already be exercised through an Extism host or the upstream demo host with the two documented preopens.

## Cancellation, recovery and durability

Cancel before publication writes nothing. Normal Kill between prompts exits. Pocket Sync also has a force-cancel handle: cancellation during a long call can leave a lock, partial immutable generation or temporary pointer. Inspect the latest valid generation before retry. Do not blindly remove `.publish.lock` while another writer is active. Completed copied files can be reused if their hashes match; conflicting partial files stop the import. A stale temporary publication file also stops commit and requires inspection. Never garbage-collect a valid generation as part of recovery.

The plugin uses individual file `sync_all`, a same-directory pointer rename and verified A/B readback. It does not fsync directories through WASI or prove SD/FAT power-loss durability. A force cancellation after commit may leave the new valid generation published despite a failure notification; inspection/idempotent retry resolves that ambiguity. Safely eject the card through the OS. Real card interruption and APF selection tests remain required.

## Validation and next port

- Standalone Python suite: 22 tests pass, including bundle preparation, preservation and stale input. The parent SpectrumDeck host suite also passed 88 tests.
- Rust tests: path/Unicode safety and strict wire fields.
- Real compiled WASI plugin: 12 scenarios pass under Extism with disposable `host`/`pocket` mounts: messages/mounts, cancellation, unsafe name, actual publication, idempotence, corrupt source, additive generation, preset preservation, stale bundle, inspection, Kill and structural index rejection.
- Hashes/logs: `validation/`.

**Rust is the preferred language for a fully in-plugin importer.** Share one Rust library between a native CLI and `wasm32-wasip1`; keep Python as a migration oracle until binary outputs and review fingerprints match. Port in this order: catalog encoder/decoder and deterministic UUID/sort rules; scanner and exact-hash metadata; bounded ZIP/TAR extraction; reviewed-choice state machine; additive compilation and publication. Test native and WASI on identical hostile/fixture corpora. No shell execution, browser UI embedding or generic Mac filesystem mount is needed. Packs still need to be placed in the plugin's host folder unless Pocket Sync adds a file-picker capability. The existing HTML prototype can remain a separate richer curator using the same review objects.

Provider search/download and cover enrichment remain separate features. A plugin language port does not grant permission to download a particular release.
