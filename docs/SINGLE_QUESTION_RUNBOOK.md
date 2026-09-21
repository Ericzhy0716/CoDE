# 单题三方法诊断：从本地准备到第一条真实记录

更新：2026-09-21。当前完成的是入口、配置和本地工程检查；尚未下载模型或执行 GPU 推理。用户已确认有服务器，目前关机；显卡型号与本轮运行额度待部署时确认。

## 1. 这次只验收什么

亲自看懂一条 `题目 → 基础生成 → Vanilla补答 → DEER/CoDE检查 → 最终答案 → 判分` 链路。默认题是手写算术教学题 `37×43−29×41=402`，不是开发集或测试集，不进入论文结果。

默认使用原 Qwen3-4B BF16，固定模型 revision `1cfa9a7208912126459214e8b04321603b3df60c`（2026-09-21经 Hugging Face 模型元数据核对），基础生成上限2048 token，单GPU、batch=1。2048不是原论文的32K设置；这一次也不能验证32K显存或完整复现。

入口为 `scripts/single_question.py`，配置为 `configs/single_question.json`。命令均在本仓库根目录执行。脚本默认路径相对于自身所在仓库定位，不需要填个人Mac路径。

## 2. 现在在 Mac 上做

```bash
python3 scripts/single_question.py plan
```

这一步只读配置、核验固定上游文件和显示执行顺序；不加载模型、不下载数据、不连接服务器。应能指出：题目、标准答案、模型版本、2048上限和四个阶段分别在哪里。

可以逐段读 `src/diagnostic_core.py` 的 `execute_stage()`，理解“结果先保存，判分后执行”。不必先读完全部论文和源码。

## 3. 在服务器准备环境与文件

先确认显卡型号、剩余磁盘、驱动、可运行时长和本轮额度。下载与安装若能在平台的无GPU模式完成，优先在那里准备；不要为了阅读文档一直开着计费GPU。本入口不会自动开机、租卡或充值。

已有仓库时先检查是否有自己的未提交修改，然后更新：

```bash
git pull --ff-only
git submodule update --init --recursive
```

没有仓库时：

```bash
git clone --recurse-submodules https://github.com/Ericzhy0716/CoDE.git
cd CoDE
```

