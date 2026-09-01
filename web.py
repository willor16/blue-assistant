"""Interfaz web de BLUE (Flask). Sirve dos vistas:
  - "/"        panel completo, futurista (ventana flotante grande)
  - "/bubble"  burbuja compacta que aparece con Super+J (estado + detener + cerrar)
"""
from __future__ import annotations
import os
import re
import subprocess
import threading
from pathlib import Path

from flask import Flask, jsonify, request

import config as config_mod
import protocols
import store
import voice as voice_mod

CONFIG_DIR = Path.home() / ".config" / "blue"
VOICES_DIR = CONFIG_DIR / "voices"
FIFO = CONFIG_DIR / "trigger"
PORT = 8777

# Catálogo de voces unificado (proviene de voice.py para no duplicar)
VOICE_CATALOG = voice_mod.VOICE_CATALOG
KOKORO_VOICES = VOICE_CATALOG["kokoro"]
EDGE_VOICES   = VOICE_CATALOG["edge"]

ENGINE_LABELS = {
    "kokoro": "Kokoro (local)",
    "edge":   "Edge — Microsoft (online)",
    "piper":  "Piper (ligera)",
}

# ---------------------------------------------------------------- estilos comunes
BASE_CSS = r"""
*{box-sizing:border-box;margin:0;padding:0}
:root{
 --bg:#060912; --bg2:#0a1120; --glass:rgba(18,28,48,.55); --glass2:rgba(26,40,68,.6);
 --line:rgba(94,160,255,.16); --line2:rgba(94,160,255,.30);
 --cyan:#4fe3ff; --blue:#3b82f6; --ice:#9fdcff; --text:#dbe9ff; --muted:#7d93b8;
 --good:#3ee08f; --warn:#ffd166; --bad:#ff6b8a;
}
body{font-family:'Inter','Segoe UI',system-ui,sans-serif;background:
 radial-gradient(1200px 700px at 80% -10%,#0e1d38 0,transparent 60%),
 radial-gradient(900px 600px at -10% 110%,#0b1730 0,transparent 55%),var(--bg);
 color:var(--text);height:100vh;overflow:hidden;-webkit-font-smoothing:antialiased}
/* orbe futurista */
.orb{position:relative;border-radius:50%;flex:none;
 background:radial-gradient(circle at 35% 30%,var(--ice),var(--blue) 60%,#1e3a8a 100%);
 box-shadow:0 0 22px -2px var(--cyan),inset 0 0 14px rgba(255,255,255,.25)}
.orb::before,.orb::after{content:"";position:absolute;inset:-7px;border-radius:50%;
 border:1.5px solid var(--line2);opacity:.7}
.orb::after{inset:-13px;border-color:rgba(79,227,255,.18)}
.orb.spin::before{animation:spin 4s linear infinite}
.orb.spin::after{animation:spin 7s linear infinite reverse}
@keyframes spin{to{transform:rotate(360deg)}}
.orb.pulse{animation:breathe 1.5s ease-in-out infinite}
@keyframes breathe{0%,100%{transform:scale(1)}50%{transform:scale(1.07)}}
.orb.listening{background:radial-gradient(circle at 35% 30%,#bfefff,#22c1ff 60%,#0a6ebd)}
.orb.thinking{background:radial-gradient(circle at 35% 30%,#fff0bf,#ffcc44 60%,#b5860b);box-shadow:0 0 22px -2px #ffcc44}
.orb.speaking{background:radial-gradient(circle at 35% 30%,#c6ffe0,#34e08f 60%,#0f9c5d);box-shadow:0 0 24px -2px #34e08f}
::-webkit-scrollbar{width:8px}::-webkit-scrollbar-thumb{background:rgba(94,160,255,.25);border-radius:5px}
"""

