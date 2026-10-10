use spectrumdeck_pocket_plugin::{ingest, library};
use std::{fs, path::PathBuf};
struct Temp(PathBuf);
impl Temp {
    fn new(name: &str) -> Self {
        let p = std::env::temp_dir().join(format!("sd-native-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&p);
        fs::create_dir_all(p.join("pocket/media")).unwrap();
        fs::create_dir_all(p.join("host")).unwrap();
        Self(fs::canonicalize(p).unwrap())
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
#[test]
fn scan_aliases_conflicts_and_empty() {
    let t = Temp::new("scan");
    let p = t.0.join("pocket");
    for (name, bytes) in [
        ("one.tap", b"one".as_slice()),
        ("copy.tap", b"one"),
        ("wrong.z80", b"one"),
        ("two.sna", b"two"),
        ("empty.tap", b""),
    ] {
        fs::write(p.join("media").join(name), bytes).unwrap();
    }
    let a = ingest::preview(&p, "media", "48k", |_| {}).unwrap();
    let b = ingest::preview(&p, "media", "48k", |_| {}).unwrap();
    assert_eq!(a, b);
    assert_eq!(a.candidates.len(), 1);
    assert_eq!(a.aliases, 2);
    assert_eq!(a.excluded.len(), 4);
}
#[test]
fn native_additive_publication_and_preset() {
    let t = Temp::new("add");
    let p = t.0.join("pocket");
    let h = t.0.join("host");
    fs::write(p.join("media/a.tap"), b"one").unwrap();
    let preview = ingest::preview(&p, "media", "128k", |_| {}).unwrap();
    let name = ingest::prepare(&h, &p, &preview, |_| {}).unwrap();
    let first = library::install(&h, &p, &name, |_| {}).unwrap();
    assert_eq!(first.sequence, 1);
    let root = p.join(library::TARGET);
    fs::write(root.join("preset.json"), b"user-owned").unwrap();
    fs::write(p.join("media/b.z80"), b"two").unwrap();
    let preview = ingest::preview(&p, "media", "48k", |_| {}).unwrap();
    assert_eq!(preview.existing, 1);
    assert_eq!(preview.candidates.len(), 1);
    let name = ingest::prepare(&h, &p, &preview, |_| {}).unwrap();
    let second = library::install(&h, &p, &name, |_| {}).unwrap();
    assert_eq!(second.sequence, 2);
    assert_eq!(fs::read(root.join("preset.json")).unwrap(), b"user-owned");
    assert_eq!(
        ingest::preview(&p, "media", "48k", |_| {})
            .unwrap()
            .candidates
            .len(),
        0
    );
}
#[test]
fn stale_scan_rejected() {
    let t = Temp::new("stale");
    let p = t.0.join("pocket");
    fs::write(p.join("media/a.tap"), b"one").unwrap();
    let a = ingest::preview(&p, "media", "48k", |_| {}).unwrap();
    fs::write(p.join("media/a.tap"), b"changed").unwrap();
    assert!(
        ingest::prepare(&t.0.join("host"), &p, &a, |_| {})
            .unwrap_err()
            .contains("changed")
    );
    assert!(!p.join(library::TARGET).exists());
}
#[test]
fn unsafe_or_generated_sources_rejected() {
    let t = Temp::new("paths");
    let p = t.0.join("pocket");
    for name in ["../media", "/media", library::TARGET] {
        assert!(ingest::preview(&p, name, "48k", |_| {}).is_err());
    }
}
#[cfg(unix)]
#[test]
fn links_excluded() {
    let t = Temp::new("links");
    let p = t.0.join("pocket");
    std::os::unix::fs::symlink("/etc/hosts", p.join("media/link.tap")).unwrap();
    let a = ingest::preview(&p, "media", "48k", |_| {}).unwrap();
    assert!(a.candidates.is_empty());
    assert_eq!(a.excluded.len(), 1);
}

#[test]
fn discovery_filters_and_keeps_sources_unchanged() {
    let t = Temp::new("discover");
    let p = t.0.join("pocket");
    assert!(ingest::discover(&p).unwrap().is_empty());
    for folder in [
        "Assets/zxspectrum/common/nested",
        "Assets/ZX-Spectrum/pack",
        "Assets/speccy",
        "Assets/gameboy",
        "Assets/spectrum-empty",
        "Assets/spectrum-archive",
        library::TARGET,
    ] {
        fs::create_dir_all(p.join(folder)).unwrap();
    }
    for file in [
        "Assets/zxspectrum/common/nested/Game.TAP",
        "Assets/ZX-Spectrum/pack/Game.z80",
        "Assets/speccy/Game.sna",
        "Assets/gameboy/Other.dsk",
        "Assets/spectrumdeck/common/library/Game.tap",
    ] {
        fs::write(p.join(file), b"original").unwrap();
    }
    fs::write(p.join("Assets/spectrum-empty/Empty.tap"), b"").unwrap();
    fs::write(p.join("Assets/spectrum-archive/Pack.zip"), b"archive").unwrap();
    assert_eq!(
        ingest::discover(&p).unwrap(),
        vec!["Assets/ZX-Spectrum", "Assets/speccy", "Assets/zxspectrum"]
    );
    assert_eq!(
        fs::read(p.join("Assets/zxspectrum/common/nested/Game.TAP")).unwrap(),
        b"original"
    );
    assert!(!p.join(library::TARGET).join("publication-a.json").exists());
}
#[cfg(unix)]
#[test]
fn discovery_never_follows_links() {
    let t = Temp::new("discover-links");
    let p = t.0.join("pocket");
    fs::write(p.join("media/Game.tap"), b"original").unwrap();
    fs::create_dir_all(p.join("Assets/spectrum/common")).unwrap();
    std::os::unix::fs::symlink(p.join("media"), p.join("Assets/zxspectrum")).unwrap();
    std::os::unix::fs::symlink(p.join("media"), p.join("Assets/spectrum/common/linked")).unwrap();
    assert!(ingest::discover(&p).unwrap().is_empty());
}
#[test]
fn discovery_depth_is_bounded() {
    let t = Temp::new("discover-depth");
    let p = t.0.join("pocket");
    let mut folder = p.join("Assets/spectrum");
    for _ in 0..34 {
        folder = folder.join("a");
    }
    fs::create_dir_all(folder).unwrap();
    assert!(ingest::discover(&p).unwrap_err().contains("depth limit"));
}

#[test]
fn macos_metadata_is_not_media() {
    let t = Temp::new("metadata");
    let p = t.0.join("pocket");
    fs::create_dir_all(p.join("Assets/spectrum")).unwrap();
    fs::write(p.join("Assets/spectrum/._Game.tap"), b"Finder metadata").unwrap();
    assert!(ingest::discover(&p).unwrap().is_empty());
    let preview = ingest::preview(&p, "Assets/spectrum", "48k", |_| {}).unwrap();
    assert!(preview.candidates.is_empty());
    assert!(preview.excluded[0].contains("metadata sidecar"));
}
