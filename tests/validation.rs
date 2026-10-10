use spectrumdeck_pocket_plugin::library::{Record, relative, verify};
use std::{collections::BTreeMap, path::Path};
#[test]
fn paths_and_unicode_never_panic() {
    for value in ["../bad", "/root", "a//b", "a\\b", "c:foo", "a\0b"] {
        assert!(relative(value).is_err())
    }
    assert!(relative("media/good.tap").is_ok());
    for name in [
        "éééééééééééééééééééééx",
        "0123456789-00000000000000000000000000000000",
    ] {
        let r = Record {
            version: 1,
            sequence: 1,
            directory: format!("generations/{name}"),
            files: BTreeMap::new(),
        };
        assert!(verify(Path::new("missing"), &r).is_err());
    }
}
#[test]
fn wire_record_rejects_extra_fields() {
    assert!(
        serde_json::from_str::<Record>(
            r#"{"version":1,"sequence":1,"directory":"generations/x","files":{},"unexpected":true}"#
        )
        .is_err()
    );
}
