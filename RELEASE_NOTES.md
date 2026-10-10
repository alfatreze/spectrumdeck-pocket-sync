SpectrumDeck Pocket Sync plugin v0.1.0

Initial experimental release for reviewed local library bundles.

- Rust WASI plugin exposes Pocket Sync's menu/prompt ABI.
- Verifies SHA-256 inventories, binary index CRC and structural/media bounds.
- Publishes additive immutable generations through verified A/B pointers.
- Preserves existing releases and user control presets; rejects stale bundles.
- Includes Python archive preview and bundle preparation tools.

Validation: 22 standalone Python tests, 2 Rust tests and 12 actual WASI scenarios pass. Host ABI checked against Pocket Sync 7.0.1. Loading in the installed app and real-card power-loss durability remain untested. The card namespace is experimental; FPGA/APF loading and full Rust ingestion remain future work.

Install in Pocket Sync using the repository URL. Both required assets are supplied: plugin.wasm and plugin.json.
