const $=id=>document.getElementById(id);
let loading=false,copy='';
const format=seconds=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(seconds*1000));
async function load(){
  if(loading)return;loading=true;
  try{
    const r=await chrome.runtime.sendNativeMessage('com.ais.connector',{action:'logs'});if(!r.ok)throw Error(r.error);
    $('logPath').textContent=r.log_file;$('logEntries').replaceChildren();
    copy=r.entries.map(e=>`${format(e.timestamp)} [${e.level}] ${e.event}\n${JSON.stringify(e.details)}`).join('\n\n');
    for(const e of r.entries){const card=document.createElement('section');const heading=document.createElement('p');heading.className=e.level==='error'?'log-error':'hint';heading.textContent=`${format(e.timestamp)} · ${e.level} · ${e.event}`;const details=document.createElement('code');details.textContent=JSON.stringify(e.details,null,2);card.append(heading,details);$('logEntries').append(card);}
    $('copyLogs').disabled=!r.entries.length;$('pageMessage').textContent=r.entries.length?`已读取 ${r.entries.length} 条日志。`:'暂无日志，后续操作将自动记录。';$('pageMessage').className='';
  }catch(e){$('pageMessage').textContent='无法读取日志：'+e.message;$('pageMessage').className='error';}
  finally{loading=false;}
}
$('reloadLogs').onclick=load;
$('copyLogs').onclick=async()=>{try{await navigator.clipboard.writeText(copy);$('pageMessage').textContent='已复制，请检查个人信息后再分享。';}catch(e){$('pageMessage').textContent='复制失败：'+e.message;}};
load();setInterval(()=>{if(!document.hidden)load();},5000);
