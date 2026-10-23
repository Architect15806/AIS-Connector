const $ = id => document.getElementById(id);
let data, states = {}, editing, busy = false;
let pendingConnection = null;
let openNamespaceId = null;
let draggedConnectionId = null;
async function reorderConnection(sourceId, targetId, after=false){
  if(busy||sourceId===targetId)return;
  const previous=data.connections.slice();
  const source=previous.find(c=>c.id===sourceId);
  if(!source||!previous.some(c=>c.id===targetId))return;
  await perform(async()=>{
    const next=previous.filter(c=>c.id!==sourceId);
    next.splice(next.findIndex(c=>c.id===targetId)+(after?1:0),0,source);
    data.connections=next;
    try{await rpc({action:'profile_save',profile:data});}
    catch(error){data.connections=previous;throw error;}
    await syncAgentFile();
    message('连接顺序已保存。');
  });
}
function attachConnectionDrag(card, row, connection){
  const handle=document.createElement('button');
  handle.type='button';handle.className='quiet connection-drag';handle.textContent='⠿';
  handle.title='拖拽排序；也可按 Alt + 上下方向键移动';
  handle.setAttribute('aria-label','调整连接顺序：'+connection.alias);
  handle.draggable=!busy;handle.disabled=busy;
  handle.ondragstart=e=>{
    if(busy){e.preventDefault();return;}
    draggedConnectionId=connection.id;
    e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',connection.id);
    card.dataset.dragging='true';
  };
  const clear=()=>{for(const el of document.querySelectorAll('.connection-card')){delete el.dataset.dropPosition;delete el.dataset.dragging;}};
  handle.ondragend=()=>{draggedConnectionId=null;clear();render();};
  card.ondragover=e=>{
    if(!draggedConnectionId||draggedConnectionId===connection.id||busy)return;
    e.preventDefault();clear();e.dataTransfer.dropEffect='move';
    const rect=card.getBoundingClientRect();
    card.dataset.dropPosition=e.clientY>rect.top+rect.height/2?'after':'before';
  };
  card.ondragleave=e=>{if(!card.contains(e.relatedTarget))delete card.dataset.dropPosition;};
  card.ondrop=e=>{
    if(!draggedConnectionId)return;
    e.preventDefault();const source=draggedConnectionId,after=card.dataset.dropPosition==='after';
    draggedConnectionId=null;clear();void reorderConnection(source,connection.id,after);
  };
  handle.onkeydown=e=>{
    if(!e.altKey||!['ArrowUp','ArrowDown'].includes(e.key))return;
    e.preventDefault();const down=e.key==='ArrowDown';
    const target=data.connections[data.connections.findIndex(c=>c.id===connection.id)+(down?1:-1)];
    if(target)void reorderConnection(connection.id,target.id,down);
  };
  row.append(handle);
}
const expandedConnections = new Set();
const expandedGPU = new Set();
function gpuPanel(connection,state){
  const panel=document.createElement('div');panel.className='gpu-panel';
  const summary=document.createElement('button');summary.className='gpu-summary';summary.type='button';
  const reveal=document.createElement('div');reveal.className='gpu-reveal';reveal.id='gpu-details-'+connection.id;
  const content=document.createElement('div');content.className='gpu-content';reveal.append(content);
  const applyOpen=()=>{const open=expandedGPU.has(connection.id);panel.dataset.expanded=String(open);summary.setAttribute('aria-expanded',String(open));content.inert=!open;};
  summary.setAttribute('aria-controls',reveal.id);applyOpen();
  summary.onclick=()=>{
    if(expandedGPU.has(connection.id))expandedGPU.delete(connection.id);else expandedGPU.add(connection.id);
    applyOpen();
    clearTimeout(foldAnimationTimer);
    foldAnimationTimer=setTimeout(()=>{foldAnimationTimer=null;if(renderAfterFold){renderAfterFold=false;render();}},300);
  };
  const scan=state.gpu,cards=scan?.cards||[];
  const counts={idle:0,spinning:0,busy:0,unknown:0};for(const card of cards)counts[card.status in counts?card.status:'unknown']++;
  summary.textContent=cards.length?`${counts.idle}卡空闲，${counts.spinning}卡空转，${counts.busy}卡占用${counts.unknown?`，${counts.unknown}卡未知`:''}`:scan?.error||'显卡状态：等待首次扫描';
  panel.append(summary);
  const note=document.createElement('p');note.className='hint';note.textContent=(scan?.updated_at?`扫描时间：${beijingTime(scan.updated_at*1000)}。`:'')+(state.status!=='connected'?' 当前连接未就绪，已有结果仅供参考。':'');const scanRow=document.createElement('div');scanRow.className='gpu-scan-row';
  const watch=button('注视',()=>perform(async()=>{
    await rpc({action:'gpu_watch',id:connection.id,enabled:!state.gpu_watching});
    message(state.gpu_watching?'已关闭注视。':'已开启注视，每 2 秒扫描显卡；扫描较慢时不会并发堆积。');
    await refresh();
  }),!state.gpu_watching);
  watch.className=state.gpu_watching?'gpu-watch watching':'quiet gpu-watch';
  watch.setAttribute('aria-pressed',String(Boolean(state.gpu_watching)));
  watch.disabled=busy||(!state.gpu_watching&&state.status!=='connected');
  if(state.gpu_watching){attachCountdown(watch,connection.id,state);watch.dataset.gpuWatch='true';}
  scanRow.append(note,watch);content.append(scanRow);
  for(const card of cards){
    const item=document.createElement('div');item.className='gpu-card';
    const model=String(card.name||'未知').replace(/^NVIDIA\s+/i,'');
    const mem=Number.isFinite(card.memory_used)&&Number.isFinite(card.memory_total)&&card.memory_total>0?Math.round(card.memory_used/card.memory_total*100)+'%':'未知';
    item.textContent=`${card.index}：${model}  Mem ${mem}  Util ${card.utilization==null?'未知':card.utilization+'%'}`;
    content.append(item);
  }
  panel.append(reveal);
  return panel;
}
let foldAnimationTimer = null, renderAfterFold = false;
let editingConnectionId = null;
let intervalSeconds = 300;
let lastCatalog = null;
async function syncAgentFile(){
  const connections=data.connections.map(({id,alias,namespace})=>({id,alias,namespace}));
  const catalog=JSON.stringify(connections);
  if(catalog===lastCatalog)return;
  await rpc({action:'sync_connections',connections});lastCatalog=catalog;
}
$('agentConnection').onclick=()=>chrome.tabs.create({url:chrome.runtime.getURL('agent.html')});
$('openLogs').onclick=()=>chrome.tabs.create({url:chrome.runtime.getURL('logs.html')});
$('openHome').onclick=()=>chrome.tabs.create({url:chrome.runtime.getURL('home.html')});
$('field1').oninput=()=>$('field1').setCustomValidity('');
const countdownResets = new Map();
const resetCountdown = id => {countdownResets.set(id,Date.now()/1000);render();};
function attachCountdown(button,id,state){
  button.classList.add('countdown-button');button.dataset.connectionId=id;
  const ns='http://www.w3.org/2000/svg';const svg=document.createElementNS(ns,'svg');svg.classList.add('countdown-border');svg.setAttribute('aria-hidden','true');
  const rect=document.createElementNS(ns,'rect');rect.setAttribute('x','1.5');rect.setAttribute('y','1.5');rect.setAttribute('width','calc(100% - 3px)');rect.setAttribute('height','calc(100% - 3px)');rect.setAttribute('rx','10');rect.setAttribute('pathLength','100');svg.append(rect);button.append(svg);
}
function animateCountdown(){
  const now=Date.now()/1000;
  for(const button of document.querySelectorAll('.countdown-button')){
    const id=button.dataset.connectionId,s=states[id]||{};let reset=countdownResets.get(id);
    if(button.dataset.gpuWatch){
      const remaining=s.gpu_next_check_at?Math.max(0,s.gpu_next_check_at-now):0;
      button.querySelector('rect').setAttribute('stroke-dasharray',`${Math.min(1,remaining/2)*100} 100`);
      button.title=s.gpu_scan_running?'正在扫描显卡…':`下次显卡扫描：${Math.ceil(remaining)} 秒`;
      continue;
    }
    if(reset&&s.countdown_started_at>=reset){countdownResets.delete(id);reset=null;}
    const duration=reset?intervalSeconds:(s.interval_seconds||intervalSeconds);
    const end=reset?reset+duration:s.next_check_at;
    const remaining=end?Math.max(0,end-now):0;
    const fraction=active(s.status)||reset?Math.min(1,remaining/duration):0;
    button.querySelector('rect').setAttribute('stroke-dasharray',`${fraction*100} 100`);
    button.title=end&&active(s.status)?`下次检测：${Math.ceil(remaining)} 秒`:'刷新 SSH 状态';
  }
  requestAnimationFrame(animateCountdown);
}
requestAnimationFrame(animateCountdown);
$('installTutorial').onclick=()=>chrome.tabs.create({url:chrome.runtime.getURL('install.html')});
const active = status => ['connected','connecting','checking','degraded','reconnecting'].includes(status);
const beijingTime = ms => ms ? new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(ms)) : '暂无记录';
const rpc = payload => chrome.runtime.sendNativeMessage('com.ais.connector', payload).then(r => {if (!r.ok) throw Error(r.error); return r;});
const message = (text, error=false) => { $('message').textContent=text; $('message').className=error?'error':''; };
const selected = () => data.users.find(u => u.id === data.selected);
async function save(){await rpc({action:'profile_save',profile:data});await chrome.storage.local.remove('ais');render();await syncAgentFile();}
function button(text, action, quiet=false){const b=document.createElement('button');b.textContent=text;b.className=quiet?'quiet':'';b.onclick=action;b.disabled=busy;return b;}
async function perform(action){if(busy)return;busy=true;render();try{await action();}catch(e){message(e.message,true);}finally{busy=false;render();}}

