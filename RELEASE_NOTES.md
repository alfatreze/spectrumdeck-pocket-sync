SpectrumDeck Pocket Sync plugin v0.2.0

Create the first library directly in Pocket Sync from loose Spectrum files already on the selected card.

- New Scan card folder → assumed model → preview → Create/update library flow.
- Rust recursive scanner, SHA deduplication, stable UUIDv5 identities and catalog compiler.
- Existing library, release defaults and user presets are preserved.
- Source/library changes invalidate the scan; no new releases means no publication.
- Unsafe/empty/oversized files and conflicting format aliases are excluded and reported.
- Existing reviewed-bundle publishing remains available.

Refresh Plugins in Pocket Sync to update. Run SpectrumDeck Library, choose Scan card folder, and enter the actual card-relative folder containing your games (for example Assets/zxspectrum/common). Choose the model assumption, review exclusions and confirm.

Validation: 22 Python tests, 7 Rust tests and 18 real WASI scenarios pass, including native first publication on an empty card. Rust/Python catalog bytes match across 3 generations and a 10-title Unicode/19-release corpus.

Experimental limitations: native mode handles loose files; archive extraction and detailed metadata/format review remain in the desktop tools. New titles are unidentified and model assumptions do not establish compatibility. Actual SD power-loss durability and SpectrumDeck FPGA/APF loading remain unqualified. User screenshots confirm v0.1.0 installs, starts and reads the publication status inside Pocket Sync 7.0.1; v0.2.0 native imports are validated on disposable Extism mounts.
