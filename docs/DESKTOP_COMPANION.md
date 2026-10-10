# SpectrumDeck desktop companion

A working local library importer using the SpectrumDeck desktop design. It imports folders and ZIP/TAR archives, shows a searchable release list, lets you keep/skip releases or resolve conflicting formats, and writes a verified additive library while preserving controls.

## Run on macOS

Requires Python 3.11 or newer (`python3 --version`). No Python packages are required. Download SpectrumDeck-Companion-macOS.zip from the latest plugin repository release, unzip it and open **Start SpectrumDeck Companion.command**. Keep its Terminal window open while importing. If macOS prevents opening the downloaded script, review the source and open it from Terminal with `zsh "Start SpectrumDeck Companion.command"` from the extracted folder. This is a development launcher, not a signed standalone macOS app.

The launcher opens a local browser page. Choose the Pocket card from detected volumes, or Browse for card to select its root. Choose a local game folder or ZIP/TAR archive, select an assumed model and Preview pack. Review additions, duplicates, excluded files and format decisions. Choose **Add N releases** when ready. No JSON editing or manually typed filesystem paths are needed.

The import is real. Sources are preserved and media is copied into `Assets/spectrumdeck/common/library` on the chosen card, using the same reviewed importer and A/B generations as the plugin. The backend rechecks sources and the base generation before publication. Safely eject through macOS after success. Canceling a picker makes no selection change. If an import reports an error, it rereads the verified generation; preview again before retrying. Keep the card connected until completion.

The browser UI runs outside Pocket Sync. The Pocket Sync plugin's **Desktop companion & help** opens the download page; stock Pocket Sync cannot start this Python process or embed this UI. The plugin remains a guided card-folder importer, with folder browsing and its prepared-bundle tools under Advanced options.

## Current limits

No online game downloads, cover/metadata editing, or control editor integration yet. The graphical companion was checked using injected picker adapters and disposable cards; native picker interaction still needs a user walkthrough. The generated library is experimental staging: Pocket FPGA runtime consumption and FAT power-loss durability remain unqualified.

Folder sources: at most 100,000 entries, depth 32, 256 MiB per media file, 2 GiB media total. The existing archive extractor validates and bounds ZIP/TAR including supported compression. Symlinks, unsafe paths and macOS metadata sidecars are excluded/rejected. Local API binds only to 127.0.0.1, uses an ephemeral port and session token, rejects cross-origin/rebound Host requests and serializes operations. Browser clients cannot nominate arbitrary paths; selection is through native pickers or detected card IDs.
