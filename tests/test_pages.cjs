const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
function page(file,response){
  const elements=new Map(),copied=[];
  const element=()=>({textContent:'',children:[],append(...items){this.children.push(...items);},replaceChildren(){this.children=[];}});
  const get=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id);};
  const context=vm.createContext({Intl,Date,JSON,Error,setInterval(){},
    document:{getElementById:get,createElement:element},
    navigator:{clipboard:{writeText:async text=>copied.push(text)}},
    chrome:{runtime:{sendNativeMessage:async()=>response}}});
  vm.runInContext(readFileSync(file,'utf8'),context);
  return {get,copied};
}
(async()=>{
  const agent=page('extension/agent.js',{ok:true,agent_file:'/Users/example/Library/Application Support/AISConnector/agent/connections.json',skill_file:'/workspace/project/skills/ais-connector/SKILL.md'});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(agent.get('agentFile').textContent,'/Users/example/Library/Application Support/AISConnector/agent/connections.json');
  await agent.get('copySkill').onclick();
  assert.equal(agent.copied[0],'/workspace/project/skills/ais-connector/SKILL.md');
  const logs=page('extension/logs.js',{ok:true,log_file:'/private/logs/events.sqlite3',entries:[{timestamp:1,level:'error',event:'operation.failed',details:{error:'<script>untrusted</script>'}}]});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(logs.get('logEntries').children.length,1);
  assert(logs.get('logEntries').children[0].children[1].textContent.includes('<script>untrusted</script>'));
  await logs.get('copyLogs').onclick();
  assert(logs.copied[0].includes('operation.failed'));
  const failed=page('extension/agent.js',{ok:false,error:'offline'});
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(failed.get('copyAgent').disabled,true);
  assert(failed.get('pageMessage').textContent.includes('offline'));
  console.log('Agent/log page tests passed: dynamic paths, copying, inert log text, offline handling.');
})().catch(e=>{console.error(e);process.exitCode=1;});
