# 2026-09-27 模型下载排错记录

本轮范围仅为下载排错与资源完整性核验。模型推理、结果分析和独立重跑由用户继续执行。

## 已定位的问题

1. 服务器直连 `huggingface.co:443` 超时，开启 AutoDL 学术加速后可访问仓库元数据。
2. `hf-xet` 下载权重时，`cas-server.xethub.hf.co` 返回 HTTP 401。该现象不能直接归因为用户没有模型访问权限。
3. 设置 `HF_HUB_DISABLE_XET=1` 后转为 HTTP 下载，进程仍有进展，但两个大分片进度不均匀；整体 `8/10` 是完成的文件数量，不是字节百分比。
4. 将模型下载改为直连 HF-Mirror，并在该下载子进程中移除代理变量后，两个大分片均继续增长。保留并复用原缓存，没有删除模型文件。

实际环境：`huggingface-hub==0.36.2`、`hf-xet==1.6.0`。本轮没有升级依赖、修改上游算法或改变模型版本。

## 固定模型身份

- 模型：`Qwen/Qwen3-4B`
- revision：`1cfa9a7208912126459214e8b04321603b3df60c`
- 权重总字节数：8,044,982,000（约 8.04 GB，不含分词器等小文件）。
- 镜像与 Hugging Face 官方同一 revision 的 API 元数据已逐项对照，分片大小和 SHA-256 相同。

| 分片 | 字节数 | 官方 SHA-256 |
| --- | ---: | --- |
| model-00001-of-00003.safetensors | 3,957,900,840 | 328a91d3122359d5547f9d79521205bc0a46e1f79a792dfe650e99fc2d651223 |
| model-00002-of-00003.safetensors | 3,987,450,520 | 6cd087b316306a68c562436b5492edbcf6e16c6dba3a1308279caa5a58e21ca5 |
| model-00003-of-00003.safetensors | 99,630,640 | e4bf436957184f4eeb86a80e9db394503f1f56446b2e6b7edeac5b81470f4ca1 |

## 服务器端操作与文件位置

在项目根目录、已激活的 `.venv`、tmux 会话中执行。恢复前先确认没有另一份 `prepare` 同时写缓存；已完成的缓存不要删除。

```bash
(
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY
    export HF_ENDPOINT=https://hf-mirror.com
    export HF_HUB_DISABLE_XET=1
    export HF_HUB_DISABLE_IMPLICIT_TOKEN=1
    export HF_HUB_DOWNLOAD_TIMEOUT=60
    export HF_HUB_ETAG_TIMEOUT=20
    set -o pipefail
    python -u scripts/single_question.py prepare 2>&1 | tee -a runs/setup/prepare-mirror.log
)
```

括号创建子 shell，网络设置只影响这次命令，不修改全局 shell 配置。模型下载的 HTTP 重定向仍可能经过 Hugging Face 文件存储域名。

如果模型已经齐全、最后只有 NLTK 下载失败，可单独使用 AutoDL 学术加速准备分句资源：

```bash
(
    source /etc/network_turbo
    python - <<'PY'
from pathlib import Path
import nltk
target = Path('data/nltk')
target.mkdir(parents=True, exist_ok=True)
nltk.download('punkt_tab', download_dir=str(target), raise_on_error=True)
PY
)
```

本轮已单独完成 `punkt_tab` 下载和解压。它不是模型权重，也不是训练数据。

- 模型缓存：`data/model-cache/`
- 分句资源：`data/nltk/`
- 旧下载记录：`runs/setup/prepare.log`
- 镜像下载记录：`runs/setup/prepare-mirror.log`
- 下载退出码：`runs/setup/prepare-mirror.exit`
- 最终成功的准备日志：`runs/setup/prepare-final.log`
- 文件校验明细：`runs/setup/download-verification-20260927.json`

## 验收状态

下载恢复后两次采样的总写入速率约 8.4 MB/s，仅代表当时这台机器的网络情况，不是速度保证。2026-09-27 已完成：

- 三个权重分片的实际大小与官方一致，SHA-256 全部通过。
- 其余七个配置/分词器文件的大小与官方一致，Git blob SHA-1 全部通过。
- 固定 revision、上游源文件校验及 `validate_snapshot()` 检查通过。
- NLTK 英文 `punkt_tab` 资源存在。
- 最终 `prepare` 命令退出码为 0；没有加载模型或运行推理。

镜像下载到 10/10 后，原进程仍等待无法直连的 NLTK 索引请求，因此仅中断这个准备进程，再以“模型本地缓存＋NLTK 学术加速”完成收尾。原 `prepare-mirror.exit` 的中断状态不是权重损坏，最终成功状态以 `prepare-final.log` 和文件校验明细为准。

以下收尾命令只适用于模型缓存已经完整的情况，`HF_HUB_OFFLINE=1` 不会下载缺失的模型文件：

```bash
(
    source /etc/network_turbo
    HF_HUB_OFFLINE=1 HF_HUB_DISABLE_XET=1 python -u scripts/single_question.py prepare
)
```

下载完整后，由用户执行：

```bash
python scripts/single_question.py check
```

应检查 `problems: []`。`check` 检查文件和环境，不运行模型生成；完整权重 SHA-256 核验与后续实际推理也应分别记录。

## 来源

- [AutoDL 学术资源加速与镜像入口](https://www.autodl.com/docs/network_turbo/)
- [Hugging Face 环境变量](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables)
- [HF-Mirror 使用说明](https://hf-mirror.com/)
- [官方固定 revision 元数据](https://huggingface.co/api/models/Qwen/Qwen3-4B/revision/1cfa9a7208912126459214e8b04321603b3df60c?blobs=true)