# ----------------------------------------------------------------- panel completo
PAGE = r"""<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>BLUE</title>
<style>__BASE__
body{display:flex;flex-direction:column;font-size:14px}
header{display:flex;align-items:center;gap:15px;padding:15px 20px;
 background:linear-gradient(180deg,rgba(20,34,60,.7),rgba(8,14,26,.3));
 border-bottom:1px solid var(--line);backdrop-filter:blur(10px)}
header .orb{width:38px;height:38px}
.brand{flex:1}
.brand h1{font-size:20px;font-weight:800;letter-spacing:3px;
 background:linear-gradient(90deg,var(--cyan),var(--ice));-webkit-background-clip:text;
 -webkit-text-fill-color:transparent;text-shadow:0 0 24px rgba(79,227,255,.4)}
.brand .sub{font-size:11px;color:var(--muted);letter-spacing:1px;margin-top:1px}
#status{font-size:11px;letter-spacing:.5px}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--muted);
 margin-right:6px;vertical-align:middle}
.iconbtn{background:var(--glass);border:1px solid var(--line);color:var(--ice);
 width:36px;height:36px;border-radius:10px;cursor:pointer;font-size:15px;display:grid;
 place-items:center;transition:.15s}
.iconbtn:hover{border-color:var(--line2);box-shadow:0 0 12px -3px var(--cyan)}
.iconbtn.danger:hover{color:var(--bad);border-color:var(--bad);box-shadow:0 0 12px -3px var(--bad)}
.iconbtn.stopv{color:var(--warn);border-color:rgba(255,209,102,.4)}
.iconbtn.stopv:hover{background:rgba(255,209,102,.12)}
main{flex:1;display:flex;overflow:hidden}
#chat{flex:1;display:flex;flex-direction:column;overflow:hidden}
#log{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:14px}
.empty{margin:auto;text-align:center;color:var(--muted);max-width:300px;line-height:1.6}
.empty .big{font-size:34px;margin-bottom:12px}
.row{display:flex;gap:10px;align-items:flex-end;max-width:86%}
.row.u{align-self:flex-end;flex-direction:row-reverse}
.av{width:28px;height:28px;border-radius:50%;flex:none;display:grid;place-items:center;font-size:13px}
.av.a{background:linear-gradient(135deg,var(--cyan),var(--blue));color:#04121f;font-weight:700}
.av.u{background:var(--glass2);color:var(--ice);border:1px solid var(--line)}
.bubble{padding:10px 14px;border-radius:16px;line-height:1.5;white-space:pre-wrap;word-break:break-word}
.u .bubble{background:linear-gradient(135deg,#1e4fd6,#2563eb);color:#eaf2ff;border-bottom-right-radius:5px}
.a .bubble{background:var(--glass2);color:var(--text);border:1px solid var(--line);border-bottom-left-radius:5px}
.time{font-size:10px;color:var(--muted);margin-top:4px;padding:0 6px}
aside{width:268px;flex:none;background:linear-gradient(180deg,rgba(10,17,32,.6),rgba(6,9,18,.6));
 border-left:1px solid var(--line);display:flex;flex-direction:column;overflow:hidden;backdrop-filter:blur(8px)}
.tabs{display:flex;padding:12px 12px 0;gap:6px}
.tab{flex:1;padding:8px 4px;border-radius:9px 9px 0 0;font-size:11px;font-weight:600;
 text-align:center;cursor:pointer;color:var(--muted);border:1px solid transparent;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tab.on{color:var(--ice);background:var(--glass);border-color:var(--line);border-bottom-color:transparent}
.dsec{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--cyan);margin:6px 2px 9px}
.dgrp{margin-bottom:13px}
.dgrp h4{font-size:11px;font-weight:700;letter-spacing:.3px;color:var(--ice);margin:0 2px 7px;
 display:flex;justify-content:space-between;align-items:center}
.dgrp h4 span{color:var(--muted);font-weight:600;font-size:10.5px}
.ditem{background:var(--glass);border:1px solid var(--line);border-radius:9px;padding:8px 10px;
 margin-bottom:6px;font-size:12px;display:flex;justify-content:space-between;gap:8px}
.ditem .ti{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ditem .ch{color:var(--muted);font-size:10.5px;flex:none}
.mfact{background:var(--glass2);border:1px solid var(--line);border-radius:9px;padding:7px 10px;
 margin-bottom:6px;font-size:12px;line-height:1.45;color:var(--ice)}
.listwrap{flex:1;overflow-y:auto;padding:12px 14px}
.addbtn{width:100%;background:linear-gradient(90deg,var(--cyan),var(--blue));color:#04121f;
 border:0;border-radius:9px;font-size:12px;font-weight:700;padding:9px;cursor:pointer;margin-bottom:12px}
.card{background:var(--glass);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:10px;transition:.15s}
.card:hover{border-color:var(--line2)}
.card .nm{font-weight:650;font-size:13.5px;display:flex;align-items:center;gap:7px}
.card .ct{color:var(--muted);font-size:11px;margin:4px 0 9px}
.card .acts{display:flex;gap:7px}
.card button{flex:1;font-size:11.5px;font-weight:650;padding:6px;border:0;border-radius:8px;cursor:pointer;transition:.15s}
.run{background:linear-gradient(90deg,var(--cyan),var(--blue));color:#04121f}.run:hover{filter:brightness(1.12)}
.del{background:var(--glass2);color:var(--muted);border:1px solid var(--line)!important}.del:hover{color:var(--bad);border-color:var(--bad)!important}
.pempty{color:var(--muted);font-size:12px;line-height:1.6;padding:8px 2px}
.voicewrap{padding:13px 14px;border-top:1px solid var(--line)}
.lbl{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:8px}
select{width:100%;background:var(--glass);color:var(--text);border:1px solid var(--line);
 border-radius:9px;padding:8px 10px;font-size:12.5px;cursor:pointer;outline:none}
footer{display:flex;gap:10px;padding:14px;background:rgba(8,14,26,.5);border-top:1px solid var(--line);align-items:center}
#txt{flex:1;padding:12px 15px;border-radius:13px;border:1px solid var(--line);
 background:var(--glass);color:var(--text);font-size:14px;outline:none;transition:.15s}
#txt:focus{border-color:var(--line2);box-shadow:0 0 14px -4px var(--cyan)}
.fbtn{width:44px;height:44px;border:0;border-radius:13px;cursor:pointer;font-size:17px;display:grid;place-items:center;transition:.15s}
#mic{background:var(--glass);border:1px solid var(--line);color:var(--ice)}#mic:hover{border-color:var(--line2)}
#mic.on{animation:breathe 1s infinite;background:rgba(52,224,143,.18);border-color:var(--good);color:var(--good)}
#send{background:linear-gradient(135deg,var(--cyan),var(--blue));color:#04121f}#send:hover{filter:brightness(1.12)}
.ov{position:fixed;inset:0;background:#0009;display:none;place-items:center;backdrop-filter:blur(4px);z-index:9}
.ov.show{display:grid}
.modal{background:var(--bg2);border:1px solid var(--line2);border-radius:18px;padding:24px;width:400px;max-width:90vw;
 box-shadow:0 0 40px -10px var(--cyan)}
.modal h3{font-size:17px;margin-bottom:4px;color:var(--ice)}.modal p{color:var(--muted);font-size:12.5px;margin-bottom:15px}
.modal label{font-size:12px;color:var(--ice);display:block;margin:12px 0 5px}
.modal input,.modal textarea{width:100%;background:var(--bg);color:var(--text);
 border:1px solid var(--line);border-radius:10px;padding:11px;font-size:13.5px;font-family:inherit;outline:none}
.modal input:focus,.modal textarea:focus{border-color:var(--line2)}
.modal textarea{resize:vertical;min-height:76px}
.seg{display:flex;gap:8px;margin-top:6px}
.seg label{flex:1;margin:0;text-align:center;padding:9px;border:1px solid var(--line);border-radius:9px;cursor:pointer;font-size:12.5px;color:var(--muted)}
.seg input{display:none}.seg input:checked+span{color:var(--ice)}
.seg label:has(input:checked){border-color:var(--line2);background:var(--glass);color:var(--ice)}
.mbtns{display:flex;gap:10px;margin-top:20px}
.mbtns button{flex:1;padding:12px;border:0;border-radius:11px;font-weight:700;font-size:13.5px;cursor:pointer}
.create{background:linear-gradient(90deg,var(--cyan),var(--blue));color:#04121f}.cancel{background:var(--glass2);color:var(--muted)}
.hint{font-size:11.5px;color:var(--muted);margin-top:10px;line-height:1.5}
</style></head><body>
<header>
 <div id=orb class="orb spin" title="Clic para cortar la voz" onclick=interrupt() style=cursor:pointer></div>
 <div class=brand><h1>BLUE</h1><div class=sub>ASISTENTE PERSONAL</div></div>
 <div style="text-align:right;margin-right:6px"><div id=status><span class=dot></span>En reposo</div></div>
 <button class="iconbtn stopv" id=stopvoice title="Detener voz" onclick=interrupt()>⏹</button>
 <button class=iconbtn id=panelmic title="Hablar" onclick=listen()>🎤</button>
</header>
<main>
 <div id=chat>
  <div id=log></div>
  <footer>
   <input id=txt placeholder="Escribe a Blue o pulsa el micrófono…" onkeydown="if(event.key==='Enter')send()">
   <button class=fbtn id=mic title="Hablar" onclick=listen()>🎙️</button>
   <button class=fbtn id=send title="Enviar" onclick=send()>➤</button>
  </footer>
 </div>
 <aside>
  <div class=tabs>
   <div class="tab on" id=tabP onclick="switchTab('P')">⚡ Protocolos</div>
   <div class=tab id=tabJ onclick="switchTab('J')">🗂 Proyectos</div>
   <div class=tab id=tabD onclick="switchTab('D')">📚 Docs</div>
  </div>
  <div class=listwrap>
   <button class=addbtn id=addbtn onclick=openModal()>+ Crear nuevo</button>
   <div id=cards></div>
  </div>
  <div class=voicewrap>
   <div class=lbl>Motor de voz</div>
   <select id=engine onchange=setengine() style="margin-bottom:8px"></select>
   <div class=lbl>Voz de Blue</div>
   <select id=voice onchange=setvoice()></select>
  </div>
 </aside>
</main>
<div class=ov id=ov>
 <div class=modal>
  <h3 id=mtitle>Crear protocolo</h3>
  <p>Una rutina con nombre. Descríbela en lenguaje natural y Blue la arma.</p>
  <div class=seg>
   <label><input type=radio name=kind value=protocolo checked onchange=kindChanged()><span>⚡ Protocolo</span></label>
   <label><input type=radio name=kind value=proyecto onchange=kindChanged()><span>🗂 Proyecto</span></label>
  </div>
  <label>Nombre</label>
  <input id=pname placeholder="ej. a dormir, gaming, web…">
  <label>¿Qué debe hacer?</label>
  <textarea id=pdesc placeholder="ej. abre VS Code en mi carpeta de proyectos, una terminal ahí y Spotify"></textarea>
  <div class=hint>💡 También puedes crearlo hablando: «Blue, crea un proyecto llamado X que…»</div>
  <div class=mbtns>
   <button class=cancel onclick=closeModal()>Cancelar</button>
   <button class=create onclick=createItem()>Crear</button>
  </div>
 </div>
</div>
<script>
const L={idle:['En reposo','--muted'],listening:['Escuchando…','--cyan'],
 thinking:['Pensando…','--warn'],speaking:['Hablando… (clic en el orbe para cortar)','--good']};
let lastLen=-1,tab='P',docsSig='';
function esc(t){return t.replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]))}
function switchTab(t){tab=t;['P','J','D'].forEach(x=>document.getElementById('tab'+x).classList.toggle('on',t===x));
 document.getElementById('addbtn').style.display=(t==='D')?'none':'';
 docsSig='';lastLen=-2;refresh();}
async function renderDocs(){
 let d;try{d=await (await fetch('/api/docs')).json()}catch(e){return}
 const sig=JSON.stringify(d);if(sig===docsSig)return;docsSig=sig;
 const wrap=document.getElementById('cards');
 if(!d.ready){wrap.innerHTML='<div class=pempty>El lector de documentos no está instalado todavía, Wilmer.</div>';return;}
 let h='<div class=dsec>📄 Documentos indexados ('+d.total_docs+')</div>';
 if(!d.docs.length)h+='<div class=pempty>Nada indexado aún. Suelta archivos en la carpeta de un curso y di «indexa mis apuntes de X».</div>';
 d.docs.forEach(g=>{h+='<div class=dgrp><h4>'+esc(g.label)+'<span>'+g.items.length+'</span></h4>';
  g.items.forEach(it=>{h+='<div class=ditem><span class=ti title="'+esc(it.title)+'">'+esc(it.title)+'</span><span class=ch>'+it.chunks+' frag</span></div>';});
  h+='</div>';});
 h+='<div class=dsec style="margin-top:15px">🧠 Memoria ('+d.total_facts+')</div>';
 if(!d.memory.length)h+='<div class=pempty>Sin hechos guardados todavía.</div>';
 d.memory.forEach(g=>{h+='<div class=dgrp><h4>'+esc(g.label)+'<span>'+g.facts.length+'</span></h4>';
  g.facts.forEach(f=>{h+='<div class=mfact>'+esc(f)+'</div>';});
  h+='</div>';});
 wrap.innerHTML=h;
}
function kindChanged(){const k=document.querySelector('input[name=kind]:checked').value;
 document.getElementById('mtitle').textContent='Crear '+k;}
async function refresh(){
 let s;try{s=await (await fetch('/api/state')).json()}catch(e){return}
 const orb=document.getElementById('orb');
 orb.className='orb spin'+(s.status!=='idle'?' pulse '+s.status:'');
 const st=document.getElementById('status'),meta=L[s.status]||[s.status,'--muted'];
 st.innerHTML='<span class=dot style="background:var('+meta[1]+');box-shadow:0 0 8px var('+meta[1]+')"></span>'+meta[0];
 document.getElementById('mic').classList.toggle('on',s.status==='listening');
 document.getElementById('stopvoice').style.opacity=s.status==='speaking'?'1':'.4';
 const log=document.getElementById('log');
 if(s.log.length!==lastLen){
  if(!s.log.length){log.innerHTML='<div class=empty><div class=big>🔵</div><b>Hola, soy Blue.</b><br>Háblame o escríbeme. Prueba: «abre Spotify», «quiero trabajar», «crea un proyecto».</div>';}
  else{log.innerHTML=s.log.map(m=>{const u=!m.role.startsWith('asist')&&!m.role.startsWith('blue');
   return '<div class="row '+(u?'u':'a')+'"><div class="av '+(u?'u':'a')+'">'+(u?'🧑':'🔵')+'</div>'+
   '<div><div class=bubble>'+esc(m.text)+'</div><div class=time>'+esc(m.role)+' · '+m.time+'</div></div></div>'}).join('');}
  log.scrollTop=log.scrollHeight;lastLen=s.log.length;
 }
 if(tab==='D'){renderDocs();}else{
 const wrap=document.getElementById('cards');
 const items=(tab==='P'?s.protocols:s.projects)||[];
 const noun=tab==='P'?'protocolo':'proyecto',ico=tab==='P'?'⚡':'🗂';
 wrap.innerHTML=items.length?items.map(p=>'<div class=card><div class=nm>'+ico+' '+esc(p.name)+'</div>'+
  '<div class=ct>'+(esc(p.description||'')||p.steps+' paso'+(p.steps!=1?'s':''))+'</div>'+
  '<div class=acts><button class=run onclick="runp(\''+esc(p.name)+'\')">▶ Activar</button>'+
  '<button class=del onclick="delp(\''+esc(p.name)+'\')">🗑</button></div></div>').join('')
  :'<div class=pempty>Aún no tienes '+noun+'s.<br>Pulsa «+ Crear nuevo».</div>';
 }
 const e=document.getElementById('engine');
 if(e.dataset.eng!==s.engine){
  e.innerHTML=Object.entries(s.engines).map(([id,nm])=>
   '<option value="'+id+'"'+(id===s.engine?' selected':'')+'>'+nm+'</option>').join('');
  e.dataset.eng=s.engine;
 }
 const v=document.getElementById('voice');
 if(v.dataset.eng!==s.engine){
  v.innerHTML=Object.entries(s.voices).map(([id,nm])=>
   '<option value="'+id+'"'+(id===s.voice?' selected':'')+'>'+nm+'</option>').join('');
  v.dataset.eng=s.engine;
 }
}
async function post(u,b){await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})});}
async function send(){const t=document.getElementById('txt');if(!t.value.trim())return;const v=t.value;t.value='';
 await post('/api/command',{text:v});lastLen=-1;refresh();setTimeout(refresh,400);setTimeout(refresh,1100);}
async function listen(){await post('/api/listen');}
async function interrupt(){await post('/api/interrupt');refresh();}
async function runp(n){await post('/api/protocol/run',{name:n});lastLen=-1;setTimeout(refresh,300);setTimeout(refresh,1200);}
async function delp(n){if(confirm('¿Borrar "'+n+'"?')){await post('/api/protocol/delete',{name:n});lastLen=-2;refresh();}}
async function setvoice(){await post('/api/voice',{voice:document.getElementById('voice').value});}
async function setengine(){const e=document.getElementById('engine').value;
 await post('/api/engine',{engine:e});
 document.getElementById('voice').dataset.eng='';   // forzar rebuild de voces
 setTimeout(refresh,150);}
function openModal(){kindChanged();document.getElementById('ov').classList.add('show');document.getElementById('pname').focus();}
function closeModal(){document.getElementById('ov').classList.remove('show');document.getElementById('pname').value='';document.getElementById('pdesc').value='';}
async function createItem(){const n=document.getElementById('pname').value.trim(),d=document.getElementById('pdesc').value.trim();
 const k=document.querySelector('input[name=kind]:checked').value;
 if(!n||!d){alert('Pon nombre y descripción.');return;}
 await post('/api/command',{text:'crea un '+k+' llamado '+n+' que '+d});closeModal();lastLen=-2;setTimeout(refresh,600);}
async function stopit(){if(confirm('¿Apagar a Blue? (dejará de responder a Super+J)')){await post('/api/stop');
 document.body.innerHTML='<div style="display:grid;place-items:center;height:100vh;color:#7d93b8">Blue se ha apagado. Puedes cerrar esta ventana.</div>';}}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal()});
setInterval(refresh,1000);refresh();
</script></body></html>"""

