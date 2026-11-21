'use strict';
// Dependency-free DOM harness: real app event handlers, no network or paid calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Node {
  constructor(tag='div') { this.tagName=tag; this.children=[];this.events={};this.style={};this.value='';this.disabled=false;this.className='';this.classList={toggle(){},add(){}}; }
  append(...nodes){ this.children.push(...nodes); }
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(k,v){this[k]=v;}
  addEventListener(k,fn){this.events[k]=fn;}
  querySelector(selector){return walk(this).find(n=>selector.startsWith('.') ? n.className?.split(' ').includes(selector.slice(1)): n.tagName===selector)||null;}
  remove(){} focus(){} select(){} click(){return this.events.click?.({target:this});}
}
function walk(node){return [node,...node.children.flatMap(walk)];}
const ids={};
for(const id of ['network-message','create-button','health-state','project-select','copy-status','job-status','download-all','clip-total','job-badge','job-title','job-source','job-percent','job-progress','job-message','clips-grid','empty-state','refresh-button','create-form','form-message','video-url','rights','paid','clip-count','language','layout','subtitle-style']) ids[id]=new Node();
ids['empty-state'].append(new Node('h3'),new Node('p'),new Node('a'));
const job={id:'legacy',title:'Fixture',status:'completed',clips:[{id:'clip-01',title:'Data',caption:'<img src=x onerror=alert(1)> Data aktual.',start:0,end:2}]};
let requests=[],copied='',fail=false, blobs=[];
const URLClass=URL; URLClass.createObjectURL=b=>{blobs.push(b);return 'blob:fixture';};URLClass.revokeObjectURL=()=>{};
const context={document:{getElementById:id=>ids[id],createElement:tag=>new Node(tag),createTextNode:text=>({textContent:text,children:[]}),body:new Node('body'),execCommand:()=>true},location:{href:'http://localhost/',origin:'http://localhost'},window:{addEventListener(){}},navigator:{clipboard:{writeText:async text=>{copied=text;}}},fetch:async(path,options={})=>{requests.push([path,options]); if(path.endsWith('/caption')) return {ok:!fail,json:async()=>fail?{detail:'Gemini HTTP 503: sedang sibuk'}:{text:'Draf aman <script>bad</script>',title:'Data',platform:'TikTok',style:'pertanyaan',method:JSON.parse(options.body).provider,disclaimer:'Draf hasil pengujian'}};return {ok:true,json:async()=>path.endsWith('/health')?{status:'ok',deepgram_configured:true}:{jobs:[job]}};},setTimeout:()=>1,clearTimeout(){},AbortController,URL:URLClass,Blob,console};
vm.runInNewContext(fs.readFileSync('static/app.js','utf8'),context);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 await tick(); await tick();
 const grid=ids['clips-grid'];
 const editor=walk(grid).find(n=>n.className==='caption-editor');
 assert.ok(editor,'editable caption draft must exist');
 const button=label=>walk(grid).find(n=>n.tagName==='button'&&n.textContent===label);
 const platform=walk(grid).find(n=>n['aria-label']==='Platform caption');
 const style=walk(grid).find(n=>n['aria-label']==='Gaya caption');
 assert.ok(platform&&style); platform.value='TikTok';style.value='pertanyaan';
 await button('Buat draf lokal').click();
 const request=requests.find(([p])=>p.endsWith('/caption'));
 assert.equal(request[0],'/api/jobs/legacy/clips/clip-01/caption');
 assert.deepEqual(JSON.parse(request[1].body),{platform:'TikTok',style:'pertanyaan',provider:'local-template'});
 assert.equal(editor.value,'Draf aman <script>bad</script>');
 editor.value='Edit pengguna'; await button('Salin draf').click();assert.equal(copied,'Edit pengguna');
 button('Unduh .txt').click();assert.equal(await blobs.at(-1).text(),'Edit pengguna');
 await button('Buat dengan Groq').click();
 assert.equal(JSON.parse(requests.filter(([p])=>p.endsWith('/caption')).at(-1)[1].body).provider,'groq');
 editor.value='Edit pengguna'; fail=true;await button('Buat dengan Gemini').click();
 assert.equal(editor.value,'Edit pengguna');
 assert.ok(walk(grid).some(n=>n.textContent?.includes('Gemini HTTP 503')));
 assert.equal(requests.filter(([p])=>p.endsWith('/caption')).length,3,'no automatic retry');
 assert.ok(fs.readFileSync('static/index.html','utf8').includes('id="subtitle-style"'));
 console.log('Frontend DOM flow passed: local + Gemini error, edit, copy, download, no retries, legacy data.');
})().catch(e=>{console.error(e);process.exitCode=1;});
