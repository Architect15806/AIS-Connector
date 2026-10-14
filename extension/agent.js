const $=id=>document.getElementById(id);
async function load(){
  $('copySkill').disabled=true;$('copyAgent').disabled=true;
  try{
    const r=await chrome.runtime.sendNativeMessage('com.ais.connector',{action:'agent_info'});
    if(!r.ok)throw Error(r.error);
    $('skillFile').textContent=r.skill_file;$('agentFile').textContent=r.agent_file;
    $('copySkill').disabled=false;$('copyAgent').disabled=false;
    $('pageMessage').textContent='路径已从本地服务获取。';$('pageMessage').className='';
  }catch(e){$('pageMessage').textContent='无法获取路径：'+e.message;$('pageMessage').className='error';}
}
for(const [button,field] of [['copySkill','skillFile'],['copyAgent','agentFile']]){
  $(button).onclick=async()=>{try{await navigator.clipboard.writeText($(field).textContent);$('pageMessage').textContent='已复制。';}catch(e){$('pageMessage').textContent='复制失败：'+e.message;}};
}
$('reloadInfo').onclick=load;load();
