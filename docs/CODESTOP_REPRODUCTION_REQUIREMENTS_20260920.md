**CoDE-Stop 复现实验要求与执行边界**

核查日期：2026-09-20。对象为 *Early Stopping for Large Reasoning Models via Confidence Dynamics*，arXiv:2604.04930v2（2026-08-14）。官方仓库核查提交：`b5081e7c2abe23bb1d19649421cc13522fee7c50`。本次仅阅读论文、下载并静态检查官方代码；未连接付费GPU、安装远程环境或运行推理。

来源：[论文v2](https://arxiv.org/html/2604.04930v2)、[版本记录](https://arxiv.org/abs/2604.04930)、[固定提交的官方代码](https://github.com/sudoparsa/CoDE-Stop/tree/b5081e7c2abe23bb1d19649421cc13522fee7c50)。下文把“论文报告”“代码现状”和“我们的执行建议”分开记录。论文与代码仍有未对齐之处，公开材料目前不足以指定一套毫无歧义的全文复现命令。

**1. 复现对象及范围**

CoDE-Stop在推理过程中试探中间答案，用答案置信度及其变化决定是否提前结束思考。无需训练主模型或辅助预测器，但需要校准停止阈值。基础轨迹生成和反复探测可能耗费大量推理时间。

| 范围 | 需要完成的内容 | 可以使用的结论 |
|---|---|---|
| 运行检查 | 少量题，检查环境、输出、数值、显存和时间 | 代码能够运行；不能评价论文效果 |
| 单模型单基准复现 | 原模型、完整基准、原采样次数、预算、判分和对照；标明代码/论文差异 | 已复现论文中的指定子集 |
| 主要结论复现 | 多模型、多基准、关键强对照，合理复现准确率与成本权衡 | 支持或不支持论文主要经验结论 |
| 全文复现 | 表1、表2、提示组合、参数与方法消融、校准迁移、附录分析 | 明确列出所有完成和缺失项目后报告全文覆盖情况 |

通过有限诊断后，可先完成Qwen3-4B / MATH500 / Vanilla、DEER、CoDE-Stop，再扩充EAT与更难的基准。该阶段是有边界的复现子集，不等于全文复现。当前是否扩大实验，以同目录的创新可行性审查为准。

**2. 主实验模型与数据**

论文§3.1使用以下四个原始检查点；具体Hub revision需在准备阶段固定。更新版Thinking/Instruct检查点、量化版和不同蒸馏基座均不能直接替代。

| 论文模型 | 官方代码模型标识 | Hugging Face模型ID |
|---|---|---|
| Qwen3-4B | `qwen-4b` | `Qwen/Qwen3-4B` |
| Qwen3-14B | `qwen-14b` | `Qwen/Qwen3-14B` |
| DeepSeek-R1-Distill-Llama-8B | `deepseek-r1-llama-8b` | `deepseek-ai/DeepSeek-R1-Distill-Llama-8B` |
| Llama-3.1-Nemotron-Nano-8B-v1 | `llama-8b` | `nvidia/Llama-3.1-Nemotron-Nano-8B-v1` |

模型映射与加载配置来源：[models.py](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/models.py)。

| 基准 | 题数 | 每题独立采样次数 | 每模型基础轨迹数 | 数据源/划分 |
|---|---:|---:|---:|---|
| AIME2024+2025 | 60 | 15 | 900 | `HuggingFaceH4/aime_2024` train；`opencompass/AIME2025` 的I/II test |
| MATH500 | 500 | 2 | 1000 | `HuggingFaceH4/MATH-500` test |
| GSM8K | 1319 | 1 | 1319 | `openai/gsm8k` main/test |
| GPQA-Diamond | 198 | 5 | 990 | `Idavidrein/gpqa` gpqa_diamond/train |
| 主评测合计 | 2077 | — | **4209** | 每模型、每种基础提示 |
| AMC23校准 | 40 | 2 | **80** | `math-ai/amc23`；尚未接入官方loader |

来源：[论文§3.1及附录F](https://arxiv.org/html/2604.04930v2#S3.SS1)、[dataset_loader.py](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/dataset_loader.py)、[AMC23](https://huggingface.co/datasets/math-ai/amc23)。GPQA虽然数据源的split名为train，在本实验中用于评测，不应拿来调停止阈值。

四模型主实验需要16,836条基础完整轨迹，另有320条AMC校准轨迹；这不含提示变体、16K实验及中间答案探测。不同停止方法共享对应的基础轨迹，不必为每种停止方法重新独立生成一批完整轨迹。

访问GPQA需要Hugging Face账号接受数据访问条件；原题不应随公开代码仓库传播。需要保留样本顺序及官方按样本序号固定的选项打乱方式。[GPQA数据页](https://huggingface.co/datasets/Idavidrein/gpqa)

**3. 软件及机器要求**

官方requirements固定版本如下，不能把不同版本环境的结果无说明地合并。

| 依赖 | 版本 |
|---|---|
| torch | 2.9.1 |
| transformers | 4.51.3 |
| datasets | 3.6.0 |
| accelerate | 1.12.0 |
| math-verify | 0.9.0 |
| nltk | 3.9.2 |
| openai | 2.26.0 |

来源：[requirements.txt](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/requirements.txt)。还需下载NLTK的`punkt_tab`。代码语法至少需要Python3.10；建议用Python3.11并保存完整依赖锁定文件。Python3.11是执行建议，不是论文公布的版本。

代码默认BF16、Transformers直接推理，未要求使用vLLM或FlashAttention。初次复现保留该实现；后续优化应作为独立工程版本核对输出与指标。RTX PRO 6000环境需验证实际安装的PyTorch CUDA构建支持这张卡，驱动界面显示CUDA版本并不能证明依赖可运行。

下列是我们的配置建议，不是论文报告的最低硬件：

| 资源 | 单模型4B第一阶段建议 |
|---|---|
| GPU | 1张RTX PRO 6000 96GB；80GB级GPU也值得实测，不先承诺峰值 |
| 并行度 | 先batch=1，按样本分块；第二张卡用于独立分块或另一模型时记录分片和随机种子 |
| CPU / RAM | 约16核、96–128GB内存较稳妥；用户此前110GB内存实例属于合适起点 |
| 磁盘 | 4B阶段预留约100GB；保留全部模型与多轮输出建议200GB以上，按实际缓存增长调整 |
| 网络 | 可下载完整模型、数据、依赖；采用API判分时需能访问裁判服务 |

论文没有给出可作为保证的GPU最低型号、总GPU小时或租用成本。4B权重能装入显存，不代表32K长前缀及探测缓存峰值一定安全。代码的缓存复制与重复前缀计算也会影响速度；必须先测短、中、长样本。不要为了让程序运行而默默把32K改成4K、使用4bit或换小模型。

**4. 生成、停止与校准设置**

主结果最大新生成token数为**32768**；附录另有**16384**预算实验。这是生成上限，不是每题必须生成的数量，也不是输入加输出总上下文长度。提示、最终答案追加及模型上下文容量均需检查。

官方代码Qwen3配置：temperature=0.6、top_p=0.95、top_k=20、min_p=0，基础生成使用随机采样。DeepSeek-Llama8B代码显式设置temperature=0.6、top_p=0.95，其余读取检查点配置；Nemotron也应保存实际加载后的generation_config。保留原chat template和Nemotron的thinking系统提示。官方当前没有完整的随机种子锁定流程，复现时应新增明确的种子记录，而不能宣称已恢复作者原seed。[模型配置代码](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/models.py)

论文v2方法参数：

| 项目 | 论文设置 |
|---|---|
| 推理检查点分隔词 | `Wait` |
| 置信度起始阈值 | r_min=0.9 |
| 置信度最高阈值 | r_max=0.95 |
| ramping steps | 2 |
| 不稳定指示器阈值 | δ=0.55 |
| 不稳定指示器 | 1[2c_i−c_(i−1)<δ] |
| 历史权重 | log(T_current/T_i)+1 |
| 停止条件 | 置信度达到当前阈值，或累计退化分数达到τ |

校准在AMC23的40题×2次采样上进行，搜索τ、r_min及ramping steps。论文选择达到最高校准准确率的最小τ，然后按**平均推理检查步数**迁移：`τ_target = τ_AMC × mean_steps_target / mean_steps_AMC`。不能直接用平均token数相除替代检查步数。完整搜索网格尚未公开齐全。[论文§2.2、附录D/F](https://arxiv.org/html/2604.04930v2#A6)

论文表7给出的32K转移阈值：

| 模型 | AMC23 | AIME | MATH500 | GSM8K | GPQA-D |
|---|---:|---:|---:|---:|---:|
| Qwen3-4B | 3.5 | 5.3 | 2.0 | 0.9 | 4.6 |
| Qwen3-14B | 3.3 | 6.9 | 2.3 | 0.9 | 5.5 |
| DeepSeek-Llama8B | 35 | 90.7 | 20.5 | 7.6 | 64.7 |
| Nemotron8B | 8 | 15.6 | 4.6 | 2.2 | 11.8 |

固定表7参数重跑和从AMC重新估计参数是两项不同的复现任务；两者均应报告。表3部分AMC步数与表7缩放结果不一致，不能自行猜测并改写原文。表1是转移阈值结果；表6分隔词比较中的Wait结果沿用逐基准调参值，不能混作表1验收目标。逐基准调参与转移参数的直接比较见表8。

**5. 对照及全文实验清单**

主表包括Vanilla、Think-or-Not、DEER、EAT、RCPD、Answer Convergence和CoDE-Stop。论文没有在14B上运行Think-or-Not，因此无需补一个原文没有的实验格子。Vanilla达到生成上限后也强制生成最终答案，不能用没有答案的截断输出作为偏弱对照。[论文实验设置](https://arxiv.org/html/2604.04930v2#S3.SS1)

| 对照 | 已知参数/实现状态 |
|---|---|
| DEER | CLI需要threshold、stop_word、ewt；0.95是代码示例，是否对应每个主表格子仍须核实 |
| EAT | timescale=10，warmup=25，threshold=1e−5，entropy_rollouts=1，entropy_decoding_steps=2；论文在20个AIME样本上选阈值 |
| Think-or-Not | 主表α=0.4；4B另做α=0.2的比较 |
| Answer Convergence | CLI为ansconv_consistency；还需核对内部判定规则和论文对应设置 |
| RCPD | 当前未发现同名CLI入口；不能把wheels未经核实当成RCPD |
| DEER+Fixed-Step40 | 论文图7的组合对照；仅存在fixed-rstep入口不等于已实现这个组合 |

来源：[论文附录D](https://arxiv.org/html/2604.04930v2#A4)、[方法注册表](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/inference.py#L224)。不能把缺失的基线配置填成自选值后声称完整对齐论文。

除主表外，全文覆盖还包括：

1. 表2：16K预算，重新校准并转移阈值。
2. 图6：4B的Vanilla、Budget-Force、Chain-of-Draft、No-Thinking及各自结合CoDE-Stop；不同提示需自己的基础轨迹。
3. 图7：DEER、DEER+Fixed-Step40、CoDE-Stop，比较错误轨迹的推理长度及准确率。
4. 图8：四种退化指标和四种历史权重的消融。
5. 图9：4B/AIME的τ敏感性曲线。
6. 表4/5/6：EAT阈值、Think-or-Not α、Wait/Alternatively分隔词对照。
7. 表8：逐基准调参和AMC转移参数的比较。
8. 附录G/H：高低退化轨迹的错误率、重复片段、答案切换、置信度曲线和检查步数分布。

这些扩展不必在第一轮同时运行，但不完成它们就应说明全文覆盖范围。

**6. 判分、记录及统计要求**

| 数据集 | 官方当前判分 |
|---|---|
| AIME | 本地math_verify |
| MATH500、GSM8K | LLM裁判，默认gpt-4o-mini，需要API可用性和独立费用预算 |
| GPQA-Diamond | 本地选项字母抽取 |

来源：[VALIDATION_REGISTRY](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/inference.py#L329)。更换为本地数学判分器可以另作评测，但须标明协议变化，并在一致样本上核对分歧；不能直接与官方API判分结果视为完全同口径。API密钥通过服务器环境配置，不进入聊天、日志或Git。

论文四项指标：Acc为所有轨迹的平均正确率；Tok为每轨迹平均推理token；CR为相对Vanilla的保留比例；Cost计入中间答案探测开销。CR=70%表示保留70%，即减少约30%。Overall按四个基准宏平均，不能直接把所有题混合算一个准确率，也不能用OverallTok的比值替代各基准CR的平均。

还必须单独记录以下实际执行信息：

- 模型、tokenizer、数据revision；代码提交和任何补丁；Python、CUDA、全部依赖；提示文本及生成配置。
- sample_id、rollout_id、种子、原始输出、抽取答案、裁判结果、停止位置及原因。
- 每次探测的答案、置信度、退化分数；非有限数、无答案、截断与异常标记。
- 原轨迹生成token、探测token、最终答案token及具体计数边界；纸面Tok和代码response_tokens的对应关系。
- 实际GPU时间、墙钟时间、峰值显存、API调用量和失败重试；结束时逐文件校验和、备份。
- 每个方法预期/实际/唯一记录数。MATH500每方法应有1000条唯一(sample, rollout)，不能把重复记录或缺依赖而跳过的题当成完成。

额外分析建议使用按题重采样的配对bootstrap区间；同题多次rollout不视为完全独立题目。该项是我们的可靠性补充，不是论文公布的原实验设置。

**7. 官方代码当前存在的开跑前问题**

以下是静态核查结果，不代表已在GPU上观察到这些问题的发生频率。

| 问题 | 影响 | 开跑前要求 |
|---|---|---|
| env_vars.py均为占位值 | 缓存目录和裁判不能直接使用 | 配置目录、环境变量和判分访问 |
| output-dir默认None仍传给makedirs | 不传路径可能立即报错 | 显式给每个实验版本独立输出路径 |
| AMC23和自动校准迁移脚本未接入 | 无法仅靠示例命令复现v2校准 | 补齐数据入口和校准记录 |
| 示例ramp_steps=1、Alternatively | 与v2主结果不同 | 使用已核对的主实验参数；不复制示例作最终配置 |
| 代码默认对置信度取log且只累积下降段 | 与v2原始概率公式不同 | 分开标记官方代码原样版、按论文公式实现版；不得静默替换 |
| 试探答案概率平均的极短输出边界 | 可能出现非有限置信度或与概率无关的1 | 用合成序列和真实短输出检查，记录处理政策 |
| 缓存只以部分参数和样本索引识别 | 种子/模型版本改变后可能误用旧轨迹 | 输出目录隔离，增加独立manifest校验 |
| 缺少依赖轨迹时只警告后跳过 | 程序结束不等于样本完整 | 对唯一键集合做完整性核对 |
| 汇总未去重且可能跳过坏JSON | 得分可能来自重复/缺失样本 | 核验后才汇总，不只看汇总脚本数字 |
| API验证先于生成结果落盘 | 裁判错误可能导致昂贵输出未保存 | 先检查裁判；可靠保存生成，再独立评测时保留同判分逻辑 |
| 只检查config.json就认为模型已下载 | 不完整权重可能被强制离线加载 | 验证全部权重分片和tokenizer文件 |

核查位置：[CoDE实现](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/method_codestop.py#L51)、[推理入口](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/inference.py)、[示例脚本](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/inference.sh)、[汇总](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/basic_results.py)、[缓存检测](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/models.py#L20)。

代码原样版和论文公式版之间的差异首先属于复现审计，不应直接包装为新的研究贡献。需要作者澄清时可准备问题清单，但尚未向作者发送任何消息。

**8. 正确执行顺序与第一阶段验收**

官方缓存依赖顺序为：`step-by-step` → `step-by-step-forceans` → `codestop` / `deer` / `eat`等。各阶段必须对应同模型、数据、预算及样本集合。官方inference.sh是SLURM示例，AutoDL无需安装SLURM；应使用Python入口按样本分块运行。[依赖注册表](https://github.com/sudoparsa/CoDE-Stop/blob/b5081e7c2abe23bb1d19649421cc13522fee7c50/inference.py#L339)

建议按以下关卡推进，不在前一关未通过时扩大租卡量：

1. 本地准备：固定版本、整理模型和数据manifest、补齐配置、静态验证公式和缓存；确认判分协议。
2. 少量GPU运行检查：固定样本覆盖短/中/长轨迹，检查答案、非有限数、计数边界、显存与耗时。小样本只用于估算资源和排错。
3. 运行AMC23校准或先做已公布参数重跑，清楚记录两者区别；未公开的网格不得冒称作者原网格。
4. Qwen3-4B / MATH500 / 32768 / 500题×2采样；共享轨迹比较Vanilla、DEER、CoDE-Stop。EAT随后补入。
5. 核验结果数量、判分分歧和异常；产出准确率—Cost图、成对改对/改错统计及原始记录。结果不吻合先定位，禁止在测试集上反复挑τ直至达到论文数字。
6. 第一阶段可信后再加AIME24/25，然后考虑第二模型及其他基准。AIME更难、轨迹更长，虽题数少却不一定便宜。

Qwen3-4B / MATH500在论文表1的参考值：

| 方法 | Acc% | Tok | CR% | Cost |
|---|---:|---:|---:|---:|
| Vanilla | 94.0 | 5210 | 100 | 5210 |
| DEER | 93.7 | 3803 | 73.0 | 3878 |
| CoDE-Stop | 93.5 | 3624 | 69.6 | 3696 |

来源：[论文表1](https://arxiv.org/html/2604.04930v2#A3.T1)。这些是对照参考，不是保证能逐点重现的验收硬指标；作者seed未充分公开且代码/公式存在差异，应报告实际偏差及原因。对该基准，论文显示的是准确率约下降0.5个百分点、Cost减少约29.1%的权衡，不是无损提升。

第一阶段交付应包含：版本及差异清单、环境锁定、可续跑执行入口、数据索引、参数文件、每方法1000条完整记录、校准记录（若实施）、资源测量、判分审计及结果报告。不能以几道题输出更短作为完成标准。

**9. 预算解释及真实速度边界**

按论文4B的平均长度推算，四个主基准的基础完整输出约32,385,654 tokens；MATH500一项约5,210,000 tokens。它们是从论文均值计算的规模估计，不是作者GPU小时，也不包含中间答案探测、校准、其他提示或失败重跑。

官方流程先生成完整轨迹，再重放前缀做提前停止评测。因此，报告的Cost用于估计该停止策略的token开销，不会把已经实际花费的原轨迹生成、重复prefill或CPU/GPU缓存搬运全部计入。**论文token节省比例不能直接当成实际GPU提速比例或租金节省比例。** 在线真正提前终止、测量时延是后续独立工程实验。

若仍沿用此前500–1000元预算，先用测得的每轨迹分阶段耗时估算批量费用，保留排错和确认性复测余量。目前不能承诺该预算完成全文复现。第二张GPU主要缩短墙钟时间，并不自动减少总计费GPU小时。

**10. 阅读与代码理解顺序**

1. 精读§3.1、表1的说明：先确定比较对象、采样次数、指标和成本口径。
2. 精读§2.2：手算一组置信度序列的阈值、退化分数和停止位置。
3. 精读附录D/F：区分固定参数与AMC校准迁移，注意平均检查步数。
4. 对照阅读method_codestop.py、inference.py、models.py、dataset_loader.py：理解论文—实现差异以及轨迹依赖。
5. 精读图7/8及相应消融：明白退化指标相比简单长度截断提供了什么。
6. 第一轮可略读Related Work、全部长案例；复现结果稳定后再精读附录G/H寻找有证据支持的后续问题。

当前最明确的下一步是完成开跑前的复现工程准备与差异核验，再用单张96GB卡做有时间上限的运行检查；本文件不表示GPU实验已经启动。
