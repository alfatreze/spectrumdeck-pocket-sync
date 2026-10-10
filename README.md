# SpectrumDeck Pocket Sync plugin

![SpectrumDeck plugin cover](assets/plugin-icon.png)

Two ways to prepare your SpectrumDeck library:

- **Desktop companion**: the graphical Choose → Review → Import layout, native card/folder/archive pickers, searchable releases, keep/skip and format decisions, and real local imports. [Run the companion](docs/DESKTOP_COMPANION.md).
- **Pocket Sync plugin v0.3.0**: a guided card-folder importer with folder browsing, clear empty-card help and advanced bundle tools. Stock Pocket Sync supplies the plugin window; its layout cannot match the graphical companion.

Both retain existing games and presets and use verified additive generations. Neither downloads games or establishes Pocket launch compatibility. The earlier HTML prototype has been replaced by a real backend in the companion.

## Install in Pocket Sync

Open Plugins → Add plugin via URL and enter:

```text
https://github.com/alfatreze/spectrumdeck-pocket-sync
```

Pocket Sync fetches `plugin.wasm` and `plugin.json` from the latest release. No network hosts are enabled for the running plugin. Compatibility has been checked against the Pocket Sync 7.0.1 source ABI and exercised in Extism with matching filesystem mounts/messages; installation and earlier menus have been confirmed inside Pocket Sync; this update’s folder chooser has been tested in Extism. Actual card publication and durability remain unverified.

## Add games in Pocket Sync

1. Refresh Plugins to install v0.3.0 and reopen SpectrumDeck Library.
2. Choose **Add games from card** and select a detected Spectrum folder. **Browse card folders** navigates folders with buttons; choose **Use this folder** when you reach your games.
3. Choose the assumed model, review the new/duplicate/excluded counts and choose **Add games**. Only this final action publishes.

On an empty card the plugin explains where games come from and offers the desktop companion. Use the companion for folders and archives on your Mac; it has a visual release-by-release review. Native plugin input is loose TAP/TZX/Z80/SNA/DSK/TRD/VHD/SZX media only. Conflicting extensions are excluded for desktop review, not guessed. Unknown titles use filenames and remain unqualified. Archives still use the companion or desktop bundle tools.

**View library** shows the verified generation. **Advanced options** contains manual card-relative paths, prepared bundles and detailed inspection. **Desktop companion & help** opens the latest release download page; it does not start a local process.

Discovery checks Spectrum-named Assets roots with 100,000-entry/depth-32 bounds. Folder browsing shows up to 100 child folders per step. Import bounds are 100,000 entries, depth 32, 256 MiB per media file and 2 GiB scanned media. Generated libraries, symlinks and macOS metadata sidecars are excluded. Native sources are rechecked before publication. Actual installed-app walkthrough and card durability still require verification.

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
cargo build --example compile --locked
python3 tools/test_catalog_parity.py
python3 -m unittest discover -s tests -p 'test_*.py'
# Optional real WASI integration test (Extism requires executable/JIT permissions):
python3 -m pip install extism
python3 tools/test_pocketsync_wasm.py
```

The WASM is `target/wasm32-wasip1/release/spectrumdeck_pocket_plugin.wasm`. Release it as `plugin.wasm` alongside the root `plugin.json`. CI builds, runs native/Python/WASI tests and uploads those two assets as an artifact; release publication is explicit.

See [integration and recovery](docs/POCKET_SYNC_INTEGRATION.md) and [pack import](docs/PACK_IMPORT.md). Next: native bounded archive extraction, metadata sidecars and per-release decision menus. The rich HTML curator is maintained in the main SpectrumDeck project.
