// web_ui.cpp - страница интерфейса. Работает без интернета: нет CDN, шрифтов и внешних скриптов.
#include "web_ui.h"

static const char INDEX_HTML[] PROGMEM = R"rawliteral(<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESP32 Барограф</title>
<style>
:root{--bg:#f2f5f9;--card:#fff;--fg:#1c2733;--mut:#6b7a8a;--acc:#1e88e5;--grid:#dde4ec;--ok:#2e9e5b;--bad:#d9534f;--warn:#e69500}
@media(prefers-color-scheme:dark){:root{--bg:#0f151c;--card:#18212b;--fg:#e7edf3;--mut:#8fa0b1;--acc:#4da3ff;--grid:#2a3644;--ok:#4cc27f;--bad:#ff6b66;--warn:#ffb340}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
header{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--card);border-bottom:1px solid var(--grid)}
header h1{font-size:18px;margin:0}
#conn{font-size:13px;color:var(--ok)}#conn.off{color:var(--bad)}
nav{display:flex;gap:4px;padding:8px 10px;overflow-x:auto;background:var(--card);border-bottom:1px solid var(--grid)}
nav button{flex:1;min-width:84px}
button,select,input{font:inherit;color:var(--fg)}
button{background:var(--bg);border:1px solid var(--grid);border-radius:8px;padding:8px 12px;cursor:pointer}
button.on{background:var(--acc);border-color:var(--acc);color:#fff}
button.pri{background:var(--acc);border-color:var(--acc);color:#fff}
input,select{background:var(--bg);border:1px solid var(--grid);border-radius:8px;padding:8px;width:100%}
main{max-width:980px;margin:0 auto;padding:12px}
.tab{display:none}.tab.on{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--grid);border-radius:12px;padding:12px 14px;margin-bottom:10px}
.grid .card{margin:0}
.lbl{font-size:13px;color:var(--mut)}
.big{font-size:34px;font-weight:600;line-height:1.15}
.big small{font-size:15px;font-weight:400;color:var(--mut)}
.mid{font-size:22px;font-weight:600}
.row{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.row>*{flex:0 0 auto}
canvas{width:100%;height:320px;display:block;touch-action:pan-y}
#tip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--grid);border-radius:8px;padding:4px 8px;font-size:13px;display:none;white-space:nowrap;box-shadow:0 2px 8px #0003}
.chartbox{position:relative}
.stat{display:flex;gap:16px;flex-wrap:wrap;font-size:14px;color:var(--mut);margin-top:8px}
.fc{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.fc svg{width:140px;height:140px}
.bar{height:10px;border-radius:5px;background:var(--grid);overflow:hidden;margin:4px 0 10px}
.bar i{display:block;height:100%}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:6px 4px;border-bottom:1px solid var(--grid);text-align:left}
tr.net{cursor:pointer}tr.net:hover{background:var(--bg)}
label{display:block;font-size:13px;color:var(--mut);margin:8px 0 3px}
.msg{font-size:14px;margin-top:8px}.ok{color:var(--ok)}.err{color:var(--bad)}.warn{color:var(--warn)}
code{background:var(--bg);padding:1px 5px;border-radius:5px;font-size:13px}
.api h3{margin:12px 0 4px;font-size:15px}.api p{margin:2px 0;font-size:14px;color:var(--mut)}
</style></head><body>
<header><h1>ESP32 Барограф</h1><span id="conn">●&nbsp;онлайн</span></header>
<nav id="nav">
<button data-tab="home" class="on">Главная</button><button data-tab="graphs">Графики</button>
<button data-tab="fc">Прогноз</button><button data-tab="set">Настройки</button><button data-tab="api">API</button>
</nav>
<main>
<div id="timewarn" class="card warn" style="display:none"></div>

<section id="tab-home" class="tab on">
<div class="grid">
<div class="card"><div class="lbl">Давление</div><div class="big"><span id="p">--</span> <small>мм рт. ст.</small></div></div>
<div class="card"><div class="lbl">Температура</div><div class="big"><span id="t">--</span> <small>°C</small></div></div>
<div class="card"><div class="lbl">Влажность</div><div class="big"><span id="h">--</span> <small id="hu">%</small></div></div>
<div class="card"><div class="lbl">Тренд</div><div class="big"><span id="tr">--</span> <small>мм рт. ст./ч</small></div></div>
<div class="card"><div class="lbl">Время</div><div class="mid" id="clk">--:--:--</div></div>
<div class="card"><div class="lbl">Дата</div><div class="mid" id="dt">--.--.----</div></div>
<div class="card"><div class="lbl">Состояние Wi-Fi</div><div class="mid" id="wf">--</div></div>
<div class="card"><div class="lbl">SD</div><div class="mid" id="sd">--</div></div>
</div>
<div class="row" style="margin-top:12px"><button id="btnMeasure" class="pri">Измерить сейчас</button><span id="mres" class="msg"></span></div>
</section>

<section id="tab-graphs" class="tab">
<div class="row" id="periods"></div>
<div class="row" id="metrics"></div>
<div class="card"><div class="chartbox"><canvas id="cv"></canvas><div id="tip"></div></div><div class="stat" id="cstat"></div></div>
</section>

<section id="tab-fc" class="tab">
<div class="card"><div class="fc"><div id="fcicon"></div><div>
<div class="lbl">Прогноз на ближайшие часы</div><div class="mid" id="fcsum">--</div>
<div id="fcdet" class="lbl" style="max-width:420px"></div>
<div style="margin-top:8px"><span class="lbl">Тренд давления:</span> <b id="fctr">--</b></div>
<div><span class="lbl">Скорость:</span> <b id="fcrate">--</b></div></div></div></div>
<div class="card"><div class="lbl">Вероятность ухудшения: <b id="pw">--</b> %</div><div class="bar"><i id="pwb" style="width:0;background:var(--bad)"></i></div>
<div class="lbl">Вероятность улучшения: <b id="pb">--</b> %</div><div class="bar"><i id="pbb" style="width:0;background:var(--ok)"></i></div></div>
<div class="card"><div class="lbl">Скорость изменения давления по интервалам, мм рт. ст./ч</div>
<table><tr><th>10 мин</th><th>30 мин</th><th>1 час</th><th>3 часа</th><th>6 часов</th></tr><tr id="rates"></tr></table>
<div class="lbl" style="margin-top:8px">Прогноз рассчитывается только по локальным данным барометра (линейная регрессия по окнам, без внешних сервисов). Давление измеряется на высоте установки, поэтому важна динамика, а не абсолютное значение.</div></div>
</section>

<section id="tab-set" class="tab">
<div class="card"><h3 style="margin-top:0">Wi-Fi</h3>
<div class="lbl">Текущая сеть: <b id="sSsid">--</b> · IP: <b id="sIp">--</b> · RSSI: <b id="sRssi">--</b> · Статус: <b id="sWf">--</b></div>
<div class="row" style="margin-top:10px"><button id="btnScan">Сканировать сети</button><span id="scanmsg" class="msg"></span></div>
<table id="nets" style="display:none"><thead><tr><th>SSID</th><th>RSSI</th><th>Канал</th><th>Защита</th></tr></thead><tbody></tbody></table>
<label>SSID</label><input id="inSsid" maxlength="32" autocomplete="off">
<label>Пароль (пустое поле — не менять; для новой открытой сети оставьте пустым)</label><input id="inPass" type="password" maxlength="63" autocomplete="new-password">
<div class="row" style="margin-top:10px"><button id="btnWifi" class="pri">Сохранить</button></div><div id="wmsg" class="msg"></div></div>

<div class="card"><h3 style="margin-top:0">Измерения</h3>
<label>Период измерения</label><select id="inMeas"></select>
<label>Период записи в историю (измерения между записями усредняются)</label><select id="inRec"></select>
<div class="row" style="margin-top:10px"><button id="btnInt" class="pri">Сохранить</button></div><div id="imsg" class="msg"></div></div>

<div class="card"><h3 style="margin-top:0">SD</h3>
<div>Статус: <b id="sdSt">--</b></div><div>Файл: <b id="sdFile">barograph.csv</b></div>
<div>Размер файла: <b id="sdSize">--</b> · Карта: <b id="sdCard">--</b></div>
<div>История в ОЗУ: <b id="hist">--</b> · Хранилище: <b id="stor">--</b></div>
<div class="row" style="margin-top:8px"><a href="/api/export.csv"><button>Скачать историю (CSV)</button></a></div></div>

<div class="card"><h3 style="margin-top:0">Датчик</h3><div>Тип: <b id="seType">--</b></div><div>I2C: <b id="seAddr">--</b></div><div>Состояние: <b id="seSt">--</b></div></div>

<div class="card"><h3 style="margin-top:0">Время</h3>
<div>Дата: <b id="tmD">--</b> · Время: <b id="tmT">--</b></div><div>NTP: <b id="tmN">--</b></div>
<div class="row" style="margin-top:8px"><button id="btnTime">Установить время с этого устройства</button></div><div id="tmsg" class="msg"></div></div>
<div class="card"><div class="lbl">Прошивка: <span id="fw">--</span> · Свободно ОЗУ: <span id="heap">--</span> · Работает: <span id="up">--</span></div></div>
</section>

<section id="tab-api" class="tab"><div class="card api">
<h3>GET <a href="/api/current">/api/current</a></h3><p>Текущие значения (давление в мм рт. ст.), тренд.</p>
<h3>GET <a href="/api/history?hours=3">/api/history?hours=3&amp;max=400</a></h3><p>История; hours — 0.5…72; max — максимум точек (downsampling).</p>
<h3>GET|POST <a href="/api/measure">/api/measure</a></h3><p>Немедленное измерение; store=1 — добавить в историю.</p>
<h3>GET <a href="/api/status">/api/status</a></h3><p>Состояние устройства.</p>
<h3>GET <a href="/api/forecast">/api/forecast</a></h3><p>Тренд и прогноз.</p>
<h3>GET|POST <a href="/api/settings">/api/settings</a></h3><p>Параметры: ssid, password, measure_interval_s, record_interval_s (form или JSON).</p>
<h3>GET <a href="/api/wifi/scan?start=1">/api/wifi/scan</a></h3><p>start=1 запускает сканирование, затем опрашивайте без параметра.</p>
<h3>GET|POST <a href="/api/time">/api/time</a></h3><p>POST epoch=… — установить время (если нет NTP).</p>
<h3>GET <a href="/api/export.csv">/api/export.csv</a></h3><p>История в CSV. Подробная документация — в README.</p>
</div></section>
</main>

<script>
"use strict";
const $=s=>document.querySelector(s);
let TZ=10800,devDelta=null,ST={},autoTime=false,hours=1,metric='pressure',chart=null,tab='home';
const PER=[[0.5,'30 мин'],[1,'1 час'],[3,'3 часа'],[6,'6 часов'],[12,'12 часов'],[48,'48 часов'],[72,'72 часа']];
const MET={pressure:['Давление','мм рт. ст.',2],temperature:['Температура','°C',1],humidity:['Влажность','%',1]};
const pad=n=>String(n).padStart(2,'0');
async function jget(u){const r=await fetch(u,{cache:'no-store'});if(!r.ok)throw new Error(r.status);return r.json()}
async function jpost(u,obj){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(obj).toString()});return r.json()}
function conn(ok){const c=$('#conn');c.className=ok?'':'off';c.innerHTML=ok?'●&nbsp;онлайн':'●&nbsp;нет связи'}
function fmt(ts,withDate){const d=new Date((ts+TZ)*1000);return(withDate?pad(d.getUTCDate())+'.'+pad(d.getUTCMonth()+1)+' ':'')+pad(d.getUTCHours())+':'+pad(d.getUTCMinutes())}

/* ---------- иконки погоды ---------- */
function icon(n){
 let rays='';for(let i=0;i<8;i++)rays+=`<line x1="50" y1="9" x2="50" y2="21" transform="rotate(${i*45} 50 50)"/>`;
 const sun=`<g stroke="#ffb300" stroke-width="5" stroke-linecap="round">${rays}</g><circle cx="50" cy="50" r="17" fill="#ffb300"/>`;
 const cl=(c,dy)=>`<g fill="${c}" transform="translate(0,${dy||0})"><circle cx="34" cy="60" r="14"/><circle cx="52" cy="50" r="18"/><circle cx="70" cy="60" r="13"/><rect x="34" y="60" width="36" height="14"/></g>`;
 let b='';
 if(n==='sun')b=sun;
 else if(n==='partly')b=`<g transform="translate(-12,-14) scale(.7)">${sun}</g>`+cl('#b0bec5',6);
 else if(n==='cloud')b=cl('#90a4ae',0);
 else if(n==='rain'){b=cl('#78909c',-12);[36,52,68].forEach(x=>b+=`<line x1="${x}" y1="68" x2="${x-5}" y2="86" stroke="#4fc3f7" stroke-width="4" stroke-linecap="round"/>`)}
 else if(n==='storm')b=cl('#546e7a',-12)+`<polygon points="52,60 40,82 50,82 45,98 63,73 52,73 58,60" fill="#ffd600"/>`;
 else if(n==='snow'){b=cl('#90a4ae',-12);[[38,78],[52,86],[66,78]].forEach(p=>b+=`<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="#90caf9"/>`)}
 else if(n==='wind')b=`<g fill="none" stroke="#90a4ae" stroke-width="5" stroke-linecap="round"><path d="M10 35H60a9 9 0 1 0-9-9"/><path d="M10 52H78a10 10 0 1 1-10 10"/><path d="M10 69H48a8 8 0 1 1-8 8"/></g>`;
 else b=`<circle cx="50" cy="50" r="30" fill="none" stroke="#90a4ae" stroke-width="5"/><text x="50" y="62" text-anchor="middle" font-size="36" fill="#90a4ae">?</text>`;
 return `<svg viewBox="0 0 100 100" aria-hidden="true">${b}</svg>`}

/* ---------- главная ---------- */
async function refreshCurrent(){
 try{const c=await jget('/api/current');conn(true);
  const ok=c.state==='ok';
  $('#p').textContent=ok?c.pressure.toFixed(1):'--';
  $('#t').textContent=ok?c.temperature.toFixed(1):'--';
  $('#h').textContent=ok&&c.humidity_valid?Math.round(c.humidity):'N/A';$('#hu').style.display=ok&&c.humidity_valid?'':'none';
  const tr=c.trend_mmhg_h;$('#tr').textContent=tr==null?'--':((tr>0?'+':'')+tr.toFixed(1));
  if(c.state==='sensor_not_found')$('#p').textContent='нет датчика';
 }catch(e){conn(false)}}
async function refreshStatus(){
 try{ST=await jget('/api/status');conn(true);TZ=ST.tz_offset_s;
  devDelta=ST.epoch?ST.epoch-Date.now()/1000:null;
  $('#wf').textContent=ST.wifi?'CONNECTED':(ST.ap?'AP MODE':'DISCONNECTED');
  $('#sd').textContent=ST.sd?'ONLINE':'OFFLINE';
  const w=$('#timewarn');
  if(!ST.time_synced){w.style.display='';w.textContent='Время не установлено: история не записывается. Подключите устройство к сети с интернетом или нажмите «Установить время» в настройках.';
   if(!autoTime){autoTime=true;try{await jpost('/api/time',{epoch:Math.floor(Date.now()/1000)})}catch(e){}}}
  else if(ST.time_source==='browser'){w.style.display='';w.textContent='Время установлено с вашего устройства (нет синхронизации NTP).'}
  else w.style.display='none';
  fillStatus();
 }catch(e){conn(false)}}
function tick(){if(devDelta===null)return;const e=Date.now()/1000+devDelta,d=new Date((e+TZ)*1000);
 const t=pad(d.getUTCHours())+':'+pad(d.getUTCMinutes())+':'+pad(d.getUTCSeconds()),dt=pad(d.getUTCDate())+'.'+pad(d.getUTCMonth()+1)+'.'+d.getUTCFullYear();
 $('#clk').textContent=t;$('#dt').textContent=dt;$('#tmT').textContent=t;$('#tmD').textContent=dt}
setInterval(tick,1000);
$('#btnMeasure').onclick=async()=>{const m=$('#mres');m.textContent='...';m.className='msg';
 try{const r=await fetch('/api/measure',{method:'POST'});const j=await r.json();
  if(j.success){m.className='msg ok';m.textContent=j.pressure.toFixed(2)+' мм рт. ст., '+j.temperature.toFixed(1)+' °C';refreshCurrent()}
  else{m.className='msg err';m.textContent='Ошибка: '+j.error}}catch(e){m.className='msg err';m.textContent='Нет связи'}};

/* ---------- графики ---------- */
PER.forEach(p=>{const b=document.createElement('button');b.textContent=p[1];b.dataset.h=p[0];if(p[0]===hours)b.className='on';
 b.onclick=()=>{hours=p[0];[...$('#periods').children].forEach(x=>x.className=x===b?'on':'');loadChart()};$('#periods').appendChild(b)});
Object.keys(MET).forEach(k=>{const b=document.createElement('button');b.textContent=MET[k][0];if(k===metric)b.className='on';
 b.onclick=()=>{metric=k;[...$('#metrics').children].forEach(x=>x.className=x===b?'on':'');drawChart(-1)};$('#metrics').appendChild(b)});
let HIST=[];
async function loadChart(){try{const j=await jget('/api/history?hours='+hours+'&max=500');HIST=j.data;drawChart(-1)}catch(e){HIST=[];drawChart(-1)}}
function css(n){return getComputedStyle(document.documentElement).getPropertyValue(n).trim()}
function drawChart(hi){
 const cv=$('#cv'),dpr=window.devicePixelRatio||1,W=cv.clientWidth,H=cv.clientHeight;
 if(!W)return;cv.width=W*dpr;cv.height=H*dpr;const g=cv.getContext('2d');g.setTransform(dpr,0,0,dpr,0,0);g.clearRect(0,0,W,H);
 const m=MET[metric],pts=HIST.filter(p=>p[metric]!=null),fg=css('--mut'),gr=css('--grid'),ac=css('--acc');
 g.font='12px system-ui,sans-serif';
 if(pts.length<2){g.fillStyle=fg;g.textAlign='center';g.fillText('Недостаточно данных для графика',W/2,H/2);chart=null;$('#cstat').textContent='';return}
 let mn=Infinity,mx=-Infinity,sum=0;pts.forEach(p=>{const v=p[metric];if(v<mn)mn=v;if(v>mx)mx=v;sum+=v});
 let span=mx-mn,minSpan=metric==='pressure'?1:(metric==='temperature'?1:4);if(span<minSpan){const c=(mx+mn)/2;mn=c-minSpan/2;mx=c+minSpan/2}else{const pd=span*.1;mn-=pd;mx+=pd}
 const L=50,R=10,T=10,B=24,pw=W-L-R,ph=H-T-B,t0=pts[0].timestamp,t1=pts[pts.length-1].timestamp,ts=Math.max(1,t1-t0);
 const X=t=>L+(t-t0)/ts*pw,Y=v=>T+(1-(v-mn)/(mx-mn))*ph;
 g.strokeStyle=gr;g.fillStyle=fg;g.lineWidth=1;g.textAlign='right';
 for(let i=0;i<=4;i++){const v=mn+(mx-mn)*i/4,y=Y(v);g.beginPath();g.moveTo(L,y);g.lineTo(W-R,y);g.stroke();g.fillText(v.toFixed(m[2]>1?1:1),L-5,y+4)}
 g.textAlign='center';const wd=ts>86400;
 for(let i=0;i<=4;i++){const t=t0+ts*i/4,x=X(t);g.beginPath();g.moveTo(x,T);g.lineTo(x,T+ph);g.stroke();g.fillText(fmt(t,wd||hours>=24),Math.min(Math.max(x,L+22),W-R-22),H-6)}
 g.strokeStyle=ac;g.lineWidth=2;g.beginPath();pts.forEach((p,i)=>{const x=X(p.timestamp),y=Y(p[metric]);i?g.lineTo(x,y):g.moveTo(x,y)});g.stroke();
 chart={pts,X,Y,L,R,T,ph,W};
 if(hi>=0){const p=pts[hi],x=X(p.timestamp),y=Y(p[metric]);g.strokeStyle=fg;g.lineWidth=1;g.beginPath();g.moveTo(x,T);g.lineTo(x,T+ph);g.stroke();g.fillStyle=ac;g.beginPath();g.arc(x,y,4,0,7);g.fill()}
 const first=pts[0][metric],last=pts[pts.length-1][metric],d=last-first;
 $('#cstat').innerHTML=`<span>Мин: <b>${Math.min(...pts.map(p=>p[metric])).toFixed(m[2])}</b></span><span>Макс: <b>${Math.max(...pts.map(p=>p[metric])).toFixed(m[2])}</b></span><span>Среднее: <b>${(sum/pts.length).toFixed(m[2])}</b></span><span>Изменение: <b>${(d>0?'+':'')+d.toFixed(m[2])}</b> ${m[1]}</span><span>Точек: ${pts.length}</span>`}
const cvEl=$('#cv');
function hover(ev){if(!chart)return;const r=cvEl.getBoundingClientRect(),x=ev.clientX-r.left;let bi=0,bd=1e9;
 chart.pts.forEach((p,i)=>{const d=Math.abs(chart.X(p.timestamp)-x);if(d<bd){bd=d;bi=i}});
 drawChart(bi);const p=chart.pts[bi],tip=$('#tip'),m=MET[metric];
 tip.style.display='block';tip.textContent=fmt(p.timestamp,true)+' · '+p[metric].toFixed(m[2])+' '+m[1];
 tip.style.left=Math.min(Math.max(chart.X(p.timestamp)-60,0),chart.W-170)+'px';tip.style.top='4px'}
cvEl.addEventListener('pointermove',hover);cvEl.addEventListener('pointerdown',hover);
cvEl.addEventListener('pointerleave',()=>{$('#tip').style.display='none';drawChart(-1)});
window.addEventListener('resize',()=>{if(tab==='graphs')drawChart(-1)});

/* ---------- прогноз ---------- */
async function loadForecast(){try{const f=await jget('/api/forecast');
 $('#fcicon').innerHTML=icon(f.icon)+(f.windy?'<div style="width:50px;margin-top:-30px">'+icon('wind')+'</div>':'');
 $('#fcsum').textContent=f.summary;$('#fcdet').textContent=f.details;$('#fctr').textContent=f.trend_label;
 const r=f.rate_mmhg_h;$('#fcrate').textContent=r==null?'--':((r>0?'+':'')+r.toFixed(2)+' мм рт. ст./ч');
 $('#pw').textContent=f.valid?f.probability_worse:'--';$('#pb').textContent=f.valid?f.probability_better:'--';
 $('#pwb').style.width=(f.valid?f.probability_worse:0)+'%';$('#pbb').style.width=(f.valid?f.probability_better:0)+'%';
 const k=['10m','30m','1h','3h','6h'];$('#rates').innerHTML=k.map(x=>{const v=f.rates[x];return'<td>'+(v==null?'—':(v>0?'+':'')+v.toFixed(2))+'</td>'}).join('')
 }catch(e){conn(false)}}

/* ---------- настройки ---------- */
function opts(el,list,cur){el.innerHTML=list.map(v=>`<option value="${v[0]}"${v[0]==cur?' selected':''}>${v[1]}</option>`).join('')}
const MEAS=[[5,'5 секунд'],[10,'10 секунд'],[30,'30 секунд'],[60,'1 минута'],[300,'5 минут'],[600,'10 минут'],[1800,'30 минут'],[3600,'1 час']];
const REC=[[60,'1 минута'],[120,'2 минуты'],[300,'5 минут'],[600,'10 минут'],[1800,'30 минут'],[3600,'1 час']];
async function loadSettings(){try{const s=await jget('/api/settings');$('#inSsid').value=s.ssid;$('#inPass').value='';
 opts($('#inMeas'),MEAS,s.measure_interval_s);opts($('#inRec'),REC,s.record_interval_s)}catch(e){}}
function fillStatus(){const s=ST;if(!s.ip)return;
 $('#sSsid').textContent=s.ssid;$('#sIp').textContent=s.ip;$('#sRssi').textContent=s.wifi?s.rssi+' dBm':'—';$('#sWf').textContent=s.wifi?'CONNECTED':(s.ap?'AP':'DISCONNECTED');
 $('#sdSt').textContent=s.sd?'ONLINE':'OFFLINE';$('#sdSize').textContent=s.sd?(s.csv_bytes/1024).toFixed(1)+' КБ':'—';$('#sdCard').textContent=s.sd?s.sd_card_mb+' МБ':'—';
 $('#hist').textContent=s.history_records+' / '+s.history_capacity;$('#stor').textContent=s.storage==='sd'?'SD (CSV)':'flash (LittleFS)';
 $('#seType').textContent=s.sensor==='none'?'не найден':s.sensor;$('#seAddr').textContent=s.sensor_address||'—';$('#seSt').textContent=s.sensor_state;
 $('#tmN').textContent=s.ntp_synced?'Синхронизировано':(s.time_synced?'Не синхронизировано (время с устройства)':'Не синхронизировано');
 $('#fw').textContent=s.fw_version;$('#heap').textContent=Math.round(s.free_heap/1024)+' КБ';
 const u=s.uptime;$('#up').textContent=Math.floor(u/3600)+' ч '+Math.floor(u%3600/60)+' мин'}
$('#btnScan').onclick=async()=>{const m=$('#scanmsg');m.textContent='Сканирование...';
 try{await jget('/api/wifi/scan?start=1');let j;for(let i=0;i<20;i++){await new Promise(r=>setTimeout(r,1000));j=await jget('/api/wifi/scan');if(j.status!=='scanning')break}
  if(!j||j.status!=='done'){m.textContent='Сети не найдены';return}
  const seen={};const list=j.networks.filter(n=>seen[n.ssid]?false:(seen[n.ssid]=1)).sort((a,b)=>b.rssi-a.rssi);
  const tb=$('#nets tbody');tb.innerHTML='';list.forEach(n=>{const tr=document.createElement('tr');tr.className='net';
   [n.ssid,n.rssi+' dBm',n.channel,n.security].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.appendChild(td)});
   tr.onclick=()=>{$('#inSsid').value=n.ssid;$('#inPass').focus()};tb.appendChild(tr)});
  $('#nets').style.display='';m.textContent='Найдено сетей: '+list.length+'. Нажмите на сеть, чтобы выбрать.'}catch(e){m.textContent='Ошибка сканирования'}};
