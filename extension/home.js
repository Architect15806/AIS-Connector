const $=id=>document.getElementById(id);
let result=null;
const validIP=value=>typeof value==='string'&&/^(\d{1,3}\.){3}\d{1,3}$/.test(value)&&value.split('.').every(n=>Number(n)<=255);
function commands(ip,index,gateway){
  if(!validIP(ip)||!validIP(gateway)||!Number.isInteger(index)||index<=0)throw Error('检测参数无效，请重新检测。');
  const prefix=ip+'/32';
  return {add:`$ErrorActionPreference = 'Stop'
$adapter = Get-NetAdapter -InterfaceIndex ${index}
if ($adapter.Status -ne 'Up') { throw 'VPN adapter is not Up. Detect again.' }
$gatewayRoute = @(Get-NetRoute -AddressFamily IPv4 -InterfaceIndex ${index} -PolicyStore ActiveStore | Where-Object NextHop -eq '${gateway}')
if ($gatewayRoute.Count -eq 0) { throw 'VPN gateway has changed. Detect again.' }
$existing = @(Get-NetRoute -DestinationPrefix '${prefix}' -PolicyStore ActiveStore -ErrorAction SilentlyContinue)
if ($existing | Where-Object { $_.InterfaceIndex -eq ${index} -and $_.NextHop -eq '${gateway}' }) {
  Write-Host 'Matching route already exists; nothing changed.'
} elseif ($existing.Count -gt 0) {
  throw 'A different host route already exists. Inspect it before making changes.'
} else {
  New-NetRoute -DestinationPrefix '${prefix}' -InterfaceIndex ${index} -NextHop '${gateway}' -RouteMetric 5 -PolicyStore ActiveStore
}`,undo:`Remove-NetRoute -DestinationPrefix '${prefix}' -InterfaceIndex ${index} -NextHop '${gateway}' -PolicyStore ActiveStore -Confirm`};
}
function options(select,items,label){
  select.replaceChildren();const empty=document.createElement('option');empty.value='';empty.textContent='请选择';select.append(empty);
  items.forEach((item,i)=>{const option=document.createElement('option');option.value=String(i);option.textContent=label(item);select.append(option);});
}
function render(){
  $('copyCommand').disabled=true;$('copyUndo').disabled=true;$('command').textContent='请选择 worker 与 VPN 网卡。';$('undo').textContent='';
  const target=$('target').value===''?null:result?.targets[Number($('target').value)];
  const vpn=$('vpn').value===''?null:result?.candidates[Number($('vpn').value)];
  $('evidence').textContent=target?`${target.source}；记录时间：${target.updated_at?new Date(target.updated_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'}):'未知'}`:'';
  $('currentRoute').textContent=target?.route?`当前路由：${target.route.DestinationPrefix} → 网卡 ${target.route.InterfaceIndex} / 网关 ${target.route.NextHop}`:target?'未找到当前 IPv4 路由。':'';
  if(!target||!vpn)return;
  if(target.route&&Number(target.route.InterfaceIndex)===vpn.index&&target.route.NextHop===vpn.gateway){$('command').textContent='当前目标已经走所选网卡与网关，无需添加临时路由。请回插件刷新 SSH 状态。';return;}
  try{const c=commands(target.ip,vpn.index,vpn.gateway);$('command').textContent=c.add;$('undo').textContent=c.undo;$('copyCommand').disabled=false;$('copyUndo').disabled=false;}
  catch(e){$('command').textContent=e.message;}
}
async function detect(){
  $('detect').disabled=true;$('copyCommand').disabled=true;$('copyUndo').disabled=true;$('target').disabled=true;$('vpn').disabled=true;
  result=null;$('command').textContent='正在重新检测，请勿使用旧命令…';$('undo').textContent='';$('message').textContent='正在读取连接进程和 Windows 路由（最多约 25 秒）…';
  try{
    const r=await chrome.runtime.sendNativeMessage('com.ais.connector',{action:'vpn_diagnose'});if(!r.ok)throw Error(r.error);result=r;
    options($('target'),r.targets,t=>`${t.alias} · ${t.ip}`);
    options($('vpn'),r.candidates,v=>`${v.likely_vpn?'VPN 候选 · ':''}${v.name} (${v.description}) · #${v.index} → ${v.gateway}`);
    if(r.targets.length===1)$('target').value='0';
    const likely=r.candidates.map((v,i)=>v.likely_vpn?i:-1).filter(i=>i>=0);if(likely.length===1)$('vpn').value=String(likely[0]);
    $('detectedAt').textContent='检测时间：'+new Date(r.detected_at*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
    $('message').textContent=r.targets.length&&r.candidates.length?'检测完成，请核对候选后复制命令。':'信息不足：未识别到 worker 或带网关的活动网卡，不生成猜测命令。';$('message').className='';render();
  }catch(e){$('message').textContent='检测失败：'+e.message;$('message').className='error';}
  finally{$('detect').disabled=false;$('target').disabled=!result;$('vpn').disabled=!result;}
}
for(const [button,field] of [['copyCommand','command'],['copyUndo','undo']])$(button).onclick=async()=>{try{await navigator.clipboard.writeText($(field).textContent);$('message').textContent='已复制，请在管理员 PowerShell 中执行。';}catch(e){$('message').textContent='复制失败：'+e.message;}};
$('target').onchange=render;$('vpn').onchange=render;$('detect').onclick=detect;detect();
