use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};
pub type Result<T> = std::result::Result<T, String>;
pub const TARGET: &str = "Assets/spectrumdeck/common/library";
const MAX_JSON: u64 = 16 * 1024 * 1024;
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Record {
    pub version: u32,
    pub sequence: u32,
    pub directory: String,
    pub files: BTreeMap<String, String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Summary {
    pub added: u32,
    pub retained: u32,
    pub unidentified: u32,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Bundle {
    pub version: u32,
    pub target: String,
    #[serde(rename = "expectedPrior")]
    pub expected_prior: serde_json::Value,
    pub publication: Record,
    pub summary: Summary,
}
fn need(condition: bool, message: &str) -> Result<()> {
    if condition {
        Ok(())
    } else {
        Err(message.into())
    }
}
fn io<T>(value: std::io::Result<T>) -> Result<T> {
    value.map_err(|e| e.to_string())
}
pub fn relative(name: &str) -> Result<()> {
    need(
        !name.is_empty()
            && name.len() <= 255
            && !name.contains(['\\', ':'])
            && !name.chars().any(|c| c < ' ' || c == '\u{7f}'),
        "unsafe path",
    )?;
    need(
        name.split('/')
            .all(|p| !p.is_empty() && p != "." && p != ".."),
        "unsafe path",
    )
}
fn safe(root: &Path, name: &str) -> Result<PathBuf> {
    relative(name)?;
    let mut path = root.to_owned();
    // Include ancestors of the root: a pre-existing symlink must not redirect writes.
    let mut probe = PathBuf::new();
    for component in root.components() {
        probe.push(component);
        if let Ok(m) = fs::symlink_metadata(&probe) {
            need(!m.is_symlink(), "symlink root")?;
        }
    }
    for part in name.split('/') {
        path.push(part);
        if let Ok(m) = fs::symlink_metadata(&path) {
            need(!m.is_symlink(), "symlink asset")?;
        }
    }
    Ok(path)
}
fn hash(path: &Path) -> Result<(String, u64)> {
    let mut f = io(File::open(path))?;
    let mut digest = Sha256::new();
    let mut buf = [0u8; 65536];
    let mut size = 0;
    loop {
        let n = io(f.read(&mut buf))?;
        if n == 0 {
            break;
        }
        size += n as u64;
        need(size <= 256 * 1024 * 1024, "file size limit")?;
        digest.update(&buf[..n]);
    }
    Ok((format!("{:x}", digest.finalize()), size))
}
fn json<T: serde::de::DeserializeOwned>(path: &Path) -> Result<T> {
    let file = io(File::open(path))?;
    need(io(file.metadata())?.len() <= MAX_JSON, "JSON size limit")?;
    serde_json::from_reader(file).map_err(|e| e.to_string())
}
fn u32at(data: &[u8], at: usize) -> usize {
    u32::from_le_bytes(data[at..at + 4].try_into().unwrap()) as usize
}
fn u16at(data: &[u8], at: usize) -> usize {
    u16::from_le_bytes(data[at..at + 2].try_into().unwrap()) as usize
}
fn string(data: &[u8], start: usize, offset: usize) -> Result<&str> {
    let at = start.checked_add(offset).ok_or("string overflow")?;
    need(
        at < data.len() && (offset == 0 || data[at - 1] == 0),
        "string boundary",
    )?;
    let tail = &data[at..];
    let end = tail
        .iter()
        .take(4097)
        .position(|b| *b == 0)
        .ok_or("unterminated string")?;
    std::str::from_utf8(&tail[..end]).map_err(|e| e.to_string())
}
fn index(data: &[u8], record: &Record, sizes: &BTreeMap<String, u64>) -> Result<()> {
    need(
        data.len() >= 64 && data.len() <= 64 * 1024 * 1024,
        "index length",
    )?;
    need(
        &data[..8] == b"SDEKIDX1"
            && u16at(data, 8) == 1
            && u16at(data, 10) == 0
            && u32at(data, 12) == 64
            && u32at(data, 16) == data.len()
            && u32at(data, 20) == record.sequence as usize
            && u32at(data, 60) == 0,
        "index header",
    )?;
    let mut header = data[..64].to_vec();
    header[56..60].fill(0);
    need(
        crc32fast::hash(&header) as usize == u32at(data, 56)
            && crc32fast::hash(&data[64..]) as usize == u32at(data, 52),
        "index CRC",
    )?;
    let ng = u32at(data, 24);
    let nr = u32at(data, 28);
    let go = u32at(data, 32);
    let ro = u32at(data, 36);
    let so = u32at(data, 40);
    let ns = u32at(data, 44);
    need(
        ng <= 100000
            && nr <= 1600000
            && u16at(data, 48) == 64
            && u16at(data, 50) == 80
            && go == 64
            && ro == go + ng * 64
            && so == ro + nr * 80
            && so <= data.len()
            && ns == data.len() - so,
        "index sections",
    )?;
    need(
        record
            .files
            .keys()
            .filter(|p| p.starts_with("media/"))
            .count()
            == nr,
        "unreferenced media inventory",
    )?;
    let mut hashes = BTreeSet::new();
    for i in 0..nr {
        let at = ro + i * 80;
        let sha = data[at..at + 32]
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>();
        let path = string(data, so, u32at(data, at + 32))?;
        relative(path)?;
        need(
            hashes.insert(sha.clone())
                && record.files.get(path) == Some(&sha)
                && sizes.get(path) == Some(&(u32at(data, at + 36) as u64)),
            "index media inventory",
        )?;
        need(
            u32at(data, at + 36) > 0
                && u16at(data, at + 40) <= 8
                && (1..=3).contains(&u16at(data, at + 42))
                && data[at + 44..at + 68].iter().all(|b| *b == 0)
                && data[at + 72..at + 80].iter().all(|b| *b == 0),
            "unsupported media fields",
        )?;
        string(data, so, u32at(data, at + 68))?;
    }
    let mut next = 0;
    let mut ids = BTreeSet::new();
    for i in 0..ng {
        let at = go + i * 64;
        need(ids.insert(data[at..at + 16].to_vec()), "duplicate game")?;
        let title = string(data, so, u32at(data, at + 16))?;
        need(!title.is_empty() && title.len() <= 255, "title")?;
        string(data, so, u32at(data, at + 20))?;
        let details = string(data, so, u32at(data, at + 24))?;
        let count = u16at(data, at + 32);
        need(
            u32at(data, at + 28) == next
                && count > 0
                && next + count <= nr
                && u16at(data, at + 44) < count
                && details.len() == u32at(data, at + 52),
            "game releases/details",
        )?;
        next += count;
        need(
            data[at + 34..at + 44].iter().all(|b| *b == 0)
                && u16at(data, at + 46) == 0
                && data[at + 56..at + 64].iter().all(|b| *b == 0),
            "unsupported game/artwork fields",
        )?;
    }
    need(next == nr, "orphan releases")
}
pub fn verify(root: &Path, record: &Record) -> Result<()> {
    need(
        record.version == 1 && record.sequence > 0 && record.files.len() <= 100003,
        "record version/count",
    )?;
    relative(&record.directory)?;
    let parts = record.directory.split('/').collect::<Vec<_>>();
    need(
        parts.len() == 2
            && parts[0] == "generations"
            && parts[1].len() == 43
            && parts[1].as_bytes()[10] == b'-'
            && parts[1].as_bytes()[..10].iter().all(|b| b.is_ascii_digit())
            && parts[1].as_bytes()[11..]
                .iter()
                .all(|b| b.is_ascii_hexdigit()),
        "generation directory",
    )?;
    let base = safe(root, &record.directory)?;
    let mut sizes = BTreeMap::new();
    let mut total = 0u64;
    for (name, sha) in &record.files {
        relative(name)?;
        need(
            sha.len() == 64
                && sha
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
            "digest",
        )?;
        need(
            ["index.bin", "catalog.json", "import-report.json"].contains(&name.as_str())
                || name.starts_with("media/"),
            "unexpected generated file",
        )?;
        let (actual, size) = hash(&safe(&base, name)?)?;
        need(&actual == sha, "digest mismatch")?;
        total += size;
        need(total <= 8 * 1024 * 1024 * 1024, "library size limit")?;
        sizes.insert(name.clone(), size);
    }
    for name in ["index.bin", "catalog.json", "import-report.json"] {
        need(
            record.files.contains_key(name),
            "missing required inventory",
        )?;
    }
    let path = safe(&base, "index.bin")?;
    need(
        io(fs::metadata(&path))?.len() <= 64 * 1024 * 1024,
        "index size",
    )?;
    index(&io(fs::read(path))?, record, &sizes)
}
pub fn latest(root: &Path) -> Result<Option<(String, Record)>> {
    let mut valid = vec![];
    let mut found = false;
    for slot in ["publication-a.json", "publication-b.json"] {
        let path = safe(root, slot)?;
        if path.exists() {
            found = true;
            if let Ok(record) = json::<Record>(&path) {
                if verify(root, &record).is_ok() {
                    valid.push((slot.to_string(), record));
                }
            }
        }
    }
    valid.sort_by_key(|(_, r)| std::cmp::Reverse(r.sequence));
    need(
        !found || !valid.is_empty(),
        "no valid library generation; repair before import",
    )?;
    Ok(valid.into_iter().next())
}
pub fn bundle(host: &Path, name: &str) -> Result<Bundle> {
    need(
        !name.is_empty()
            && name.len() <= 80
            && name
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_'),
        "bundle name: use letters, digits, hyphen or underscore",
    )?;
    let root = safe(host, &format!("bundles/{name}"))?;
    let b: Bundle = json(&safe(&root, "bundle.json")?)?;
    need(
        b.version == 1 && b.target == TARGET && b.summary.added > 0,
        "bundle version/target/summary",
    )?;
    verify(&root, &b.publication)?;
    Ok(b)
}
fn expected(b: &Bundle) -> Result<Option<Record>> {
    if b.expected_prior == serde_json::json!({}) {
        Ok(None)
    } else {
        serde_json::from_value(b.expected_prior.clone())
            .map(Some)
            .map_err(|e| e.to_string())
    }
}
struct Lock(PathBuf);
impl Drop for Lock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}
pub fn install(host: &Path, pocket: &Path, name: &str, log: impl Fn(&str)) -> Result<Record> {
    let b = bundle(host, name)?;
    let source = safe(host, &format!("bundles/{name}"))?;
    let root = safe(pocket, TARGET)?;
    io(fs::create_dir_all(&root))?;
    let lockpath = safe(&root, ".publish.lock")?;
    let mut lock = io(OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&lockpath))?;
    io(lock.write_all(b"Pocket Sync SpectrumDeck\n"))?;
    io(lock.sync_all())?;
    let _guard = Lock(lockpath);
    let prior = latest(&root)?;
    if prior.as_ref().map(|(_, r)| r) == Some(&b.publication) {
        log("This exact bundle is already published.\n");
        return Ok(b.publication);
    }
    need(
        prior.as_ref().map(|(_, r)| r) == expected(&b)?.as_ref(),
        "library changed since bundle preparation; prepare again",
    )?;
    if let Some((_, old)) = &prior {
        for (path, sha) in &old.files {
            if path.starts_with("media/") {
                need(
                    b.publication.files.get(path) == Some(sha),
                    "bundle would remove an existing release",
                )?;
            }
        }
    }
    let sequence = prior
        .as_ref()
        .map_or(Some(1), |(_, r)| r.sequence.checked_add(1));
    need(sequence == Some(b.publication.sequence), "bundle sequence")?;
    let destination = safe(&root, &b.publication.directory)?;
    io(fs::create_dir_all(&destination))?;
    let sourcebase = safe(&source, &b.publication.directory)?;
    for (name, sha) in &b.publication.files {
        log(&format!("Copying {name}\n"));
        let dst = safe(&destination, name)?;
        if dst.exists() {
            need(
                hash(&dst)?.0 == *sha,
                "conflicting incomplete generation; inspect before retry",
            )?;
            continue;
        }
        io(fs::create_dir_all(dst.parent().unwrap()))?;
        let mut input = io(File::open(safe(&sourcebase, name)?))?;
        let mut output = io(OpenOptions::new().write(true).create_new(true).open(&dst))?;
        io(std::io::copy(&mut input, &mut output))?;
        io(output.sync_all())?;
    }
    log("Verifying copied generation before publication.\n");
    verify(&root, &b.publication)?;
    let slot = if prior.as_ref().map(|(s, _)| s.as_str()) == Some("publication-a.json") {
        "publication-b.json"
    } else {
        "publication-a.json"
    };
    let temporary = safe(&root, ".spectrumdeck-publication.tmp")?;
    let mut file = io(OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary))?;
    io(file.write_all(&serde_json::to_vec_pretty(&b.publication).map_err(|e| e.to_string())?))?;
    io(file.sync_all())?;
    drop(file);
    io(fs::rename(&temporary, safe(&root, slot)?))?;
    need(
        latest(&root)?.as_ref().map(|(_, r)| r) == Some(&b.publication),
        "commit readback failed; inspect publication",
    )?;
    log("Publication verified. Safely eject the Pocket card in the host OS.\n");
    Ok(b.publication)
}
