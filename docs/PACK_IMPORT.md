# Reviewed local pack import

`tools/pack_import.py` imports folders, ZIP, TAR, TAR.GZ/TGZ, TAR.BZ2 and TAR.XZ into the existing offline library publisher. Imports **add releases to the latest verified generation**. They retain prior titles, releases and default selections; they never write user control overrides. The older `pack_ingest.py` command still rebuilds a complete generation from one folder.

## Preview and import

```sh
python3 tools/pack_import.py preview /path/to/pack.zip /path/to/library \
  --plan /path/to/import-plan.json --default-model 48k
python3 tools/pack_import.py import /path/to/pack.zip /path/to/library \
  --plan /path/to/import-plan.json --default-model 48k
```

The first command writes only the review plan. It does not create or change the library. Keep the source, destination, metadata and options identical between commands. A changed source, sidecar or committed library invalidates the review; generate a fresh preview. A second library check happens inside the publication lock to reject a competing import.

The plan contains candidate paths indexed by SHA-256, duplicate aliases, excluded files, unidentified releases, assumed machine models, and conflicting formats. Edit **only `choices`**:

- Keep a candidate path to include that exact file.
- Set its value to `null` to skip the release.
- Identical bytes under different format extensions default to `null`. Choose the actual format explicitly after checking the files.

Hashes already in the library keep their existing identity, metadata and format. The report lists them under `alreadyPresent`. No new selected releases means no publication. An import cannot delete or reclassify an existing release; those operations need a separate library editor.

Identification uses an optional explicit `--metadata /path/to/metadata.json` sidecar on **both** commands. Each lowercase SHA-256 maps to:

```json
{
  "gameId": "11111111-1111-4111-8111-111111111111",
  "title": "Title identified by the user",
  "details": "Edition and other verified information",
  "model": "48k",
  "source": "Local identification reference"
}
```

Use the same game UUID for verified related releases. The importer preserves existing title/details on conflicting identification and records `metadataConflicts`; it adds the new release under that identity. Unknown files get stable hash-derived UUIDs and filename titles. Reports contain their hashes and assumed models so they can be identified later. An extension or metadata entry does not prove playability or enable automatic launch.

## Publication and recovery

The final generation contains the complete merged catalog, content-addressed media, compiled index and `import-report.json`. Its report records archive provenance/hash, review choices, new imports, already-present files, skipped files, unknowns, exclusions, metadata conflicts and retained release count. Copied media hashes are checked before the A/B pointer commit. Prior files are verified again after staging; an interruption preserves the previous publication. A corrupt latest generation falls back to the other valid slot. Stale locks and incomplete generations require manual inspection, as in the existing publisher.

Archive extraction uses a private temporary directory and streamed copies. Limits: 100,000 members, 256 MiB per expanded file, 2 GiB total expanded content and 2 GiB compressed input. It rejects absolute/traversal/control-character/drive paths, duplicate or case-colliding paths, parent file collisions, links, devices, encrypted ZIPs, invalid CRCs and truncated members. Unsafe archives fail as a unit before publication. ZIP central-directory metadata is parsed by Python's ZIP reader before the member-count check; these limits are resource bounds, not an operating-system sandbox. TAR runs in streaming mode. Output must be outside the input directory.

All regular archive content counts toward limits, including unsupported files. Supported media extensions are those in the catalog compiler; unrelated files and nested archives are not recursively imported. Archives may contain untrusted metadata, artwork or scripts: these are not automatically applied or executed. Provide identification explicitly. Temporary extraction and staging can consume several times the pack size; ensure disk space for those copies plus the new complete generation. Old generations are not garbage-collected.

## Validation and remaining integration

Host tests exercise ZIP and compressed TAR, deterministic previews, explicit format choices/skips, additive imports, metadata grouping/conflicts, hash duplicates, user profile preservation, stale source/library detection, concurrent publication, hostile archives and interruption recovery.

This is a desktop CLI and reusable Python workflow. A [Rust Pocket Sync plugin](POCKET_SYNC_INTEGRATION.md) now publishes reviewed prepared bundles; full in-plugin archive ingestion and installed-host/release distribution remain open. Cover enrichment, actual SD/APF generation selection and real media/launch qualification remain separate work. No ROMs or commercial games are bundled.
