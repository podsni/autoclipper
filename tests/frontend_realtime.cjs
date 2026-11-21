'use strict';
// Explicitly stubbed backend responses; exercises real app event handlers, no server.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this.events={}; this.style={}; this.value=''; this.disabled=false; this.hidden=false; this.className=''; this.attributes={}; this.classList={toggle(){},add(){}}; }
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(k,v){this.attributes[k]=String(v);this[k]=String(v);}
  removeAttribute(k){delete this.attributes[k];delete this[k];}
  addEventListener(k,fn){this.events[k]=fn;}
  querySelector(s){return walk(this).find(n=>s.startsWith('.')?n.className?.split(' ').includes(s.slice(1)):n.tagName===s)||null;}
  focus(){focused=this;} select(){} remove(){} showModal(){this.open=true;} close(){this.open=false;this.events.close?.();}
  click(){if(!this.disabled)return this.events.click?.({target:this,preventDefault(){}});}
}
const walk=n=>[n,...n.children.flatMap(walk)];
let focused;
const tick=async()=>{for(let i=0;i<5;i++)await new Promise(r=>setImmediate(r));};
function harness(jobs, {sse=true, deleteStatus=200, retainDeleted=false}={}) {
 const html=fs.readFileSync('static/index.html','utf8');const ids={};
 for(const [,id] of html.matchAll(/id="([^"]+)"/g))ids[id]=new Element();
 ids['empty-state'].append(new Element('h3'),new Element('p'),new Element('a'));
 const requests=[],sources=[],timers=new Map(),listeners={};let timerId=0;
 class EventSourceStub { constructor(url){this.url=url;this.events={};this.closed=false;sources.push(this);} addEventListener(k,fn){this.events[k]=fn;} close(){this.closed=true;} emit(job){this.events.job?.({data:JSON.stringify(job)});} }
 const context={document:{getElementById:id=>ids[id],createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text,children:[]}),body:new Element('body')},location:{href:'http://localhost/',origin:'http://localhost'},window:{addEventListener(k,fn){listeners[k]=fn;}},navigator:{},fetch:async(path,options={})=>{
  requests.push([path,options]);let status=200,data;
  if(options.method==='DELETE'){status=deleteStatus;if(status===200){if(!retainDeleted)jobs=jobs.filter(j=>path!==`/api/jobs/${j.id}`);data={deleted:true,id:path.split('/').at(-1),cache_retained:true};}else {data={detail:status===409?'Proyek masih aktif.':'Proyek tidak ditemukan.'};if(status===404)jobs=jobs.filter(j=>path!==`/api/jobs/${j.id}`);if(status===409)jobs=jobs.map(j=>path===`/api/jobs/${j.id}`?{...j,status:'rendering'}:j);}}
  else if(path==='/api/jobs'&&options.method==='POST') {data={...JSON.parse(options.body),id:'new-job',status:'queued',clips:[]};jobs=[data,...jobs];}
  else if(path==='/api/health') data={status:'ok',deepgram_configured:true};
  else if(path==='/api/jobs')data={jobs};
  else {data=jobs.find(j=>path===`/api/jobs/${j.id}`);if(!data){status=404;data={detail:'Proyek tidak ditemukan.'};}}
  return {ok:status<400,status,json:async()=>data};
 },setTimeout:(fn,delay)=>{const id=++timerId;timers.set(id,{fn,delay});return id;},clearTimeout:id=>timers.delete(id),AbortController,URL,Blob,console};
 if(sse)context.EventSource=EventSourceStub;
 vm.runInNewContext(fs.readFileSync('static/app.js','utf8'),context);
 return {ids,requests,sources,timers,listeners,select:async id=>{ids['project-select'].value=id;ids['project-select'].events.change({target:ids['project-select']});await tick();},runPoll:async()=>{const item=[...timers].find(([,v])=>v.delay===2000);assert.ok(item,'one 2 second fallback timer');timers.delete(item[0]);await item[1].fn();await tick();}};
}
const completed={id:'done',title:'Selesai',status:'completed',progress:100,clips:[{id:'clip-1',title:'Klip',caption:'Transkrip',video_url:'/media/clip.mp4'}]};
(async()=>{
 const h=harness([completed]);await tick();
 assert.ok(h.ids['delete-project'],'project delete control exists');
 assert.equal(h.ids['delete-project'].disabled,false);
 await h.ids['delete-project'].click();assert.equal(h.ids['delete-dialog'].open,true);
 assert.equal(focused,h.ids['delete-cancel'],'safe cancel is initially focused');
 await h.ids['delete-cancel'].click();assert.equal(h.ids['delete-dialog'].open,false);
 assert.equal(h.requests.filter(([,o])=>o.method==='DELETE').length,0,'cancel never deletes');
 await h.ids['delete-project'].click();await h.ids['delete-confirm'].click();await tick();
 assert.equal(h.requests.filter(([,o])=>o.method==='DELETE').length,1);
 assert.ok(h.requests.filter(([p,o])=>p==='/api/jobs'&&!o.method).length>=2,'history read back');
 assert.equal(h.ids['job-status'].hidden,true);assert.equal(h.ids['delete-project'].disabled,true);
 console.log('PASS delete dialog cancel, confirmation, history read-back and deselection');
 for(const status of [404,409,500]) {
  const e=harness([completed],{deleteStatus:status});await tick();
  await e.ids['delete-project'].click();await e.ids['delete-confirm'].click();await tick();
  assert.equal(e.ids['delete-error'].hidden,false,`HTTP ${status} is visible`);
  assert.equal(e.ids['delete-dialog'].open,true,'error does not silently dismiss confirmation');
  assert.equal(e.ids['delete-cancel'].disabled,false);
  if(status===404||status===409) {
   assert.ok(e.requests.filter(([p])=>p==='/api/jobs').length>=2,'missing/active conflict refreshes history');
   assert.equal(e.ids['delete-confirm'].disabled,true,'cannot retry stale target');
   assert.equal(e.ids['delete-project'].disabled,true);
  }
  if(status===404)assert.equal(e.ids['job-status'].hidden,true);
 }
 const active=harness([{...completed,status:'rendering'}]);await tick();
 assert.equal(active.ids['delete-project'].disabled,true);
 await active.ids['delete-project'].click();assert.equal(active.requests.some(([,o])=>o.method==='DELETE'),false);
 console.log('PASS active delete disabled; 404, 409, 500 safe error states');
 const live={...completed,id:'live',status:'queued',progress:0};
 const s=harness([live,{...live,id:'second'}]);await tick();
 assert.equal(s.sources.length,1,'one selected stream only');assert.equal(s.sources[0].url,'/api/jobs/live/events');
 const gridBefore=s.ids['clips-grid'].children[0];
 s.sources[0].emit({...live,status:'rendering',progress:68,progress_detail:{stage_progress:24,current_clip:1,total_clips:3,indeterminate:false}});await tick();
 assert.equal(s.ids['job-badge'].textContent,'Merender klip');
 assert.equal(s.ids['clips-grid'].children[0],gridBefore,'progress-only snapshot preserves video and caption nodes');
 await s.ids['refresh-button'].click();await tick();assert.equal(s.sources.length,1,'refresh does not duplicate connection');
 await s.select('second');assert.equal(s.sources[0].closed,true);assert.equal(s.sources.length,2);
 s.sources[0].emit({...live,title:'STALE'});assert.notEqual(s.ids['job-title'].textContent,'STALE');
 s.sources[1].emit({...live,id:'second',status:'completed'});await tick();assert.equal(s.sources[1].closed,true,'final closes stream');
 assert.equal([...s.timers.values()].filter(t=>t.delay===2000).length,0,'final has no polling');
 const f=harness([live]);await tick();f.sources[0].onerror();await tick();
 assert.equal(f.sources[0].closed,true,'disable native reconnect when falling back');
 assert.match(f.ids['live-state'].textContent,/2 detik/);
 await f.runPoll();assert.equal(f.requests.filter(([p])=>p==='/api/jobs/live').length,1);
 assert.equal([...f.timers.values()].filter(t=>t.delay===2000).length,1,'one fallback timer');
 f.listeners.pagehide();assert.equal([...f.timers.values()].filter(t=>t.delay===2000).length,0);
 const noSSE=harness([live],{sse:false});await tick();await noSSE.runPoll();assert.match(noSSE.ids['live-state'].textContent,/2 detik/);
 const unload=harness([live]);await tick();unload.listeners.beforeunload();assert.equal(unload.sources[0].closed,true);
 console.log('PASS SSE snapshots, stable media, one connection, switching, terminal close, fallback and unload');
 const p=harness([live]);await tick();
 assert.match(p.ids['job-percent'].textContent,/Progres tahapan/);
 assert.match(p.ids['stage-detail'].textContent,/belum tersedia/i);
 assert.equal(p.ids['stage-progress'].attributes.value,undefined,'unknown stage is indeterminate');
 assert.ok(p.ids['stage-progress'].attributes['aria-valuetext'].includes('belum tersedia'));
 p.sources[0].emit({...live,status:'rendering',progress:68,progress_detail:{stage_progress:24.5,current_clip:2,total_clips:3,indeterminate:false}});
 assert.match(p.ids['stage-detail'].textContent,/Klip 2\/3.*24.5%/);
 assert.equal(p.ids['stage-progress'].value,24.5);
 p.sources[0].emit({...live,status:'rendering',progress:68,progress_detail:{stage_progress:24.51234567,current_clip:2,total_clips:3,indeterminate:false}});
 assert.match(p.ids['stage-detail'].textContent,/24\.5%/);
 assert.ok(!p.ids['stage-detail'].textContent.includes('24.51234567'),'human-readable stage percentage');
 assert.ok(walk(p.ids['job-steps']).some(n=>n.attributes?.['aria-current']==='step'&&n.textContent.includes('Render')));
 p.sources[0].emit({...live,status:'transcribing',progress:null,progress_detail:{stage_progress:null,indeterminate:true}});
 assert.equal(p.ids['job-progress'].attributes.value,undefined);assert.ok(!p.ids['job-percent'].textContent.includes('%'));
 p.sources[0].emit({...live,status:'failed',error:'Sumber tidak dapat dibaca'});
 assert.equal(p.sources[0].closed,true);assert.match(p.ids['job-message'].textContent,/Sumber tidak dapat dibaca/);
 assert.equal(p.ids['delete-project'].disabled,false);
 const markup=fs.readFileSync('static/index.html','utf8');
 assert.ok(markup.includes('Studio proyek'),'compact operational dashboard title');
 assert.ok(markup.includes('<fieldset')&&markup.includes('<legend'),'settings grouped semantically');
 assert.ok(markup.includes('id="clear-selection"'),'history can be deselected');
 assert.ok(!markup.includes('Potong durasinya.'),'not a marketing hero');
 const clear=harness([live]);await tick();await clear.ids['clear-selection'].click();
 assert.equal(clear.ids['job-status'].hidden,true);assert.equal(clear.sources[0].closed,true);
 assert.equal(clear.ids['clear-selection'].disabled,true);
 await clear.ids['refresh-button'].click();await tick();assert.equal(clear.ids['job-status'].hidden,true,'refresh respects deliberate deselection');
 const multi=harness([completed,{...completed,id:'next'}]);await tick();
 await multi.ids['delete-project'].click();await multi.ids['delete-confirm'].click();await tick();
 assert.equal(multi.ids['job-status'].hidden,false);assert.equal(multi.ids['delete-project'].disabled,false);
 await multi.ids['delete-project'].click();assert.equal(multi.ids['delete-confirm'].disabled,false);
 multi.ids['delete-dialog'].events.cancel({preventDefault(){}});assert.equal(multi.ids['delete-dialog'].open,false,'Escape cancels safely');
 assert.equal(multi.requests.filter(([,o])=>o.method==='DELETE').length,1);
 const inconsistent=harness([completed],{retainDeleted:true});await tick();
 await inconsistent.ids['delete-project'].click();await inconsistent.ids['delete-confirm'].click();await tick();
 assert.match(inconsistent.ids['network-message'].textContent,/belum dapat diverifikasi/);
 assert.ok(!inconsistent.ids['copy-status'].textContent?.includes('Proyek dihapus'),'do not claim unverified deletion');
 console.log('PASS deletion read-back inconsistency is reported, not claimed successful');
 console.log('PASS delete selects remaining project; dialog reusable and Escape safe');
 console.log('PASS clear history selection closes stream and persists across refresh');
 const stages=harness([live]);await tick();
 for(const [status,label] of [['queued','Antrean'],['downloading','Unduh'],['transcribing','Transkrip'],['selecting','Pilih klip'],['rendering','Render']]) {
  stages.sources[0].emit({...live,status,progress_detail:{stage_progress:null,indeterminate:true}});
  assert.ok(walk(stages.ids['job-steps']).some(n=>n.attributes?.['aria-current']==='step'&&n.textContent.includes(label)));
  assert.equal(stages.ids['stage-progress'].attributes.value,undefined);
 }
 stages.sources[0].events.job({data:'not-json'});assert.equal(stages.sources[0].closed,true);
 assert.equal([...stages.timers.values()].filter(t=>t.delay===2000).length,1,'bad snapshot falls back once');
 const timeout=harness([live]);await tick();const connect=[...timeout.timers].find(([,t])=>t.delay===10000);connect[1].fn();
 assert.equal(timeout.sources[0].closed,true);assert.match(timeout.ids['live-state'].textContent,/2 detik/);
 const create=harness([]);await tick();
 for(const [id,value] of Object.entries({'video-url':'https://youtu.be/abcdefghijk','clip-count':'3',language:'id',layout:'fit','subtitle-style':'clean','render-preset':'reference',headline:'Judul pengujian'}))create.ids[id].value=value;
 create.ids.rights.checked=create.ids.paid.checked=true;
 await create.ids['create-form'].events.submit({preventDefault(){}});await tick();
 const created=JSON.parse(create.requests.find(([p,o])=>p==='/api/jobs'&&o.method==='POST')[1].body);
 assert.equal(created.render_preset,'reference');assert.equal(created.headline,'Judul pengujian');assert.equal(created.clip_count,3);
 assert.equal(create.sources.length,1,'new job starts one live stream');
 assert.ok(markup.includes('value="reference" selected'));assert.ok(markup.includes('maxlength="120"'));
 console.log('PASS all active stages, malformed snapshot, connection timeout, preset/headline creation');
 console.log('PASS operational dashboard structure');
 console.log('PASS truthful overall/stage progress, unknown indeterminate, render n/m, stepper and failure');
})().catch(e=>{console.error(e);process.exitCode=1;});
