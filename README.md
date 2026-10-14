# AIS Connector

面向 Ant AIStudio 的 Chrome 侧栏扩展：管理用户认证、后台 SSH 隧道，并为 Agent 提供自动更新的连接命令。

前端使用原生 HTML / CSS / JavaScript，通过 Native Messaging 调用本机 Python 宿主和 ssctl。无需 npm 安装或构建。

> Windows 已在本机验证；macOS 已实现适配并通过安装脚本测试，尚待真实 Mac 验证。“居家”路由功能仅支持 Windows。本项目不附带 ssctl，不提供账号或服务器访问权限。

## 功能

- 多用户登录；用户与连接独立管理，新安装不预置任何个人信息。
- 添加、编辑、删除连接；名称点击复制，namespace 菜单支持复制 namespace 和工作台链接。
- 卡片默认折叠，支持单条和全部展开 / 折叠、过渡动画。
- 定时真实 SSH 检测、手动 / 全部刷新、自动重连、端口更新与倒计时。
- 底部提供 **Agent 连接｜居家｜日志｜设置** 四个入口。
- 个人数据独立存储，Git 默认忽略；项目 Logo 作为正式资源保留。

## 环境要求

- Chrome 116 或更新版本。
- Python 3.9+，Windows 使用 `python`，macOS 使用 `python3`。
- OpenSSH 客户端（`ssh` 命令可用）。
- 通过公司认可渠道安装的 ssctl、有效 AIStudio 账号、实例权限及网络条件。
- Git 用于下载 / 更新源码；Node.js 仅运行前端测试时需要。

默认 ssctl 路径为 Windows 的 `%USERPROFILE%\.ssctl\bin\ssctl.exe` 或 macOS 的 `~/.ssctl/bin/ssctl`，也支持从宿主进程 PATH 查找。

## Windows 安装

在 PowerShell 下载项目：

```powershell
git clone https://github.com/Architect15806/AIS-Connector.git
Set-Location AIS-Connector
python --version
ssh -V
```

1. 打开 `chrome://extensions`，开启开发者模式。
2. 选择“加载已解压的扩展程序”，加载 **extension 子目录**，不是项目根目录。
3. 复制扩展卡片上的 ID，在项目目录执行：

```powershell
$extensionId = Read-Host '请粘贴 Chrome 扩展 ID'
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -ExtensionId $extensionId
```

安装脚本使用当前 Python 路径，在个人目录生成宿主文件并注册到当前用户的 Chrome 配置，通常无需管理员权限。

打开插件侧栏，确认“本地服务就绪”。若侧栏位于左侧，可在 Chrome 设置中调整。插件内“安装教程”会自动填入当前扩展 ID，并提供复制命令。

## macOS 安装

在 Terminal 中执行：

```sh
git clone https://github.com/Architect15806/AIS-Connector.git
cd AIS-Connector
python3 --version
ssh -V
```

安装公司提供的 macOS ssctl。在 Chrome 开发者模式中加载项目的 `extension` 子目录，复制扩展 ID，然后执行：

```sh
printf '请粘贴 Chrome 扩展 ID，然后按回车: '
read -r extension_id
sh ./install-mac.sh "$extension_id"
```

宿主注册清单位于 `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/`。首次认证可能提示 Keychain 授权。真实 Mac 环境尚待验证。

## 日常使用

1. **添加用户**：填写邮箱前缀，例如 `example.user@example.com` 对应 `example.user`。
2. **登录**：选择用户，点击“登录”，输入当前六位 Alilang Token。明文输入，仅用于本次认证，不保存。
3. **添加连接**：填写别名和 namespace。可在实例 Web IDE 中执行：

   ```sh
   echo "$AISTUDIO_NAMESPACE"
   ```

4. 展开连接，点击“初始化连接”，使用当前用户的凭据连接 `main` 容器。
5. 等待“SSH 验证通过”，复制显示的命令到本机终端执行。

所有用户共享连接列表；切换或删除用户不会中断已有隧道。连接别名必须唯一；修改运行中连接的 namespace 前应先断开。

### 检测和重连

- 默认每 5 分钟检测一次，设置范围为 0.1–1440 分钟。
- 检测执行 SSH `hostname`，连接超时 6 秒，整体超时 10 秒。
- 检测成功保留端口；失败会关闭旧通道并重建，可能更换端口、中断已有 SSH 会话。
- 初始化、手动刷新和自动检测会重置倒计时；修改间隔立即请求检测运行中的连接。
- “全部刷新”不初始化已断开的连接。
- 时间使用 Asia/Shanghai，精确到秒，并显示相对时间。认证时间仅是上次操作时间，不代表凭据仍有效。
- 关闭侧栏或 Chrome 后，独立后台仍可维护隧道；电脑重启后需要重新初始化。

## Agent 连接

底部“Agent 连接”页面显示当前机器的 JSON 路径和项目内 skill 的实际路径，可直接复制给 Agent：

```text
skills/ais-connector/SKILL.md
```

