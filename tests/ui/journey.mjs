// End-to-end UI journey in jsdom against a live server (see run.sh). jsdom is not a real browser:
// it verifies logic, DOM and flows, not visual layout.
import { JSDOM } from "jsdom"; import fs from "fs";
const base=`http://127.0.0.1:${process.env.HF_UI_PORT||8798}`; const KEY="omni-key-1234567890";
const r0=await fetch(base+"/auth?token=tok",{redirect:"manual"}); const cookie=r0.headers.get("set-cookie").split(";")[0];
const f=(u,o={})=>fetch(new URL(u,base),{...o,headers:{...(o.headers||{}),cookie}});
const html=await (await f("/")).text(); const errors=[];
const dom=new JSDOM(html,{url:base+"/",runScripts:"outside-only",pretendToBeVisual:true}); const w=dom.window;
w.fetch=(u,o)=>f(u,o); w.confirm=()=>true; w.TextDecoder=TextDecoder; w.addEventListener("error",e=>errors.push(e.message)); w.addEventListener("unhandledrejection",e=>errors.push("rej:"+e.reason));
w.EventSource=class{constructor(u){this.c=new AbortController();(async()=>{const r=await f(u,{signal:this.c.signal});const rd=r.body.getReader();const dec=new TextDecoder();let buf="";for(;;){const {done,value}=await rd.read();if(done)break;buf+=dec.decode(value);let i;while((i=buf.indexOf("\n\n"))>=0){const ch=buf.slice(0,i);buf=buf.slice(i+2);if(ch.startsWith("data:"))this.onmessage&&this.onmessage({data:ch.slice(5).trim()});}}})().catch(()=>{});}close(){this.c.abort();}};
const code=["core","guide","settings","app"].map(n=>fs.readFileSync(new URL(`../../src/hearthforge/web/${n}.js`,import.meta.url),"utf8").replace('"use strict";','')).join("\n");
w.eval(code); const d=w.document; const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const btn=(t,root=d)=>[...root.querySelectorAll("button")].find(b=>b.textContent.trim().startsWith(t));
const until=async(fn,ms=6000)=>{for(let i=0;i<ms/100;i++){const v=fn();if(v)return v;await sleep(100);}throw new Error("timeout waiting: "+fn);};
const ok=(label,cond)=>{console.log((cond?"PASS":"FAIL"),label); if(!cond) process.exitCode=1;};
const set=(el,v)=>{el.value=v;el.dispatchEvent(new w.Event("input",{bubbles:true}));};

await sleep(700);
ok("home shows 'Connect a model' setup", !!d.querySelector(".step") && d.body.textContent.includes("Connect a model"));
// 1) connect wizard with OmniRoute-like gateway
btn("Connect a model",d.querySelector(".step")).click(); await until(()=>d.querySelector(".modal"));
btn("OmniRoute",d.querySelector(".modal")).click(); await sleep(100);
const m=()=>d.querySelector(".modal");
ok("preset prefilled URL", m().querySelector("input[aria-label='Base URL']").value==="http://localhost:20128/v1");
set(m().querySelector("input[aria-label='API key']"),KEY);
btn("Connect and find models",m()).click();
await until(()=>m().textContent.includes("Found 2 models"));
ok("detected models listed", m().textContent.includes("openai/gpt-x"));
btn("Use this model",m()).click();
await until(()=>m().textContent.includes("Works"),8000);
ok("test message succeeded", m().textContent.includes("I work!"));
ok("active model in top bar", d.querySelector(".top").textContent.includes("auto"));
btn("Start chatting",m()).click(); await sleep(300);
// 2) chat
const cin=d.querySelector("#cin"); set(cin,"Say hello"); btn("Send").click();
await until(()=>d.querySelector(".msg.ai .body")?.textContent.includes("Hello from the model"));
ok("chat streamed a reply", true);
// 3) folder picker
btn("Open a folder",d.querySelector(".top")).click(); await until(()=>d.querySelector(".modal"));
const parent=fs.readFileSync(process.env.HF_UI_TMP+"/parent","utf8");
set(m().querySelector("input[aria-label='Folder path']"),parent); btn("Go",m()).click();
await sleep(1500); await until(()=>m().textContent.includes("myapp"));
ok("project badge shown", m().textContent.includes("project"));
[...m().querySelectorAll(".item")].find(i=>i.textContent.includes("myapp")).click();
await until(()=>m().querySelector(".notice strong")?.textContent.endsWith("myapp")&&!btn("Select this folder",m()).disabled);
btn("Select this folder",m()).click(); await until(()=>!d.querySelector(".modal"));
await sleep(500); ok("folder attached and Agent view open", d.querySelector(".top").textContent.includes("myapp") && !!d.querySelector(".agent"));
// 4) internet on + test
btn("Internet",d.querySelector(".side")).click(); await sleep(200);
[...d.querySelectorAll(".choice")].find(c=>c.textContent.startsWith("On")).click();
btn("Save and test search").click(); await sleep(2000); await until(()=>d.body.textContent.includes("Python 3 docs"));
ok("internet search test works", d.querySelector(".top").textContent.includes("Internet: on"));
// 5) chat with web
btn("Chat",d.querySelector(".side")).click(); await sleep(200);
const web=[...d.querySelectorAll(".toggle")].find(t=>t.textContent.includes("Web")); web.click(); await sleep(200);
set(d.querySelector("#cin"),"python docs?"); btn("Send").click();
await until(()=>d.querySelector(".sources")); ok("web answer shows sources", d.querySelector(".sources").textContent.includes("Python 3 docs"));
// 6) agent
btn("Agent",d.querySelector(".side")).click(); await sleep(300);
set(d.querySelector("#goal"),"Fix the failing test"); btn("Start",d.querySelector(".composer")).click();
let approved=0; for(let i=0;i<120;i++){await sleep(150); const a=btn("Approve",d.querySelector(".gate")||d); if(d.querySelector(".gate:not(.done)")&&a&&approved<2){approved++;a.click();} if(d.querySelector(".final"))break;}
ok("agent finished verified", d.querySelector(".final")?.textContent.includes("Verified"));
ok("diff visible in inspector", d.querySelectorAll(".insp .diff div").length>3);
// 7) palette + guide + other views
d.dispatchEvent(new w.KeyboardEvent("keydown",{key:"k",ctrlKey:true,bubbles:true})); await until(()=>d.querySelector(".modal")); 
set(d.querySelector(".modal input"),"guide"); await sleep(100); d.querySelector(".modal .item").click(); await sleep(300);
ok("guide via palette", d.querySelector("h1")?.textContent==="Guide" && d.body.textContent.includes("OmniRoute (gateway)"));
btn("Knowledge",d.querySelector(".side")).click(); await sleep(500);
btn("Index this folder").click(); await until(()=>d.querySelector("#main").textContent.includes("docs ·"));
ok("knowledge index lists source (array rendering)", d.querySelector("#main .card .badge")?.textContent.includes("docs"));
set(d.querySelector("input[aria-label='Search your indexed files…'], input[type=search]"),"add"); btn("Search").click();
await until(()=>d.querySelector("#main pre"),4000); ok("knowledge search results rendered with citation", d.querySelector("#main .card.flat .mono")?.textContent.includes("calc.py"));
for(const v of ["Models","Folders","Knowledge","Capabilities","Hardware fit","Usage and audit"]){ btn(v,d.querySelector(".side")).click(); await sleep(600); ok("view "+v, !!d.querySelector("#main h1")); }
ok("no script errors", errors.length===0); if(errors.length) console.log(errors);
process.exit(process.exitCode||0);