# ----------------------------------------------------------------- burbuja Super+J
BUBBLE = r"""<!doctype html><html lang=es><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Blue</title>
<style>__BASE__
body{display:flex;flex-direction:column;align-items:center;justify-content:center;
 padding:18px;text-align:center;-webkit-app-region:drag;user-select:none}
.bigorb{width:108px;height:108px;margin-top:6px}
#st{margin-top:22px;font-size:14px;letter-spacing:.4px;min-height:20px;color:var(--ice)}
#last{margin-top:8px;font-size:11.5px;color:var(--muted);line-height:1.45;max-height:54px;overflow:hidden;
 display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical}
.btns{display:flex;gap:10px;margin-top:auto;width:100%;-webkit-app-region:no-drag}
.btns button{flex:1;padding:11px 0;border:0;border-radius:12px;font-size:13px;font-weight:700;cursor:pointer;transition:.15s}
.mic{background:var(--glass);border:1px solid var(--line)!important;color:var(--ice)}
.stop{background:rgba(255,209,102,.14);border:1px solid rgba(255,209,102,.4)!important;color:var(--warn)}
.close{background:var(--glass);border:1px solid var(--line)!important;color:var(--muted)}
.btns button:hover{filter:brightness(1.15)}
.title{position:absolute;top:14px;left:0;right:0;font-size:13px;font-weight:800;letter-spacing:3px;
 color:var(--ice);text-shadow:0 0 16px rgba(79,227,255,.5)}
</style></head><body>
<div class=title>BLUE</div>
<div id=orb class="orb spin bigorb"></div>
<div id=st>En reposo</div>
<div id=last></div>
<div class=btns>
 <button class=mic title="Hablar de nuevo" onclick=listen()>🎙️ Hablar</button>
 <button class=stop title="Detener voz" onclick=interrupt()>⏹ Detener</button>
 <button class=close title="Cerrar burbuja" onclick=closeBubble()>✕</button>
</div>
<script>
const L={idle:['En reposo','--muted'],listening:['Escuchando…','--cyan'],
 thinking:['Pensando…','--warn'],speaking:['Hablando…','--good']};
async function post(u){await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});}
function listen(){post('/api/listen');}
function interrupt(){post('/api/interrupt');}
function closeBubble(){post('/api/closebubble');setTimeout(()=>window.close(),150);}
async function refresh(){
 let s;try{s=await (await fetch('/api/state')).json()}catch(e){return}
 const orb=document.getElementById('orb');
 orb.className='orb spin bigorb'+(s.status!=='idle'?' pulse '+s.status:'');
 const meta=L[s.status]||[s.status,'--muted'];
 document.getElementById('st').textContent=meta[0];
 const last=[...s.log].reverse().find(m=>m.role.startsWith('asist')||m.role.startsWith('blue'));
 document.getElementById('last').textContent=last?last.text:'';
}
setInterval(refresh,500);refresh();
</script></body></html>"""

