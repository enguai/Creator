# 薪资任务统一使用 Project01 的 skill

Project01-薪资的项目目录是 `C:\Users\Administrator\Documents\work01`。
它使用的共享技能目录是 `C:\Users\Administrator\.codex\skills\live-payroll`。
网站本地 Worker 与公开网站 Worker 现在明确使用这份共享技能，入口为该目录下的 `SKILL.md`。

## 修改一次即可生效

在 Project01 中要求修改上述共享 skill，包括其 `references`、`scripts`、`assets` 下的规则、生成器和评级。每个新开始处理的网站薪资任务都会重新读取这个入口及它引用的当前文件。

只改 work01 中某次任务的临时脚本、排班 JSON、结果表格或聊天指令，不等于更新共享 skill，也不会自动影响网站任务。

普通 skill 内容更新不需要重启 Worker，不需要推送网站 GitHub，也不需要更新云服务器。Worker 程序自身修改才需要重启 Worker。

已完成结果不自动重算。已开始处理的任务可能已读取旧规则；要应用新规则，应在修改完成后提交新任务。尽量在空闲时完成一组相关规则、脚本及评级文件的更新，避免正在计算时读到修改中的文件。

## 网站与 skill 的职责

- 网站只提供直播间、周期、上传材料和结果保存位置。
- 算法、缺失资料处理、评级更新方式、生成脚本、表格布局、校验流程由共享 skill 决定。
- 上传的评级更新只影响该次网站任务，不能修改共享评级或其他人的任务。需要永久更新评级时在 Project01 修改共享评级。
- 薪资任务等待 skill 完成校验，不再因为结果文件大小暂时不变就提前终止 Codex。
- skill 入口不存在或为空时明确失败，不回退到旧技能。
- 成功任务 summary 中的 `skill_source_path` 记录入口，`skill_entry_sha256` 记录任务开始时 SKILL.md 的指纹。该指纹仅代表入口文件，不代表全部脚本、评级文件的快照。

## 路径配置

两个启动脚本 `start_codex_form_worker.ps1`、`start_local_codex_worker.ps1` 使用当前 Windows 用户的 `.codex\skills\live-payroll\SKILL.md`，传给 Worker 的配置名为 `CREATOR_PAYROLL_SKILL_PATH`。
换电脑运行时，也需要把同一份最新 skill 安装到该电脑；此设置不会自动跨电脑同步文件。

检查命令（本地 PowerShell）：

```powershell
Get-Item "$env:USERPROFILE\.codex\skills\live-payroll\SKILL.md" | Select-Object FullName,LastWriteTime
Get-ScheduledTask -TaskName CreatorCodexFormWorker,CreatorLocalCodexWorker | Select-Object TaskName,State
```
