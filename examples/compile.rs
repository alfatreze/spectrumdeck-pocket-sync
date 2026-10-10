use spectrumdeck_pocket_plugin::ingest::{self, Catalog};
use std::collections::BTreeMap;
fn main() {
    let a = std::env::args().collect::<Vec<_>>();
    let c: Catalog = serde_json::from_slice(&std::fs::read(&a[1]).unwrap()).unwrap();
    let sizes: BTreeMap<String, u64> =
        serde_json::from_slice(&std::fs::read(&a[2]).unwrap()).unwrap();
    std::fs::write(&a[3], ingest::compile(&c, &sizes).unwrap()).unwrap();
}