PAGE = PAGE.replace("__BASE__", BASE_CSS)
BUBBLE = BUBBLE.replace("__BASE__", BASE_CSS)


def _split_protocols():
    """Devuelve (protocolos, proyectos) como listas ligeras para la UI.
    'Proyectos' incluye todos los contenedores de contexto: proyectos, cursos,
    trabajos y estudio externo (ver study.CONTAINER_CATS)."""
    try:
        import study
        containers = study.CONTAINER_CATS | {"proyecto"}
    except Exception:
        containers = {"proyecto"}
    data = protocols.load_protocols()
    pro, proj = [], []
    for p in data.values():
        item = {"name": p["name"], "description": p.get("description", ""),
                "steps": len(p.get("steps", [])),
                "category": p.get("category", "")}
        (proj if p.get("category") in containers else pro).append(item)
    return pro, proj


def create_app(assistant):
    app = Flask(__name__)

    @app.get("/")
    def index():
        return PAGE

    @app.get("/bubble")
    def bubble():
        return BUBBLE

    @app.get("/api/state")
    def state():
        snap = store.snapshot()
        pro, proj = _split_protocols()
        snap["protocols"], snap["projects"] = pro, proj
        engine = assistant.cfg.get("tts", "kokoro")
        snap["engine"] = engine
        snap["engines"] = ENGINE_LABELS
        if engine == "kokoro":
            snap["voices"] = KOKORO_VOICES
            snap["voice"] = assistant.cfg.get("kokoro_voice", "ef_dora")
        elif engine == "edge":
            snap["voices"] = EDGE_VOICES
            snap["voice"] = assistant.cfg.get("edge_voice", "es-MX-DaliaNeural")
        else:
            snap["voices"] = {p.name: p.name for p in VOICES_DIR.glob("*.onnx")}
            snap["voice"] = assistant.cfg.get("voice", "")
        return jsonify(snap)

    @app.post("/api/command")
    def command():
        text = (request.json or {}).get("text", "")
        threading.Thread(target=assistant.handle_text, args=(text,),
                         kwargs={"speak": True}, daemon=True).start()
        return jsonify(ok=True)

    @app.post("/api/listen")
    def listen():
        assistant.stop_speaking()          # barge-in: corta la voz si habla
        if FIFO.exists():
            try:
                with open(FIFO, "w") as f:
                    f.write("listen\n")
            except OSError:
                pass
        return jsonify(ok=True)

    @app.post("/api/interrupt")
    def interrupt():
        assistant.stop_speaking()
        return jsonify(ok=True)

    @app.post("/api/closebubble")
    def closebubble():
        _close_window_class("blue-bubble")
        return jsonify(ok=True)

    @app.get("/api/docs")
    def docs_api():
        """Inventario para la pestaña 📚 Docs: documentos indexados y hechos de
        memoria, agrupados por curso/proyecto (o 'General' si son globales)."""
        import rag
        import memory
        data = protocols.load_protocols()
        name_of = {k: v.get("name", k) for k, v in data.items()}

        def label_of(key):
            return "General" if not key else name_of.get(key, key)

        dgroups = {}
        for d in (rag.inventory() if rag.available() else []):
            dgroups.setdefault(label_of(d["project"]), []).append(
                {"title": d["title"], "chunks": d["chunks"]})
        mgroups = {}
        for m in memory.inventory():
            mgroups.setdefault(label_of(m["project"]), []).append(m["text"])
        return jsonify(
            ready=rag.available(),
            docs=[{"label": k, "items": v} for k, v in sorted(dgroups.items())],
            memory=[{"label": k, "facts": v} for k, v in sorted(mgroups.items())],
            total_docs=sum(len(v) for v in dgroups.values()),
            total_facts=sum(len(v) for v in mgroups.values()))

    @app.post("/api/protocol/run")
    def proto_run():
        name = (request.json or {}).get("name", "")
        threading.Thread(target=lambda: assistant.handle_text(
            f"ejecuta el protocolo {name}", speak=True), daemon=True).start()
        return jsonify(ok=True)

    @app.post("/api/protocol/delete")
    def proto_del():
        name = (request.json or {}).get("name", "")
        protocols.delete_protocol(name)
        return jsonify(ok=True)

    @app.post("/api/voice")
    def set_voice():
        v = (request.json or {}).get("voice", "")
        engine = assistant.cfg.get("tts", "kokoro")
        if engine == "kokoro" and v in KOKORO_VOICES:
            assistant.cfg["kokoro_voice"] = v
            _persist_kv("kokoro_voice", v)
        elif engine == "edge" and v in EDGE_VOICES:
            assistant.cfg["edge_voice"] = v
            _persist_kv("edge_voice", v)
        elif engine == "piper" and (VOICES_DIR / v).exists():
            assistant.cfg["voice"] = v
            _persist_kv("voice", v)
        return jsonify(ok=True)

    @app.post("/api/engine")
    def set_engine():
        e = (request.json or {}).get("engine", "")
        if e in ENGINE_LABELS:
            assistant.cfg["tts"] = e
            _persist_kv("tts", e)
        return jsonify(ok=True)

    @app.post("/api/stop")
    def stop():
        assistant.stop_speaking()          # corta la voz en curso
        subprocess.run(["pkill", "-x", "paplay"], check=False)
        def _bye():
            try:
                import lines
                assistant.speak(lines.goodbye())   # se despide con personalidad
            except Exception:
                pass
            os._exit(0)
        threading.Thread(target=_bye, daemon=True).start()
        return jsonify(ok=True)

    return app


