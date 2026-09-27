# 每天收工时同步 GitHub

推荐在 Mac 的项目目录统一整理、检查、上传。无需 GPU，无需激活实验 `.venv`；脚本只使用 Python 标准库和 Git。它只处理运行脚本所在的这一份仓库，不会自动拉取服务器文件，也不会同步 Notion 页面。

## 每天的流程

在 VS Code 打开本项目的终端，确认 `pwd` 是 `codestop-reproduction`。查看修改：

```bash
python3 scripts/daily_sync.py status
```

选择当天要保存的文件。例如，保存阅读笔记与自己写的代码，同时保存上游代码里的注释：

```bash
python3 scripts/daily_sync.py stage --notes docs src
git diff --cached
```

- `stage`：把指定文件的当前版本放进 Git 暂存区，尚未提交和上传。
- `--notes`：把 `upstream/CoDE-Stop` 中相对固定版本的修改，导出为 `docs/upstream-notes/日期.patch` 和对应的版本/校验信息。包括已跟踪文件的暂存及未暂存修改，不修改原文件或子模块指针。新增而未跟踪的上游文件会报错，先整理到 `src/` 再继续。
- `docs src`：本次选择这两个目录内的修改。也可以写具体文件名，或加上 `configs scripts tests README.md` 等需要上传的路径。
- `git diff --cached`：查看即将提交的实际内容，`+` 表示增加，`-` 表示删除；按 `q` 退出。导出的补丁里会出现两层差异，阅读原始修改可运行 `git -C upstream/CoDE-Stop diff HEAD`。

检查后执行，日期与说明换成当天实际工作：

```bash
python3 scripts/daily_sync.py publish -m "2026-09-28：完成补答函数阅读并整理笔记"
```

脚本先在本机创建提交，再推送 `origin/main`，最后读回远端提交号。只有出现“上传并核对成功”才表示本次核验完成。**Git 暂存区里原先已有的合规文件也会一起提交，所以每次都要查看完整的 `git diff --cached`。** `publish` 不会自动加入暂存之后新写的内容；后续修改请再次 `stage`。

如果选错文件，下面的命令仅撤销暂存，保留文件内容：

```bash
git restore --staged -- docs/某个文件.md
```

脚本不会替你判断笔记或研究结论是否正确。学习注释的补丁标记为源码修改快照，不代表通过了功能验证。

## 只保存上游阅读注释

```bash
python3 scripts/daily_sync.py stage --notes
git diff --cached
python3 scripts/daily_sync.py publish -m "2026-09-28：记录 DEER 阅读注释"
```

主仓库只记录子模块的提交指针；直接推送主仓库不会保存子模块中的未提交修改。补丁让这些修改可以在自己的 CoDE 仓库里浏览、回溯、恢复，同时保留官方代码的固定版本。[Git 子模块文档](https://git-scm.com/docs/gitsubmodules)

同一天重新导出会更新当天文件，已提交的旧版可从 Git 历史找回；每份补丁是相对其 `base_commit` 的完整修改，不要把连续多天补丁叠加应用。如果上游没有修改，脚本不会清除已有补丁。`.vscode/`、缓存、忽略文件和上游未跟踪文件不属于补丁备份范围。

恢复时，在一份**干净且 HEAD 与 JSON 中 base_commit 相同**的子模块副本上先检查，再应用选定的一份补丁。以下日期仅为示例：

```bash
git -C upstream/CoDE-Stop status --short
git -C upstream/CoDE-Stop rev-parse HEAD
cat docs/upstream-notes/2026-09-28.json
git -C upstream/CoDE-Stop apply --check ../../docs/upstream-notes/2026-09-28.patch
git -C upstream/CoDE-Stop apply ../../docs/upstream-notes/2026-09-28.patch
```

`apply --check` 只验证可应用性；最后一行才写入文件。已有同样注释时不用重复应用。不要为了恢复补丁覆盖尚未保存的工作。

## 保存实验结果

原始输出仍放在被忽略的 `runs/`。核对过的结果和说明整理到 `results/`，例如今天已上传的 `results/teaching/2026-09-27/`。之后选择具体归档目录：

```bash
python3 scripts/daily_sync.py stage results/teaching/2026-09-27
git diff --cached
python3 scripts/daily_sync.py publish -m "2026-09-27：归档两次教学实验"
```

若结果只在服务器上，Mac 脚本不会自动看到它。可以从服务器传到本项目，或在服务器该仓库里自行配置 GitHub 认证后使用同一脚本。建议当前阶段以 Mac 为主要提交端，避免两边同时提交引起分叉。大型输出和权重另用文件存储，GitHub 中保留索引、哈希和整理后的报告。

日常脚本限制为 `docs/ src/ configs/ scripts/ tests/ results/` 和少量项目根文件，遵守 `.gitignore`；还会拦截常见凭据文件名、模型文件、符号链接以及单文件大于 5 MiB 的改动。5 MiB 是本项目脚本的限制，不是 GitHub 上限。**这些检查不是完整的密钥扫描**，文字里粘贴的密码、API key、私人信息仍需自己在差异中排除。删除文件也会被记录，因此同样要检查。

## 网络、认证或版本冲突

提交成功、推送失败时，不必重复提交，网络恢复后：

```bash
python3 scripts/daily_sync.py push
```

超时可能发生在 GitHub 已收到提交之后；以重试核对或 GitHub 实际记录为准。脚本不会关闭 TLS 验证、配置代理或悄悄切换上传方式。若像 9 月 27 日一样普通 Git HTTPS 不通而官方 API 可用，可把错误信息发给协助者，另行核验并通过官方 API 同步。

若提示 `non-fast-forward`，说明远端已有当前本地分支不包含的提交。先停止，保留修改，让协助者核对差异；不要用 `--force`，也不要反复重新提交。[Git 推送文档](https://git-scm.com/docs/git-push)

首次在另一台机器使用时需要独立配置 GitHub 认证。推荐使用 GitHub CLI 的 `gh auth login` 和 `gh auth setup-git`，按终端提示登录，不把令牌写进仓库或聊天。当前 Mac 已有登录；无需再次配置。[GitHub CLI 认证文档](https://cli.github.com/manual/gh_auth_login)

## 与普通 Git 命令的关系

`stage` 对应选择性 `git add`；`publish` 对应 `git commit` 加 `git push`；`push` 只重试上传。VS Code 的 Source Control 面板也能查看差异、暂存和提交，但上游子模块的笔记仍需通过 `--notes` 导出后一起保存。