$('#btnWifi').onclick=async()=>{const m=$('#wmsg');m.className='msg';
 try{const j=await jpost('/api/settings',{ssid:$('#inSsid').value,password:$('#inPass').value});
  if(j.success){m.className='msg ok';m.textContent='Сохранено. Устройство подключается к сети. Если вы были подключены к точке доступа, найдите новый IP в мониторе порта или откройте http://esp32-barograf.local'}
  else{m.className='msg err';m.textContent='Ошибка: '+j.error}}catch(e){m.className='msg err';m.textContent='Связь прервана — вероятно, устройство переключается на новую сеть'}};
$('#btnInt').onclick=async()=>{const m=$('#imsg');
 try{const j=await jpost('/api/settings',{measure_interval_s:$('#inMeas').value,record_interval_s:$('#inRec').value});
  m.className='msg '+(j.success?'ok':'err');m.textContent=j.success?'Сохранено':'Ошибка: '+j.error}catch(e){m.className='msg err';m.textContent='Нет связи'}};
$('#btnTime').onclick=async()=>{const m=$('#tmsg');
 try{const j=await jpost('/api/time',{epoch:Math.floor(Date.now()/1000)});m.className='msg ok';
  m.textContent=j.applied?'Время установлено':'Время уже синхронизировано по NTP';refreshStatus()}catch(e){m.className='msg err';m.textContent='Ошибка'}};

/* ---------- вкладки ---------- */
function show(t){tab=t;document.querySelectorAll('.tab').forEach(e=>e.className='tab'+(e.id==='tab-'+t?' on':''));
 document.querySelectorAll('#nav button').forEach(b=>b.className=b.dataset.tab===t?'on':'');
 if(t==='graphs')loadChart();if(t==='fc')loadForecast();if(t==='set'){loadSettings();fillStatus()}}
document.querySelectorAll('#nav button').forEach(b=>b.onclick=()=>show(b.dataset.tab));
function poll(){refreshCurrent();if(tab==='fc')loadForecast();if(tab==='graphs')loadChart()}
refreshStatus();refreshCurrent();setInterval(refreshCurrent,3000);setInterval(refreshStatus,5000);setInterval(()=>{if(tab==='fc')loadForecast();if(tab==='graphs')loadChart()},30000);
</script></body></html>)rawliteral";

namespace WebUi {
  const char* indexHtml() { return INDEX_HTML; }
}