async function copyText(value){try{await navigator.clipboard.writeText(value);message('已复制。');}catch(e){message('复制失败：'+e.message,true);}}
function updateRelativeTimes(){
  for(const el of document.querySelectorAll('[data-relative-time]')){
    const minutes=Math.max(0,Math.floor((Date.now()-Number(el.dataset.relativeTime))/60000));
    el.textContent=`（${minutes>=60?`${Math.floor(minutes/60)}小时${minutes%60}分钟`:`${minutes}分钟`}前）`;
  }
}
function timeRow(label,ms){
  const p=document.createElement('p');p.className='hint connection-meta';
  p.append(`${label}${beijingTime(ms)}`);
  if(ms){const age=document.createElement('span');age.dataset.relativeTime=ms;p.append(' ',age);}
  return p;
}
function closeNamespaceMenu(){
  openNamespaceId=null;
  document.querySelectorAll('.namespace-menu').forEach(el=>el.hidden=true);
  document.querySelectorAll('.namespace-toggle').forEach(el=>el.setAttribute('aria-expanded','false'));
}
document.addEventListener('click',e=>{if(!e.target.closest('.namespace-actions'))closeNamespaceMenu();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){const toggle=document.querySelector('.namespace-toggle[aria-expanded="true"]');closeNamespaceMenu();toggle?.focus();}});
setInterval(updateRelativeTimes,1000);
$('refreshAll').onclick=()=>perform(async()=>{
  const targets=data.connections.filter(c=>active(states[c.id]?.status));
  for(const c of targets)countdownResets.set(c.id,Date.now()/1000);
  render();
  const results=await Promise.allSettled(targets.map(async c=>{
    try{await rpc({action:'check',id:c.id});}
    catch(e){countdownResets.delete(c.id);throw Error(`${c.alias}：${e.message}`);}
  }));
  const failures=results.filter(r=>r.status==='rejected');
  message(`已请求刷新 ${results.length-failures.length} 个连接。`+(failures.length?' '+failures.map(r=>r.reason.message).join('；'):''),failures.length>0);
});

