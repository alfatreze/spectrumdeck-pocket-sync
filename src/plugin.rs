use crate::{ingest, library};
use extism_pdk::*;
use serde::{Deserialize, Serialize};
use std::{fs, path::Path};
#[derive(Serialize, ToBytes)]
#[encoding(Json)]
pub enum PluginMessage {
    Choice {
        name: String,
        query: String,
        choices: Vec<String>,
    },
    Text {
        name: String,
        query: String,
    },
    Exit,
}
#[derive(Deserialize, FromBytes)]
#[encoding(Json)]
pub enum HostMessage {
    Answer { name: String, value: String },
    Kill,
}
#[host_fn]
unsafe extern "ExtismHost" {
    fn print_msg(message: &str) -> ();
    fn open_url(url: &str) -> ();
}
fn log(message: &str) {
    unsafe {
        let _ = print_msg(message);
    }
}
fn menu() -> PluginMessage {
    PluginMessage::Choice {
        name: "menu".into(),
        query: "SpectrumDeck · Add games to your Pocket library".into(),
        choices: vec![
            "Add games from card".into(),
            "View library".into(),
            "Desktop companion & help".into(),
            "Advanced options".into(),
            "Exit".into(),
        ],
    }
}
fn manual_folder() -> PluginMessage {
    PluginMessage::Text { name: "scan-folder".into(), query: "Folder relative to the selected card, e.g. Assets/zxspectrum/common. Loose TAP/TZX/Z80/SNA/DSK/TRD/VHD/SZX files only; archives use desktop preparation.".into() }
}
fn choose_source(source: &str) -> FnResult<PluginMessage> {
    if let Err(e) = library::relative(source) {
        log(&format!("Invalid card folder: {e}\n"));
        return Ok(menu());
    }
    var::set("source", source)?;
    Ok(PluginMessage::Choice {
        name: "scan-model".into(),
        query: "2 / Choose the Spectrum model for these games. For most original titles, choose 48k. This is an assumption, not a compatibility test."
            .into(),
        choices: vec![
            "48k".into(),
            "128k".into(),
            "pentagon".into(),
            "Cancel".into(),
        ],
    })
}
fn discover_folders() -> FnResult<PluginMessage> {
    var::remove("folders")?;
    var::remove("scan")?;
    var::remove("source")?;
    match ingest::discover(Path::new("pocket")) {
        Ok(folders) if !folders.is_empty() => {
            log(&format!(
                "Found {} Spectrum-named Assets folders with loose media. Discovery is read-only; compatibility is not verified.\n",
                folders.len()
            ));
            var::set("folders", serde_json::to_string(&folders)?)?;
            let mut choices = folders;
            choices.extend(["Browse card folders".into(), "Cancel".into()]);
            Ok(PluginMessage::Choice {
                name: "detected-folder".into(),
                query: "1 / Choose your games folder. Its subfolders are included.".into(),
                choices,
            })
        }
        Ok(_) => {
            log(
                "No games found in the usual Spectrum folders. You can browse another location or use the desktop companion to add a pack.\n",
            );
            Ok(PluginMessage::Choice{name:"empty-card".into(),query:"No Spectrum games found yet. This plugin uses games already on the selected card. The desktop companion can import a folder or archive from your Mac.".into(),choices:vec!["Browse card folders".into(),"Desktop companion & help".into(),"Back".into()]})
        }
        Err(e) => {
            log(&format!(
                "Folder discovery stopped: {e}. Enter a folder manually.\n"
            ));
            Ok(manual_folder())
        }
    }
}
fn browse_folder(relative: &str) -> FnResult<PluginMessage> {
    match browse_impl(relative) {
        Ok(message) => Ok(message),
        Err(error) => {
            log(&format!(
                "Could not open this folder: {error}. Choose Add games again, or use Advanced options for a manual path.\n"
            ));
            Ok(menu())
        }
    }
}
fn browse_impl(relative: &str) -> Result<PluginMessage, Error> {
    let root = Path::new("pocket");
    let folder = if relative.is_empty() {
        root.to_owned()
    } else {
        library::safe(root, relative).map_err(Error::msg)?
    };
    let mut paths = vec![];
    for entry in fs::read_dir(&folder)?.take(1001) {
        let path = entry?.path();
        let meta = fs::symlink_metadata(&path)?;
        let Some(name) = path.file_name().and_then(|s| s.to_str()) else {
            continue;
        };
        if meta.is_symlink() || !meta.is_dir() || name.starts_with('.') {
            continue;
        }
        let Some(value) = path.strip_prefix(root).ok().and_then(|p| p.to_str()) else {
            continue;
        };
        if library::relative(value).is_err()
            || value == library::TARGET
            || value.starts_with(&format!("{}/", library::TARGET))
        {
            continue;
        }
        paths.push(value.to_string());
    }
    paths.sort();
    if paths.len() > 100 {
        log("Showing the first 100 folders. Advanced options allows a manual path.\n");
        paths.truncate(100);
    }
    var::set("browse-current", serde_json::to_string(relative)?)?;
    var::set("browse-choices", serde_json::to_string(&paths)?)?;
    let mut choices = vec![];
    if !relative.is_empty() {
        choices.push("Use this folder".into());
        choices.push("Parent folder".into());
    }
    choices.extend(paths);
    choices.push("Cancel".into());
    Ok(PluginMessage::Choice {
        name: "browse".into(),
        query: format!(
            "1 / Find your games folder · {}. Choose a subfolder, then Use this folder. All its subfolders will be scanned.",
            if relative.is_empty() {
                "Card root"
            } else {
                relative
            }
        ),
        choices,
    })
}
fn browse_answer(choice: &str) -> FnResult<PluginMessage> {
    if choice == "Cancel" {
        var::remove("browse-current")?;
        var::remove("browse-choices")?;
        return Ok(menu());
    }
    let Some(current) = var::get::<String>("browse-current")? else {
        return Ok(menu());
    };
    let current: String = serde_json::from_str(&current)?;
    let allowed = var::get::<String>("browse-choices")?.unwrap_or_default();
    var::remove("browse-current")?;
    var::remove("browse-choices")?;
    if choice == "Use this folder" && !current.is_empty() {
        return choose_source(&current);
    }
    if choice == "Parent folder" && !current.is_empty() {
        return browse_folder(current.rsplit_once('/').map(|(p, _)| p).unwrap_or(""));
    }
    let allowed: Vec<String> = serde_json::from_str(&allowed).unwrap_or_default();
    if allowed.iter().any(|p| p == choice) {
        return browse_folder(choice);
    }
    log("Folder selection expired. Start again.\n");
    Ok(menu())
}
#[plugin_fn]
pub fn start() -> FnResult<PluginMessage> {
    var::remove("browse-current")?;
    var::remove("browse-choices")?;
    var::remove("pending")?;
    var::remove("folders")?;
    var::remove("scan")?;
    var::remove("source")?;
    log(
        "Welcome to SpectrumDeck. Add games already on your card, or use the desktop companion to import folders and archives from your Mac.\n",
    );
    Ok(menu())
}
#[plugin_fn]
pub fn handle_response(message: HostMessage) -> FnResult<PluginMessage> {
    match message {
  HostMessage::Kill=>{var::remove("browse-current")?;var::remove("browse-choices")?;var::remove("folders")?;var::remove("scan")?;var::remove("source")?;var::remove("pending")?;log("Cancelled between steps.\n");Ok(PluginMessage::Exit)},
  HostMessage::Answer{name,value}=>match (name.as_str(),value.as_str()){
   ("menu","Add games from card")|("menu","Scan card folder")=>discover_folders(),
   ("menu","Advanced options")=>Ok(PluginMessage::Choice{name:"advanced".into(),query:"Advanced library tools".into(),choices:vec!["Enter card folder manually".into(),"Publish prepared bundle".into(),"Inspect current library".into(),"Back".into()]}),
   ("advanced","Enter card folder manually")=>Ok(manual_folder()),
   ("advanced","Back")|("empty-card","Back")|("companion-help","Back")=>Ok(menu()),
   ("menu","Desktop companion & help")|("empty-card","Desktop companion & help")=>Ok(PluginMessage::Choice{name:"companion-help".into(),query:"The desktop companion has folder/archive pickers, a visual release list and real imports. Download it from this repository’s release, unzip it, then open Start SpectrumDeck Companion.command. Requires Python 3.11+ on macOS. It runs outside Pocket Sync.".into(),choices:vec!["Open companion download".into(),"Back".into()]}),
   ("companion-help","Open companion download")=>{unsafe {let _=open_url("https://github.com/alfatreze/spectrumdeck-pocket-sync/releases/latest");}Ok(menu())},
   ("empty-card","Browse card folders")=>browse_folder(""),
   ("browse",choice)=>browse_answer(choice),
   ("detected-folder","Browse card folders")=>{var::remove("folders")?;browse_folder("")},
   ("detected-folder","Enter folder manually")=>{var::remove("folders")?;Ok(manual_folder())},
   ("detected-folder","Cancel")=>{var::remove("folders")?;Ok(menu())},
   ("detected-folder",source)=>{let folders=var::get::<String>("folders")?.unwrap_or_default();var::remove("folders")?;let folders:Vec<String>=serde_json::from_str(&folders).unwrap_or_default();if folders.iter().any(|p|p==source){choose_source(source)}else{log("Folder selection expired or invalid; scan again.\n");Ok(menu())}},
   ("scan-folder",source)=>choose_source(source),
   ("scan-model","Cancel")=>{var::remove("source")?;Ok(menu())},
   ("scan-model",model)=>{if let Some(source)=var::get::<String>("source")?{var::remove("source")?;match ingest::preview(Path::new("pocket"),&source,model,|_|{}){
    Ok(p)=>{for reason in p.excluded.iter().take(5){log(&format!("Excluded: {reason}\n"));}log(&format!("{} new, {} already present, {} aliases, {} exclusions. New titles use filenames and assumed model {}.\n",p.candidates.len(),p.existing,p.aliases,p.excluded.len(),p.model));
     if p.candidates.is_empty(){log("Nothing new to add. These files are already present or excluded. Your library is unchanged.\n");Ok(menu())}else{var::set("scan",serde_json::to_string(&p)?)?;Ok(PluginMessage::Choice{name:"scan-confirm".into(),query:format!("3 / Review and add {} releases from {}. {} already in your library; {} excluded. Model: {}. Existing games and control presets stay. New titles use filenames.",p.candidates.len(),p.source,p.existing,p.excluded.len(),p.model),choices:vec!["Cancel".into(),"Add games".into()]})}
    },Err(e)=>{log(&format!("Scan stopped: {e}\n"));Ok(menu())}
   }}else{Ok(menu())}},
   ("scan-confirm","Cancel")=>{var::remove("scan")?;Ok(menu())},
   ("scan-confirm","Add games")|("scan-confirm","Create/update library")=>{if let Some(value)=var::get::<String>("scan")?{var::remove("scan")?;let p:ingest::Preview=serde_json::from_str(&value)?;match ingest::prepare(Path::new("host"),Path::new("pocket"),&p,|_|{}).and_then(|name|library::install(Path::new("host"),Path::new("pocket"),&name,log)){Ok(r)=>log(&format!("Generation {} ready.\n",r.sequence)),Err(e)=>log(&format!("Import stopped: {e}\nInspect current library before retry.\n"))}}else{log("No scan pending.\n")};Ok(menu())},
   ("menu","Publish prepared bundle")|("advanced","Publish prepared bundle")=>Ok(PluginMessage::Text{name:"bundle".into(),query:"Bundle folder name under this plugin's host/bundles (letters, digits, - or _). Prepare with tools/pocketsync_bundle.py first.".into()}),
   ("menu","Inspect current library")|("menu","View library")|("advanced","Inspect current library")=>{match library::latest(&Path::new("pocket").join(library::TARGET)){Ok(Some((_,r)))=>log(&format!("Your library: verified generation {}, {} media releases.\n",r.sequence,r.files.keys().filter(|p|p.starts_with("media/")).count())),Ok(None)=>log("Your library is empty. Choose Add games from card, or import a local pack with the desktop companion.\n"),Err(e)=>log(&format!("Library inspection failed: {e}\n"))};Ok(menu())},
   ("bundle",name)=>match library::bundle(Path::new("host"),name){
    Ok(b)=>{var::set("pending",name)?;Ok(PluginMessage::Choice{name:"confirm".into(),query:format!("Publish generation {}? {} added, {} retained, {} unidentified. Existing control presets are preserved. The target library must match the reviewed bundle.",b.publication.sequence,b.summary.added,b.summary.retained,b.summary.unidentified),choices:vec!["Cancel".into(),"Publish".into()]})},
    Err(e)=>{log(&format!("Bundle rejected: {e}\n"));Ok(menu())}
   },
   ("confirm","Publish")=>{if let Some(name)=var::get::<String>("pending")?{var::remove("pending")?;match library::install(Path::new("host"),Path::new("pocket"),&name,log){Ok(r)=>log(&format!("Generation {} ready.\n",r.sequence)),Err(e)=>log(&format!("Publication stopped: {e}\nInspect current library before retry; a completed commit may already be present.\n"))}}else{log("No reviewed bundle pending.\n")};Ok(menu())},
   ("confirm","Cancel")=>{var::remove("pending")?;Ok(menu())},
   _=>Ok(PluginMessage::Exit)
  }
 }
}
