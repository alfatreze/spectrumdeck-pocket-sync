//! Native card-folder ingestion. Archive extraction remains the desktop tool's job.
use crate::library::{self, Bundle, Record, Result, Summary};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};
use unicode_casefold::UnicodeCaseFold;
use unicode_normalization::{UnicodeNormalization, char::is_combining_mark};
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Release {
    pub path: String,
    pub format: String,
    pub model: String,
    pub label: String,
    pub sha256: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Game {
    pub id: String,
    pub title: String,
    pub details: String,
    pub releases: Vec<Release>,
    #[serde(default)]
    pub default_release: u16,
    #[serde(default)]
    pub collection_mask: u32,
}
#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Catalog {
    pub schema_version: u32,
    pub generation: u32,
    pub games: Vec<Game>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Candidate {
    pub path: String,
    pub sha256: String,
    pub format: String,
    pub bytes: u64,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Preview {
    pub source: String,
    pub model: String,
    pub prior: Option<Record>,
    pub candidates: Vec<Candidate>,
    pub excluded: Vec<String>,
    pub aliases: usize,
    pub existing: usize,
    pub fingerprint: String,
}
fn error<T>(r: std::io::Result<T>) -> Result<T> {
    r.map_err(|e| e.to_string())
}
fn need(c: bool, m: &str) -> Result<()> {
    if c { Ok(()) } else { Err(m.into()) }
}
fn model(s: &str) -> Result<u16> {
    match s {
        "48k" => Ok(1),
        "128k" => Ok(2),
        "pentagon" => Ok(3),
        _ => Err("unknown model".into()),
    }
}
fn format(s: &str) -> Result<u16> {
    match s {
        "tap" => Ok(1),
        "tzx" => Ok(2),
        "z80" => Ok(3),
        "sna" => Ok(4),
        "dsk" => Ok(5),
        "trd" => Ok(6),
        "vhd" => Ok(7),
        "szx" => Ok(8),
        _ => Err("unknown format".into()),
    }
}
fn alias(s: &str) -> String {
    s.nfkd()
        .filter(|c| !is_combining_mark(*c))
        .case_fold()
        .collect()
}
pub fn preview(pocket: &Path, source: &str, machine: &str, log: impl Fn(&str)) -> Result<Preview> {
    model(machine)?;
    library::relative(source)?;
    need(
        !(source == library::TARGET || source.starts_with(&format!("{}/", library::TARGET))),
        "choose original media, not generated library",
    )?;
    let start = library::safe(pocket, source)?;
    need(
        start.is_dir(),
        "source folder does not exist on the selected card",
    )?;
    let prior = library::latest(&pocket.join(library::TARGET))?.map(|(_, r)| r);
    let known = prior
        .as_ref()
        .map(|r| {
            r.files
                .iter()
                .filter(|(p, _)| p.starts_with("media/"))
                .map(|(_, h)| h.clone())
                .collect::<BTreeSet<_>>()
        })
        .unwrap_or_default();
    let mut all = vec![];
    let mut excluded = vec![];
    let mut count = 0;
    let mut total = 0;
    fn walk(
        pocket: &Path,
        folder: &Path,
        all: &mut Vec<Candidate>,
        excluded: &mut Vec<String>,
        count: &mut usize,
        total: &mut u64,
        depth: usize,
        log: &impl Fn(&str),
    ) -> Result<()> {
        need(depth <= 32, "folder depth limit")?;
        let mut paths = error(fs::read_dir(folder))?
            .take(100001)
            .map(|e| e.map(|e| e.path()))
            .collect::<std::io::Result<Vec<_>>>()
            .map_err(|e| e.to_string())?;
        paths.sort();
        for path in paths {
            *count += 1;
            need(*count <= 100000, "folder entry limit")?;
            let relative = path
                .strip_prefix(pocket)
                .map_err(|e| e.to_string())?
                .to_str()
                .ok_or("non-UTF8 filename")?
                .to_string();
            if relative == library::TARGET || relative.starts_with(&format!("{}/", library::TARGET))
            {
                continue;
            }
            let meta = error(fs::symlink_metadata(&path))?;
            if meta.is_symlink() {
                excluded.push(format!("{relative}: symlink"));
                continue;
            }
            if meta.is_dir() {
                library::relative(&relative)?;
                walk(pocket, &path, all, excluded, count, total, depth + 1, log)?;
                continue;
            }
            if !meta.is_file() {
                excluded.push(format!("{relative}: special file"));
                continue;
            }
            let fmt = path
                .extension()
                .and_then(|s| s.to_str())
                .unwrap_or("")
                .to_lowercase();
            if format(&fmt).is_err() {
                continue;
            }
            if let Err(e) = library::relative(&relative) {
                excluded.push(format!("{relative}: {e}"));
                continue;
            }
            if meta.len() == 0 || meta.len() > 256 * 1024 * 1024 {
                excluded.push(format!("{relative}: empty or exceeds 256 MiB"));
                continue;
            }
            *total += meta.len();
            need(*total <= 2 * 1024 * 1024 * 1024, "scan media exceeds 2 GiB")?;
            log(&format!("Checking {relative}\n"));
            let (sha, size) = library::hash(&library::safe(pocket, &relative)?)?;
            all.push(Candidate {
                path: relative,
                format: fmt,
                sha256: sha,
                bytes: size,
            });
        }
        Ok(())
    }
    walk(
        pocket,
        &start,
        &mut all,
        &mut excluded,
        &mut count,
        &mut total,
        0,
        &log,
    )?;
    let mut hashes: BTreeMap<String, Vec<Candidate>> = BTreeMap::new();
    for item in all {
        hashes.entry(item.sha256.clone()).or_default().push(item);
    }
    let mut candidates = vec![];
    let mut aliases = 0;
    let mut existing = 0;
    for (sha, items) in hashes {
        aliases += items.len() - 1;
        if known.contains(&sha) {
            existing += 1;
            continue;
        }
        if items.iter().any(|i| i.format != items[0].format) {
            for i in items {
                excluded.push(format!(
                    "{}: same bytes have conflicting extensions; use reviewed desktop import",
                    i.path
                ));
            }
            continue;
        }
        candidates.push(items[0].clone());
    }
    let mut p = Preview {
        source: source.into(),
        model: machine.into(),
        prior,
        candidates,
        excluded,
        aliases,
        existing,
        fingerprint: String::new(),
    };
    p.fingerprint = format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&p).map_err(|e| e.to_string())?)
    );
    Ok(p)
}
fn put32(b: &mut [u8], at: usize, v: usize) {
    b[at..at + 4].copy_from_slice(&(v as u32).to_le_bytes());
}
fn put16(b: &mut [u8], at: usize, v: u16) {
    b[at..at + 2].copy_from_slice(&v.to_le_bytes());
}
pub fn compile(catalog: &Catalog, sizes: &BTreeMap<String, u64>) -> Result<Vec<u8>> {
    need(
        catalog.schema_version == 1 && catalog.generation > 0 && catalog.games.len() <= 100000,
        "catalog schema/generation/count",
    )?;
    let mut strings = vec![];
    let mut interned = BTreeMap::new();
    let mut intern = |s: &str| -> Result<usize> {
        need(!s.contains('\0') && s.len() <= 4096, "invalid text")?;
        if let Some(i) = interned.get(s) {
            return Ok(*i);
        }
        let offset = strings.len();
        strings.extend_from_slice(s.as_bytes());
        strings.push(0);
        interned.insert(s.to_string(), offset);
        Ok(offset)
    };
    let mut games = vec![];
    let mut releases = vec![];
    let mut ids = BTreeSet::new();
    let mut hashes = BTreeSet::new();
    let mut next = 0;
    for game in &catalog.games {
        let id = uuid::Uuid::parse_str(&game.id).map_err(|e| e.to_string())?;
        need(
            ids.insert(id)
                && !game.title.is_empty()
                && game.title.len() <= 255
                && !game.releases.is_empty()
                && game.releases.len() <= 65535
                && (game.default_release as usize) < game.releases.len(),
            "invalid game",
        )?;
        for release in &game.releases {
            library::relative(&release.path)?;
            need(
                release.sha256.len() == 64
                    && release
                        .sha256
                        .bytes()
                        .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
                    && hashes.insert(release.sha256.clone()),
                "invalid/duplicate digest",
            )?;
            let bytes = *sizes.get(&release.path).ok_or("missing media size")?;
            need(bytes > 0 && bytes <= u32::MAX as u64, "media size")?;
            let mut r = [0u8; 80];
            for i in 0..32 {
                r[i] = u8::from_str_radix(&release.sha256[2 * i..2 * i + 2], 16)
                    .map_err(|e| e.to_string())?;
            }
            put32(&mut r, 32, intern(&release.path)?);
            put32(&mut r, 36, bytes as usize);
            put16(&mut r, 40, format(&release.format)?);
            put16(&mut r, 42, model(&release.model)?);
            put32(&mut r, 68, intern(&release.label)?);
            releases.extend_from_slice(&r);
        }
        let mut g = [0u8; 64];
        g[..16].copy_from_slice(id.as_bytes());
        put32(&mut g, 16, intern(&game.title)?);
        put32(&mut g, 20, intern(&alias(&game.title))?);
        put32(&mut g, 24, intern(&game.details)?);
        put32(&mut g, 28, next);
        put16(&mut g, 32, game.releases.len() as u16);
        put16(&mut g, 44, game.default_release);
        put32(&mut g, 48, game.collection_mask as usize);
        put32(&mut g, 52, game.details.len());
        games.extend_from_slice(&g);
        next += game.releases.len();
    }
    drop(intern);
    let total = 64 + games.len() + releases.len() + strings.len();
    need(total <= 64 * 1024 * 1024, "catalog size")?;
    let mut data = vec![0u8; 64];
    data[..8].copy_from_slice(b"SDEKIDX1");
    put16(&mut data, 8, 1);
    put32(&mut data, 12, 64);
    put32(&mut data, 16, total);
    put32(&mut data, 20, catalog.generation as usize);
    put32(&mut data, 24, catalog.games.len());
    put32(&mut data, 28, next);
    put32(&mut data, 32, 64);
    put32(&mut data, 36, 64 + games.len());
    put32(&mut data, 40, 64 + games.len() + releases.len());
    put32(&mut data, 44, strings.len());
    put16(&mut data, 48, 64);
    put16(&mut data, 50, 80);
    data.extend(games);
    data.extend(releases);
    data.extend(strings);
    let crc = crc32fast::hash(&data[64..]);
    put32(&mut data, 52, crc as usize);
    let crc = crc32fast::hash(&data[..64]);
    put32(&mut data, 56, crc as usize);
    Ok(data)
}
pub fn prepare(host: &Path, pocket: &Path, review: &Preview, log: impl Fn(&str)) -> Result<String> {
    let current = preview(pocket, &review.source, &review.model, &log)?;
    need(&current == review, "source or library changed; scan again")?;
    need(
        !review.candidates.is_empty(),
        "no new unambiguous releases; library unchanged",
    )?;
    let seq = review
        .prior
        .as_ref()
        .map_or(Some(1), |r| r.sequence.checked_add(1))
        .ok_or("generation exhausted")?;
    let name = format!("scan-{}", &review.fingerprint[..24]);
    let root = library::safe(host, &format!("bundles/{name}"))?;
    need(
        !root.exists(),
        "scan bundle already exists; inspect host bundle before retry",
    )?;
    error(fs::create_dir_all(root.parent().unwrap()))?;
    error(fs::create_dir(&root))?;
    let result = (|| {
        let directory = format!("generations/{seq:010}-{}", &review.fingerprint[..32]);
        let base = root.join(&directory);
        error(fs::create_dir_all(base.join("media")))?;
        let mut catalog = Catalog {
            schema_version: 1,
            generation: seq,
            games: vec![],
        };
        let mut sizes = BTreeMap::new();
        let mut files = BTreeMap::new();
        if let Some(prior) = &review.prior {
            let oldbase = library::safe(&pocket.join(library::TARGET), &prior.directory)?;
            catalog = library::json(&library::safe(&oldbase, "catalog.json")?)?;
            catalog.generation = seq;
            for (path, sha) in &prior.files {
                if path.starts_with("media/") {
                    let source = library::safe(&oldbase, path)?;
                    let target = library::safe(&base, path)?;
                    error(fs::create_dir_all(target.parent().unwrap()))?;
                    error(fs::copy(source, &target))?;
                    let (actual, size) = library::hash(&target)?;
                    need(&actual == sha, "retained media changed")?;
                    sizes.insert(path.clone(), size);
                    files.insert(path.clone(), sha.clone());
                }
            }
        }
        let namespace = uuid::Uuid::parse_str("ce3176ca-78d2-464e-a07e-9e08b728a44e").unwrap();
        for item in &review.candidates {
            let path = format!("media/{}.{}", item.sha256, item.format);
            let target = base.join(&path);
            log(&format!("Preparing {}\n", item.path));
            error(fs::copy(library::safe(pocket, &item.path)?, &target))?;
            let (actual, size) = library::hash(&target)?;
            need(
                actual == item.sha256 && size == item.bytes,
                "source changed during preparation",
            )?;
            let title = Path::new(&item.path)
                .file_stem()
                .and_then(|s| s.to_str())
                .ok_or("title encoding")?
                .to_string();
            let id = uuid::Uuid::new_v5(&namespace, item.sha256.as_bytes()).to_string();
            need(
                !catalog.games.iter().any(|g| g.id == id),
                "existing game identity conflict",
            )?;
            catalog.games.push(Game{id,title,details:"Unidentified import. Model is an import assumption; use native/manual launch until qualified.".into(),releases:vec![Release{path:path.clone(),format:item.format.clone(),model:review.model.clone(),label:item.path.clone(),sha256:item.sha256.clone()}],default_release:0,collection_mask:0});
            sizes.insert(path.clone(), size);
            files.insert(path, item.sha256.clone());
        }
        catalog
            .games
            .sort_by_key(|g| (alias(&g.title), g.id.clone()));
        let binary = compile(&catalog, &sizes)?;
        for (name, bytes) in [
            ("index.bin", binary),
            (
                "catalog.json",
                serde_json::to_vec_pretty(&catalog).map_err(|e| e.to_string())?,
            ),
            (
                "import-report.json",
                serde_json::to_vec_pretty(review).map_err(|e| e.to_string())?,
            ),
        ] {
            error(fs::write(base.join(name), &bytes))?;
            files.insert(name.into(), format!("{:x}", Sha256::digest(&bytes)));
        }
        let publication = Record {
            version: 1,
            sequence: seq,
            directory,
            files,
        };
        library::verify(&root, &publication)?;
        let bundle = Bundle {
            version: 1,
            target: library::TARGET.into(),
            expected_prior: match &review.prior {
                Some(r) => serde_json::to_value(r).map_err(|e| e.to_string())?,
                None => serde_json::json!({}),
            },
            publication,
            summary: Summary {
                added: review.candidates.len() as u32,
                retained: review.prior.as_ref().map_or(0, |r| {
                    r.files.keys().filter(|p| p.starts_with("media/")).count() as u32
                }),
                unidentified: review.candidates.len() as u32,
            },
        };
        error(fs::write(
            root.join("bundle.json"),
            serde_json::to_vec_pretty(&bundle).map_err(|e| e.to_string())?,
        ))?;
        Ok(name)
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&root);
    }
    result
}