使用独立 Python 3.10–3.12 环境。下面是 PyTorch 官方提供的2.9.1/CUDA12.8构建示例，需要实际驱动兼容；不要覆盖已有实验环境。其余版本来自固定上游 requirements。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements-diagnostic.txt
```

官方构建来源：[PyTorch previous versions](https://pytorch.org/get-started/previous-versions/)。本地CPU检查不证明这套环境已在用户显卡上通过；实际以接下来的检查及首条生成结果为准。

下面这一条会联网下载约8GB的模型权重及分词/分句资源，请先确认网络和磁盘：

```bash
python scripts/single_question.py prepare
```

默认保存到忽略Git的 `data/model-cache/` 和 `data/nltk/`；Hugging Face 下载支持复用缓存。`prepare`会检查索引要求的每个权重分片，避免仅有config文件就误判完整。它不加载模型或推理。

GPU就绪后运行：

```bash
python scripts/single_question.py check
```

通过标准：输出 `problems: []`，有实际GPU型号、BF16能力和全部权重分片。失败先处理列出的那一项；不能把未装依赖的Mac检查当成服务器失败。

## 4. 按阶段执行，先观察再继续

首次先只运行基础生成：

```bash
python scripts/single_question.py run --stage base
python scripts/single_question.py inspect
```

检查 `runs/single-question/base.json`：真实回答是否保存、原始生成token IDs是否存在、耗时/显存是否有值。`grading.json`是教学题的本地数字判分：缺少 `</think>`、答案不完整或不支持的表达式记为 `needs_review`，不会静默判错。这里不用付费裁判，不能替代论文的MATH500判分协议。

基础输出确认后，逐个执行：

```bash
python scripts/single_question.py run --stage vanilla
python scripts/single_question.py run --stage deer
python scripts/single_question.py run --stage codestop
python scripts/single_question.py inspect
```

Vanilla有必要时使用上游 `generic_forceans()` 补答；DEER/CoDE共用它的输出。三个方法的上游算法函数从固定源码按函数定义加载，不执行整个上游入口及其自动下载/裁判初始化副作用，也不改上游文件。

理解四阶段后，可用 `run --stage all` 顺序执行。已有成功阶段不会重新生成；失败的DEER不会抹掉Vanilla，也不会阻止独立的CoDE诊断。每个新进程会重新加载权重，初学时分步观察优先，熟悉后一次加载完成全部阶段。

## 5. 怎样解释结果与恢复

| 记录 | 看什么 |
| --- | --- |
| `manifest.json` | 样本、配置、模型revision、上游与封装代码哈希 |
| `environment.json` | 实际Python/依赖/CUDA/GPU及完整快照位置 |
| `base.json` / `vanilla.json` | 原始推理、补答、token IDs、阶段时间和显存 |
| `deer.json` / `codestop.json` | 原始方法输出、探测概率与停止信息；CoDE保留退化分数和当前阈值 |
| `events.jsonl` | 逐次生成、检查点及异常的持久化记录 |
| `*.error.json` | 最近一次失败及已完成的部分证据；历史失败仍在events中 |
| `grading.json` | 独立教学判分及其来源文件哈希；没有整体准确率结论 |

如果没有 `Wait` 检查点，DEER/CoDE返回原答案并给出警告。这只说明入口完成，探测/提前停止分支尚未覆盖。不要插入假的 `Wait` 冒充模型轨迹；下一步选择独立开发题或用真实已有前缀单独诊断。

如果试答只生成1–2个token、出现非有限置信度或EOS处理异常，当前方法明确失败，并先保留已得到的试答记录。固定上游在这些边界存在置信度问题；本入口不会把它们改成0、1或跳过后继续冒称原算法。检查证据后，再决定有来源记录的工程/公式适配。

断线后，当前正在生成的阶段可能需要重跑；已完整保存的阶段会复用。重跑相同命令不会覆盖成功结果。配置、代码或软件/GPU改变时，使用新的运行目录，例如 `--run-dir runs/single-question-second`，保留原始记录。并发进程不能共用同一运行目录。不要把“关掉本地窗口”当成服务器进程已停；在平台确认任务结束及实例关机状态。

只重新判分，不加载模型：

```bash
python scripts/single_question.py grade
```

## 6. 本轮与原论文的区别

- **上游算法口径**：保留 `use_log=True`、严格大于阈值、零起始ramp索引、原试答概率公式和实际21-token探测上限；尚不是论文概率域公式对齐版。极短/异常试答由外层拒绝继续执行。
- **阈值来源**：0.9→0.95、ramp=2及退化阈值2.0借自现有4B/MATH500参考配置，DEER=0.95来源于代码示例；没有在这道教学题上校准，也不据此称为主表参数的完整复现。
- **工程设置**：关闭父前缀KV复用（`cp_cache=false`，上游已有选项），每次检查会重新预填充前缀；试答内部仍使用自回归缓存。后续单独验收前缀KV的等价性和长序列内存。
- **随机性**：基础生成seed42，Vanilla补答43，DEER/CoDE各自从44开始；记录这些新增实验种子，不声称恢复作者的seed。
- **成本**：上游`work/response_tokens`保留原口径，另存真实生成token IDs、探测和耗时。DEER/CoDE在已有轨迹上回放，耗时含日志，不能当成在线早停加速或总租金。
- **证据**：标准库单元检查与模拟边界检查仅验证编排/错误处理，真实GPU兼容、真实探测及最终效果尚待用户运行。

第一条运行后，反馈阶段名、是否出现检查点、错误末尾或关键输出、实际显存和耗时即可。不要发送密码、密钥或完整身份令牌。
