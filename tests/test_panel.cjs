const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
class Element {
  constructor(){this.children=[];this.dataset={};this.className='';this.hidden=false;this.classList={add:(c)=>this.className+=' '+c};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  setAttribute(k,v){this[k]=v;}
  addEventListener(){}
  focus(){}
  click(){this.onclick?.();}
}
const elements=new Map(),copied=[],requests=[];
const get=id=>{const found=elements.has('connections')?walk(elements.get('connections')).find(e=>e.id===id):null;if(found)return found;if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const walk=e=>[e,...e.children.filter(x=>x instanceof Element).flatMap(walk)];
const context=vm.createContext({console,Intl,Date,Map,Promise,Error,Number,String,Math,
  setInterval(){},requestAnimationFrame(){},setTimeout(){return 1;},clearTimeout(){},
  navigator:{clipboard:{writeText:async value=>copied.push(value)}},
  document:{getElementById:get,createElement:()=>new Element(),createElementNS:()=>new Element(),addEventListener(){},querySelectorAll:selector=>walk(get('connections')).filter(e=>selector==='[data-relative-time]'?e.dataset.relativeTime:selector.startsWith('.')?e.className.split(' ').includes(selector.slice(1)):false)},
  chrome:{runtime:{sendNativeMessage:async(_,r)=>{requests.push(r);return {ok:true};}}}
});
let source=readFileSync('extension/panel.js','utf8');
source=source.slice(0,source.indexOf('// Load private profile;'));
vm.runInContext(source,context);
(async()=>{
  vm.runInContext("data={users:[],connections:[{id:'a',alias:'Example server',namespace:'workflow_87654321',createdAt:Date.now()-120000},{id:'b',alias:'offline',namespace:'workflow_123',createdAt:Date.now()}]};states={a:{status:'connected',port_refreshed_at:Date.now()/1000-300,loginName:'test'}};render();",context);
  let nodes=walk(get('connections'));
  assert.equal(nodes.find(e=>e.id==='connection-body-a').inert,true);
  get('toggleAll').onclick();
  assert.equal(nodes.find(e=>e.id==='connection-body-a').inert,false);
  assert.equal(nodes.find(e=>e.id==='connection-body-b').inert,false);
  get('toggleAll').onclick();
  assert.equal(nodes.find(e=>e.id==='connection-body-a').inert,true);
  assert.equal(nodes.find(e=>e.id==='connection-body-b').inert,true);
  nodes.find(e=>e.id==='fold-a').onclick();
  await nodes.find(e=>e.textContent==='Example server').onclick();
  assert.equal(copied.pop(),'Example server');
  assert(nodes.some(e=>e.textContent==='87654321'));
  await nodes.find(e=>e.textContent==='复制namespace').onclick();
  assert.equal(copied.pop(),'workflow_87654321');
  await nodes.find(e=>e.textContent==='复制登录链接').onclick();
  assert.equal(copied.pop(),'https://aistudio.alipay.com/libro/dev/project/workbench/87654321');
  assert(nodes.some(e=>e.textContent==='（2分钟前）'));
  assert(nodes.some(e=>e.textContent==='（5分钟前）'));
  const age=nodes.find(e=>e.dataset.relativeTime);
  for(const [minutes,expected] of [[59,'（59分钟前）'],[60,'（1小时0分钟前）'],[333,'（5小时33分钟前）']]){
    age.dataset.relativeTime=Date.now()-minutes*60000;
    vm.runInContext('updateRelativeTimes()',context);
    assert.equal(age.textContent,expected);
  }
  nodes.find(e=>e.id==='fold-a').onclick();
  nodes=walk(get('connections'));
  assert.equal(nodes.find(e=>e.id==='connection-body-a').inert,true);
  assert.equal(nodes.find(e=>e.id==='fold-a')['aria-expanded'],'false');
  assert(nodes.some(e=>e.className==='state'&&e.textContent.includes('SSH')));
  await nodes.find(e=>e.textContent==='Example server').onclick();
  assert.equal(copied.pop(),'Example server');
  vm.runInContext('render()',context);
  nodes=walk(get('connections'));
  assert.equal(nodes.find(e=>e.id==='connection-body-a').inert,true);
  nodes.find(e=>e.id==='fold-a').onclick();
  assert.equal(walk(get('connections')).find(e=>e.id==='connection-body-a').inert,false);
  vm.runInContext('foldAnimationTimer=null;render()',context);
  await get('refreshAll').onclick();
  assert.deepEqual(JSON.parse(JSON.stringify(requests)),[{action:'check',id:'a'}]);
  console.log('Panel tests passed: copy name/namespace/link, relative times, active-only refresh.');
})().catch(e=>{console.error(e);process.exitCode=1;});
