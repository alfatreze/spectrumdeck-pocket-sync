use spectrumdeck_pocket_plugin::library;
use std::path::Path;
fn main() {
    let args = std::env::args().collect::<Vec<_>>();
    assert_eq!(args.len(), 4, "publish HOST_ROOT POCKET_ROOT BUNDLE_NAME");
    match library::install(Path::new(&args[1]), Path::new(&args[2]), &args[3], |s| {
        print!("{s}")
    }) {
        Ok(r) => println!("{}", serde_json::to_string(&r).unwrap()),
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(1)
        }
    }
}