| 系统 | 自动更新的连接文件 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\AISConnector\agent\connections.json` |
| macOS | `~/Library/Application Support/AISConnector/agent/connections.json` |

文件格式如下，端口仅为示例，不应缓存：

```json
{
  "示例连接": "ssh -p 12345 127.0.0.1"
}
```

Agent 每次新建 SSH 会话前读取 JSON，按完整别名选择连接；失败后重读并重试一次，仍失败则提醒用户检查登录状态和初始化。

文件只包含最近检测可用的连接；重连期间别名可能消失。Agent 必须在运行插件的同一台电脑上使用 localhost 命令，不能修改该文件或擅自重建插件的隧道。新端口不能恢复已中断的 SSH 会话。项目 skill 不会自动安装到 Agent 的全局配置。

## 居家：VPN 临时路由

此功能仅诊断和生成命令，**不执行网络修改**，仅支持 Windows。

1. 连接公司 VPN，打开“居家”页面。
2. 核对 worker 候选、VPN 网卡和网关；有多个候选时手动选择。
3. 复制命令到管理员 PowerShell 执行。
4. 重新检测路由，再回主页刷新 SSH 状态。

候选来自错误、后台输出和 ssctl 网络端点，可能过期；网卡名称只提供线索，信息不足时不会猜测。生成单个目标 IP 的 `/32` 临时路由，共享该 IP 的连接可共同受益，不覆盖未来未知 worker。

命令检查现有路由，不覆盖冲突配置；另提供撤销命令。路由重启后失效，VPN 网关或 worker 变化后需重新检测。正确路由不保证 VPN 允许访问目标。

## 日志

日志页每 5 秒更新，显示最新 200 条；个人目录的 `logs/events.sqlite3` 最多保留 2000 条。记录操作开始、完成、失败及后台状态变化。

不保存完整请求、Token 或认证输出，诊断文本做脱敏；日志仍可能包含用户名、namespace 和网络地址，分享前请检查。

旧版后台不会热加载日志代码，页面会补充当前状态快照；需要完整后续事件时，在方便时断开并重新初始化连接。日志写入失败不会中断隧道。

## 个人数据与安全

个人目录独立于源码：

- Windows：`%LOCALAPPDATA%\AISConnector`
- macOS：`~/Library/Application Support/AISConnector`

| 内容 | 位置 |
| --- | --- |
| 用户、连接、认证结果 | `profile.json` |
| 检测设置、运行状态 | `settings.json`、连接 ID 对应的 JSON |
| Agent 目录及命令 | `agent/` |
| 日志 | `logs/` |
| 本机宿主启动配置 | `native-host/` |
| 认证凭据 | Windows Credential Manager / macOS Keychain |

本机可通过被忽略的 `.personal` 入口访问个人目录；此入口不会随克隆创建。旧浏览器数据在新版侧栏首次成功打开时迁移，写入成功后才删除旧副本。ssctl / OpenSSH 自身配置及 known_hosts 不迁移。

`.gitignore` 排除个人目录、日志、缓存、环境文件和生成的宿主注册文件。不要强制添加个人数据或将其复制进发布包；忽略规则不是加密保护。

`extension/assets/` 中的 Logo 原图和图标是项目资源，纳入版本管理。

认证通过独立子进程的 `-alilang-token` 参数传入 Token，不经 shell、不记录请求；认证期间有权限读取本机进程参数的程序仍可能看到它。宿主只接受注册扩展 ID 的调用，不提供任意 shell 执行接口。

## 更新与排错

源码更新后在 `chrome://extensions` 重新加载扩展，并重新打开侧栏。移动项目、切换 Python 或扩展 ID 变化后，应重新运行安装脚本。后台进程不热加载源码，涉及后台逻辑的更新需在方便时断开并重新初始化。

- **清单文件缺失**：应加载 `extension` 子目录。
- **Specified native messaging host not found**：检查宿主注册及扩展 ID，重新执行安装命令。
- **Native host has exited**：检查 Python 路径、目录及运行权限。
- **SSH / WebSocket 超时**：检查日志、实例及 VPN 路由，不直接判定认证过期。
- **本地服务就绪**：表示宿主可用且找到了 ssctl，不代表已认证或已连接。
- **手动登录与插件不同**：插件使用按用户名隔离的凭据，手动 ssctl 可能使用另一组默认凭据。

## 工程结构与测试

```text
extension/          侧栏及独立页面
native-host/        Python 宿主、安装配置和 VPN 诊断
skills/             Agent 连接 skill
tests/              后台和前端行为测试
install.ps1         Windows 注册脚本
install-mac.sh      macOS 注册脚本
```

在项目根目录执行（macOS 将 python 换为 python3）：

```sh
python -m unittest discover -s tests -v
node tests/test_panel.cjs
node tests/test_pages.cjs
node tests/test_home.cjs
node --check extension/panel.js
node --check extension/home.js
```

自动化测试无需真实凭据；真实 SSH 端到端验证仍需有效账号、可用实例和网络。

实现注意：ssctl 的 stdin 管道需在隧道存活期间保持打开。部分版本在 stdin 为 DEVNULL 或提前关闭时会出现“端口监听但 SSH banner 超时”。

## 卸载

先在插件中断开连接，再从 Chrome 删除扩展。Windows 在项目目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\uninstall.ps1
```

仅移除当前用户的宿主注册，不删除个人数据和凭据。macOS 可在 Finder 中前往 `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/`，将 `com.ais.connector.json` 移入废纸篓；个人数据和 Keychain 凭据继续保留。
