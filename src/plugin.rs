use crate::library;
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
        query: "SpectrumDeck library · reviewed local bundles".into(),
        choices: vec![
            "Publish prepared bundle".into(),
            "Inspect current library".into(),
            "Exit".into(),
        ],
    }
}
#[plugin_fn]
pub fn start() -> FnResult<PluginMessage> {
    var::remove("pending")?;
    log("SpectrumDeck: no network downloads; user presets are preserved.\n");
    Ok(menu())
}
#[plugin_fn]
pub fn handle_response(message: HostMessage) -> FnResult<PluginMessage> {
    match message {
  HostMessage::Kill=>{var::remove("pending")?;log("Cancelled between steps.\n");Ok(PluginMessage::Exit)},
  HostMessage::Answer{name,value}=>match (name.as_str(),value.as_str()){
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