def _close_window_class(cls: str):
    import json
    out = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True)
    try:
        for c in json.loads(out.stdout):
            if c.get("class") == cls and c.get("address"):
                subprocess.run(["hyprctl", "dispatch", "closewindow",
                                f"address:{c['address']}"], check=False)
    except Exception:
        pass


def _persist_kv(key: str, val: str):
    f = config_mod.CONFIG_FILE
    try:
        txt = f.read_text()
        if re.search(rf'(?m)^{key}\s*=', txt):
            txt = re.sub(rf'(?m)^{key}\s*=.*$', f'{key} = "{val}"', txt)
        else:
            txt += f'\n{key} = "{val}"\n'
        f.write_text(txt)
    except OSError:
        pass


def run_server(assistant):
    # La burbuja y el panel piden /api/state UNA VEZ POR SEGUNDO cada uno. El
    # log de acceso de Werkzeug escribia una linea por cada peticion: 86.400
    # lineas al dia de puro ruido que sepultaban lo unico que importa ahi
    # —los avisos de cerebro caido y los tiempos de cada turno—. El 31/08/2026
    # /tmp/jd.log tenia 575 KB y practicamente todo era esto.
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = create_app(assistant)
    app.run(host="127.0.0.1", port=PORT, threaded=True,
            use_reloader=False, debug=False)
