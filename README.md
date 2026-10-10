# SpectrumDeck Pocket Sync plugin

A local-file Rust/WASI plugin for publishing reviewed SpectrumDeck library bundles through Pocket Sync. **Experimental v0.1.0**: the plugin verifies and publishes complete generations; archive scanning and compilation currently run in the included Python tools.

## Install in Pocket Sync

Open Plugins → Add plugin via URL and enter:

```text
https://github.com/alfatreze/spectrumdeck-pocket-sync
```

Pocket Sync fetches `plugin.wasm` and `plugin.json` from the latest release. No network hosts are enabled for the running plugin. Compatibility has been checked against the Pocket Sync 7.0.1 source ABI and exercised in Extism with matching filesystem mounts/messages; loading inside the installed Pocket Sync app and actual card durability remain untested.

## Prepare a library bundle

Requires Python 3.11+; the importer has no third-party Python dependencies.

```sh
python3 tools/pack_import.py preview /path/to/pack.zip \
  /path/to/card/Assets/spectrumdeck/common/library --plan /path/to/review.json
# Review choices in the JSON: candidate path = include, null = skip.
python3 tools/pocketsync_bundle.py /path/to/pack.zip \
  /path/to/card/Assets/spectrumdeck/common/library /path/to/prepared-bundle \
  --plan /path/to/review.json
```

The destination must be the intended card's existing SpectrumDeck library or an exact mirror. Bundle preparation does not publish to the card. Keep model/metadata options identical to preview. ZIP, TAR, gzip, bzip2 and xz archives are bounded and validated; unsafe archives fail before publication.

Place the resulting directory under this plugin's dedicated host folder as `host/bundles/my-pack`. On macOS the expected location is:

```text
~/Library/Application Support/today.neil.pocket-sync/alfatreze-spectrumdeck-pocket-sync/host/bundles/my-pack
```

Confirm the app-data location for your installation. In the plugin choose **Publish prepared bundle**, enter `my-pack`, review the summary and choose Publish. It preserves prior releases and user presets, rejects a changed library and commits only after verification. Safely eject through the OS when complete.

The card namespace `Assets/spectrumdeck/common/library` is experimental desktop staging. The SpectrumDeck FPGA/APF runtime is not yet qualified to load it. No ROMs or commercial games are bundled. Import does not establish game compatibility or automatic launch qualification.

## Build and test

```sh
rustup target add wasm32-wasip1
cargo build --release --target wasm32-wasip1 --locked
cargo test --locked
python3 -m unittest discover -s tests -p 'test_*.py'
# Optional real WASI integration test (Extism requires executable/JIT permissions):
python3 -m pip install extism
python3 tools/test_pocketsync_wasm.py
```

The WASM is `target/wasm32-wasip1/release/spectrumdeck_pocket_plugin.wasm`. Release it as `plugin.wasm` alongside the root `plugin.json`. CI builds, runs native/Python/WASI tests and uploads those two assets as an artifact; release publication is explicit.

See [integration and recovery](docs/POCKET_SYNC_INTEGRATION.md) and [pack import](docs/PACK_IMPORT.md). Next: port the scanner, archives and compiler into the shared Rust library for fully in-plugin ingestion. The rich HTML curator is maintained in the main SpectrumDeck project.