function updateFoldAll(){
  const allClosed=data.connections.every(c=>!expandedConnections.has(c.id));
  const control=$('toggleAll');
  control.disabled=!data.connections.length;
  control.textContent=allClosed?'▸':'▾';
  control.title=allClosed?'全部展开':'全部折叠';
  control.setAttribute('aria-label',control.title);
}
$('toggleAll').onclick=()=>{
  const allClosed=data.connections.every(c=>!expandedConnections.has(c.id));
  for(const c of data.connections){
    if(expandedConnections.has(c.id)!==allClosed)document.getElementById('fold-'+c.id)?.click();
  }
  updateFoldAll();
};
function render(){
  if(draggedConnectionId)return;
  if(foldAnimationTimer!==null){renderAfterFold=true;return;}
  updateFoldAll();
  $('refreshAll').disabled=busy||!data.connections.some(c=>active(states[c.id]?.status));
  $('users').replaceChildren(...data.users.map(u=>{const o=document.createElement('option');o.value=u.id;o.textContent=u.name;return o;}));$('users').value=data.selected||'';
  $('login').disabled=busy||!selected();$('deleteUser').disabled=busy||!selected();$('addConnection').disabled=busy;$('addUser').disabled=busy;$('users').disabled=busy;
  const auth=selected()?.auth;
  $('currentUser').textContent=auth?.status==='认证成功'?`当前用户：${selected().name}`:'当前用户：未登录';
  $('auth').textContent=auth ? `${auth.status} · 更新于 ${beijingTime(auth.updatedAt)}` : '尚无登录状态记录';
  $('connections').replaceChildren();
  const connections=data.connections;
  if(!connections.length){const p=document.createElement('p');p.className='hint';p.textContent='添加一个实例，随时开启工作通道。';$('connections').append(p);}
  for(const c of connections){const s=states[c.id]||{};const a=document.createElement('article');const collapsed=!expandedConnections.has(c.id);a.className=collapsed?'connection-card collapsed':'connection-card';const body=document.createElement('div');body.className='connection-body';body.id='connection-body-'+c.id;body.inert=collapsed;const reveal=document.createElement('div');reveal.className='connection-reveal';reveal.append(body);const st=document.createElement('div');st.className='state';st.textContent=({connected:'● 已连接 · SSH 验证通过',connecting:'◌ 正在建立通道…',checking:'◌ 正在验证 SSH…',degraded:'⚠ SSH 不可用',error:'连接失败',stopped:'未连接'})[s.status]||'未连接';
    const nameRow=document.createElement('div');nameRow.className='connection-name-row';
    attachConnectionDrag(a,nameRow,c);
    const copyName=button(c.alias,()=>copyText(c.alias),true);
    copyName.classList.add('connection-title');copyName.disabled=false;copyName.title='点击复制连接名称';
    const actions=document.createElement('div');actions.className='namespace-actions';
    const digits=/^workflow_(\d+)$/.exec(c.namespace)?.[1];
    const toggle=button(digits||c.namespace,()=>{const show=menu.hidden;closeNamespaceMenu();if(show){openNamespaceId=c.id;menu.hidden=false;toggle.setAttribute('aria-expanded','true');}},true);
    toggle.classList.add('namespace-toggle');toggle.disabled=false;toggle.title=c.namespace;toggle.setAttribute('aria-expanded',String(openNamespaceId===c.id));toggle.setAttribute('aria-label',c.namespace+' 复制选项');
    const menu=document.createElement('div');menu.className='namespace-menu';menu.hidden=openNamespaceId!==c.id;
    const copyNamespace=button('复制namespace',()=>{closeNamespaceMenu();return copyText(c.namespace);},true);
    const copyLink=button('复制登录链接',()=>{closeNamespaceMenu();return copyText('https://aistudio.alipay.com/libro/dev/project/workbench/'+digits);},true);
    copyNamespace.disabled=false;copyLink.disabled=!digits;menu.append(copyNamespace,copyLink);actions.append(toggle,menu);actions.inert=collapsed;
    const fold=button('▾',()=>{
      if(expandedConnections.has(c.id))expandedConnections.delete(c.id);else expandedConnections.add(c.id);
      closeNamespaceMenu();updateFoldAll();
      const closed=!expandedConnections.has(c.id);
      a.className=closed?'connection-card collapsed':'connection-card';
      body.inert=closed;actions.inert=closed;
      fold.title=closed?'展开连接':'折叠连接';
      fold.setAttribute('aria-label',fold.title+'：'+c.alias);
      fold.setAttribute('aria-expanded',String(!closed));
      clearTimeout(foldAnimationTimer);
      foldAnimationTimer=setTimeout(()=>{
        foldAnimationTimer=null;
        if(renderAfterFold){renderAfterFold=false;render();}
      },300);
    },true);
    fold.disabled=false;fold.id='fold-'+c.id;fold.className='quiet connection-fold';fold.title=collapsed?'展开连接':'折叠连接';fold.setAttribute('aria-label',fold.title+'：'+c.alias);fold.setAttribute('aria-expanded',String(!collapsed));fold.setAttribute('aria-controls',body.id);
    nameRow.append(copyName,actions,fold);a.append(nameRow,st,reveal);
    if(s.error){const p=document.createElement('p');p.className='hint';p.textContent=s.error;body.append(p);}
    body.append(timeRow('状态更新：',s.updated_at ? s.updated_at*1000 : c.createdAt));
    if(s.port_refreshed_at)body.append(timeRow('端口刷新：',s.port_refreshed_at*1000));
    if(s.status==='reconnecting')st.textContent='◌ 正在重连 / 等待重试';
    if(active(s.status)&&s.loginName){const account=document.createElement('p');account.className='hint connection-meta';account.textContent=`本次连接用户：${s.loginName}`;body.append(account);}
    if(s.ssh_command){const line=document.createElement('div');line.className='ssh-line';const code=document.createElement('code');code.textContent=s.ssh_command;const copy=button('',async()=>{try{await navigator.clipboard.writeText(s.ssh_command);copy.title='已复制';message('SSH 命令已复制。');}catch(e){message(e.message,true);}},true);copy.className='copy-button';copy.title='复制 SSH 命令';copy.setAttribute('aria-label','复制 SSH 命令');copy.innerHTML='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>';line.append(code,copy);body.append(line);}
    const row=document.createElement('div');row.className='row';
    const check=button('刷新状态',()=>perform(async()=>{resetCountdown(c.id);try{await rpc({action:'check',id:c.id});pendingConnection=c.id;message('已请求实时 SSH 检测。');}catch(e){countdownResets.delete(c.id);throw e;}}));check.disabled=busy||!active(s.status);attachCountdown(check,c.id,s);row.append(check);
    const disconnect=button('断开连接',()=>perform(async()=>{await rpc({action:'stop',id:c.id});pendingConnection=c.id;message('已请求断开，正在等待后台进程退出。');await refresh();}));disconnect.disabled=busy||!active(s.status);row.append(disconnect);
    row.append(button('编辑',()=>openEditor('connection',c),true));
    row.append(button('删除',()=>perform(async()=>{if(active(s.status))throw Error('请先断开此连接。');if(confirm(`删除连接“${c.alias}”？`)){data.connections=data.connections.filter(x=>x.id!==c.id);await save();}}),true));body.append(row,gpuPanel(c,s));if(!active(s.status)){const start=button('初始化连接',()=>perform(async()=>{if(!selected())throw Error('请先选择一个用户。');resetCountdown(c.id);await rpc({action:'connect',id:c.id,namespace:c.namespace,loginName:selected().name});pendingConnection=c.id;message('正在后台建立通道…');await refresh();}));start.disabled=busy||!selected();const startRow=document.createElement('div');startRow.className='row';startRow.append(start);body.append(startRow);}$('connections').append(a);
  }
  updateRelativeTimes();
}
async function refresh(){try{await syncAgentFile();const r=await rpc({action:'status'});states=r.connections;intervalSeconds=(r.settings?.interval_minutes??5)*60;const s=states[pendingConnection];if(s){if(s.status==='connected'){message('SSH 验证通过，可复制命令进入实例。');pendingConnection=null;}else if(['error','degraded'].includes(s.status)){message(s.error||'SSH 不可用，请查看连接详情。',true);pendingConnection=null;}else if(s.status==='checking'){message('通道已监听，正在验证远端 SSH…');}else if(s.status==='stopped'){message('隧道已断开。');pendingConnection=null;}}$('bridge').textContent=r.ssctlInstalled?'本地服务就绪':'缺少 ssctl';$('installTutorial').className=r.ssctlInstalled?'quiet':'';if(!r.ssctlInstalled)message('请先安装 ssctl 到用户目录的 .ssctl/bin。',true);render();}catch(e){$('bridge').textContent='宿主不可用';$('installTutorial').className='';message('无法连接本地宿主：'+e.message,true);}}
$('users').onchange=async()=>{data.selected=$('users').value;await save();};
$('openSettings').onclick=async()=>{try{const r=await rpc({action:'status'});$('checkInterval').value=r.settings?.interval_minutes??5;$('settingsError').textContent='';$('settingsDialog').showModal();}catch(e){message(e.message,true);}};
$('cancelSettings').onclick=()=>$('settingsDialog').close();
$('settingsForm').onsubmit=async e=>{e.preventDefault();try{const minutes=Number($('checkInterval').value);await rpc({action:'settings',interval_minutes:minutes});intervalSeconds=minutes*60;for(const [id,s] of Object.entries(states))if(active(s.status))resetCountdown(id);$('settingsDialog').close();message('检测间隔已保存，已请求立即检测并重置倒计时。');}catch(error){$('settingsError').textContent=error.message;}};
$('addUser').onclick=()=>openEditor('user');$('addConnection').onclick=()=>openEditor('connection');
function openEditor(mode,connection=null){editing=mode;editingConnectionId=connection?.id||null;const user=mode==='user';$('editorTitle').textContent=user?'添加用户':connection?'编辑连接':'添加连接';$('field1Label').firstChild.textContent=user?'用户名（邮箱前缀）':'连接别名';$('field1').setCustomValidity('');$('field1').value=connection?.alias||'';$('field1').placeholder=user?'example.user':'';$('field2').value=connection?.namespace||'';$('field2').setCustomValidity('');$('field2Label').hidden=user;$('field2').required=!user;$('field2').disabled=user;$('namespaceHelp').hidden=user;$('userHelp').hidden=!user;$('editor').showModal();$('field1').focus();}
$('field2').oninput=()=>$('field2').setCustomValidity('');
$('copyNamespace').onclick=async()=>{try{await navigator.clipboard.writeText('echo $AISTUDIO_NAMESPACE');$('copyNamespace').title='已复制';}catch(e){message('复制失败：'+e.message,true);}};
$('cancelEditor').onclick=()=>$('editor').close();
$('editorForm').onsubmit=async e=>{e.preventDefault();const name=$('field1').value.trim();if(!name)return;if(editing!=='user'&&data.connections.some(c=>c.id!==editingConnectionId&&c.alias===name)){$('field1').setCustomValidity('连接别名不能重复（Agent 文件以别名为键）。');$('field1').reportValidity();return;}if(editing==='user'){if(!/^[a-zA-Z0-9._@-]{1,100}$/.test(name)){message('Login name 格式不正确。',true);return;}if(data.users.some(u=>u.name===name)){message('用户已存在。',true);return;}const id=crypto.randomUUID();data.users.push({id,name});data.selected=id;}else{const namespace=$('field2').value.trim();const connection=data.connections.find(c=>c.id===editingConnectionId);if(connection){if(namespace!==connection.namespace){const result=await rpc({action:'status'}).catch(()=>null);if(!result){$('field2').setCustomValidity('无法确认连接状态，请恢复本地服务后重试。');$('field2').reportValidity();return;}states=result.connections;if(active(states[connection.id]?.status)){$('field2').setCustomValidity('请先断开连接，再修改 namespace。');$('field2').reportValidity();return;}connection.id=crypto.randomUUID();connection.createdAt=Date.now();}Object.assign(connection,{alias:name,namespace});}else{data.connections.push({id:crypto.randomUUID(),alias:name,namespace,createdAt:Date.now()});}}$('editor').close();await save();};
$('deleteUser').onclick=()=>perform(async()=>{if(confirm('删除此用户？已有连接和运行中的隧道会保留。')){data.users=data.users.filter(u=>u.id!==data.selected);data.selected=data.users[0]?.id;await save();}});
$('login').onclick=()=>{$('loginName').textContent=selected().name;$('token').value='';$('loginDialog').showModal();$('token').focus();};
$('cancelLogin').onclick=()=>$('loginDialog').close();$('loginDialog').addEventListener('close',()=>{$('token').value='';});
$('loginForm').onsubmit=e=>{e.preventDefault();const token=$('token').value;const user=selected();const loginName=user.name;$('loginDialog').close();perform(async()=>{user.auth={status:'正在认证',updatedAt:Date.now()};await save();message('正在认证…');try{await rpc({action:'login',loginName,token});user.auth={status:'认证成功',updatedAt:Date.now()};message(`${loginName} 认证成功，可以初始化连接。`);}catch(error){user.auth={status:'认证失败',updatedAt:Date.now()};throw error;}finally{await save();}});};
// Load private profile; migrate the legacy browser copy only after durable host storage succeeds.
(async()=>{
  try{
    const saved=await rpc({action:'profile_get'});
    data=saved.profile;
    if(!data){
      const legacy=(await chrome.storage.local.get('ais')).ais;
      data=legacy||{schemaVersion:2,users:[],selected:null,connections:[]};
      for(const c of data.connections)delete c.userId;
      data.schemaVersion=2;
      data=(await rpc({action:'profile_init',profile:data})).profile;
    }
    await chrome.storage.local.remove('ais');
    render();await refresh();
    let lastPoll=0,polling=false;
    setInterval(async()=>{const period=Object.values(states).some(s=>s.gpu_watching)?1000:3000;if(polling||Date.now()-lastPoll<period)return;polling=true;lastPoll=Date.now();try{await refresh();}finally{polling=false;}},1000);
  }catch(e){
    data={users:[],connections:[]};render();
    document.querySelectorAll('main button, main select').forEach(el=>el.disabled=true);
    $('installTutorial').disabled=false;
    message('无法读取个人数据，未修改已有数据。请检查本地服务并重新打开侧栏：'+e.message,true);
  }
})();
