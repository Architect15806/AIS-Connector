(() => {
  const root=document.getElementById('platformGuides');
  const psQuote=value=>"'"+value.replaceAll("'","''")+"'";
  const shQuote=value=>"'"+value.replaceAll("'","'\\''")+"'";
  for(const mac of [false,true]){
    const section=document.createElement('section');
    const heading=document.createElement('h3');heading.textContent=mac?'macOS · Terminal':'Windows · PowerShell';section.append(heading);
    const intro=document.createElement('p');intro.textContent=mac?'将整个项目复制到 Mac（默认 ~/AIS-connector）。在 Chrome 扩展管理页启用开发者模式，加载该项目的 extension 文件夹。':'在 Chrome 扩展管理页启用开发者模式，加载项目中的 extension 文件夹。';section.append(intro);
    const label=document.createElement('label');label.textContent='项目目录';const input=document.createElement('input');input.value=mac?'~/AIS-connector':'D:\\Workspace\\AIS-connector';label.append(input);section.append(label);
    const commands=document.createElement('div');section.append(commands);
    const add=(title,command)=>{const p=document.createElement('p');p.textContent=title;const line=document.createElement('div');line.className='ssh-line';const code=document.createElement('code');code.textContent=command;const copy=document.createElement('button');copy.className='copy-button';copy.title='复制命令';copy.setAttribute('aria-label','复制'+title);copy.innerHTML='<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>';copy.onclick=async()=>{try{await navigator.clipboard.writeText(command);copy.title='已复制';}catch{copy.title='复制失败，请手动选择命令';}};line.append(code,copy);commands.append(p,line);};
    const render=()=>{commands.replaceChildren();const raw=input.value.trim();const path=mac?(raw.startsWith('~/')?'"$HOME"/'+shQuote(raw.slice(2)):shQuote(raw)):psQuote(raw);
      add('1. 打开 Chrome 扩展管理页',mac?'open -a "Google Chrome" "chrome://extensions"':'Start-Process chrome "chrome://extensions"');
      add('2. 检查 Python、ssctl 和 SSH',mac?'python3 --version\n"$HOME/.ssctl/bin/ssctl" login --help\nssh -V':'python --version\n& "$env:USERPROFILE\\.ssctl\\bin\\ssctl.exe" login --help\nssh -V');
      add('3. 注册本地宿主（已填入当前扩展 ID）',mac?`cd ${path}\nsh ./install-mac.sh ${shQuote(chrome.runtime.id)}`:`Set-Location -LiteralPath ${path}\npowershell -NoProfile -ExecutionPolicy Bypass -File .\\install.ps1 -ExtensionId ${chrome.runtime.id}`);
    };input.addEventListener('input',render);render();root.append(section);
  }
})();
