use crate::{ingest, library};
use extism_pdk::*;
use serde::{Deserialize, Serialize};
use std::path::Path;
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
}
fn log(message: &str) {
    unsafe {
        let _ = print_msg(message);
    }
}
fn menu() -> PluginMessage {
    PluginMessage::Choice {
        name: "menu".into(),
        query: "SpectrumDeck library · card folders and reviewed bundles".into(),
        choices: vec![
            "Scan card folder".into(),
            "Publish prepared bundle".into(),
            "Inspect current library".into(),
            "Exit".into(),
        ],
    }
}
#[plugin_fn]
pub fn start() -> FnResult<PluginMessage> {
    var::remove("pending")?;
    var::remove("scan")?;
    var::remove("source")?;
    log("SpectrumDeck: no network downloads; user presets are preserved.\n");
    Ok(menu())
}
#[plugin_fn]
pub fn handle_response(message: HostMessage) -> FnResult<PluginMessage> {
    match message {
  HostMessage::Kill=>{var::remove("scan")?;var::remove("source")?;var::remove("pending")?;log("Cancelled between steps.\n");Ok(PluginMessage::Exit)},
  HostMessage::Answer{name,value}=>match (name.as_str(),value.as_str()){
   ("menu","Scan card folder")=>Ok(PluginMessage::Text{name:"scan-folder".into(),query:"Folder relative to the selected card, e.g. Assets/zxspectrum/common. Loose TAP/TZX/Z80/SNA/DSK/TRD/VHD/SZX files only; archives use desktop preparation.".into()}),
   ("scan-folder",source)=>{if let Err(e)=library::relative(source){log(&format!("Invalid card folder: {e}\n"));return Ok(menu())}var::set("source",source)?;Ok(PluginMessage::Choice{name:"scan-model".into(),query:"Assumed model for unidentified files. This does not establish compatibility.".into(),choices:vec!["48k".into(),"128k".into(),"pentagon".into(),"Cancel".into()]})},
   ("scan-model","Cancel")=>{var::remove("source")?;Ok(menu())},
   ("scan-model",model)=>{if let Some(source)=var::get::<String>("source")?{var::remove("source")?;match ingest::preview(Path::new("pocket"),&source,model,log){
    Ok(p)=>{for reason in p.excluded.iter().take(50){log(&format!("Excluded: {reason}\n"));}log(&format!("{} new, {} already present, {} aliases, {} exclusions. New titles use filenames and assumed model {}.\n",p.candidates.len(),p.existing,p.aliases,p.excluded.len(),p.model));
     if p.candidates.is_empty(){log("No new unambiguous releases. No publication written.\n");Ok(menu())}else{var::set("scan",serde_json::to_string(&p)?)?;Ok(PluginMessage::Choice{name:"scan-confirm".into(),query:format!("Add {} unidentified releases from {}? {} existing releases matched; {} exclusions. Model assumption: {}. Existing library and presets stay. Archive extraction and metadata enrichment are separate.",p.candidates.len(),p.source,p.existing,p.excluded.len(),p.model),choices:vec!["Cancel".into(),"Create/update library".into()]})}
    },Err(e)=>{log(&format!("Scan stopped: {e}\n"));Ok(menu())}
   }}else{Ok(menu())}},
   ("scan-confirm","Cancel")=>{var::remove("scan")?;Ok(menu())},
   ("scan-confirm","Create/update library")=>{if let Some(value)=var::get::<String>("scan")?{var::remove("scan")?;let p:ingest::Preview=serde_json::from_str(&value)?;match ingest::prepare(Path::new("host"),Path::new("pocket"),&p,log).and_then(|name|library::install(Path::new("host"),Path::new("pocket"),&name,log)){Ok(r)=>log(&format!("Generation {} ready.\n",r.sequence)),Err(e)=>log(&format!("Import stopped: {e}\nInspect current library before retry.\n"))}}else{log("No scan pending.\n")};Ok(menu())},
   ("menu","Publish prepared bundle")=>Ok(PluginMessage::Text{name:"bundle".into(),query:"Bundle folder name under this plugin's host/bundles (letters, digits, - or _). Prepare with tools/pocketsync_bundle.py first.".into()}),
   ("menu","Inspect current library")=>{match library::latest(&Path::new("pocket").join(library::TARGET)){Ok(Some((_,r)))=>log(&format!("Verified generation {}: {} files.\n",r.sequence,r.files.len())),Ok(None)=>log("No SpectrumDeck publication yet.\n"),Err(e)=>log(&format!("Library inspection failed: {e}\n"))};Ok(menu())},
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
