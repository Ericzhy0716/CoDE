**CoDE — CoDE-Stop复现与后续研究**

这是CoDE-Stop的独立复现与后续研究项目，创建于2026-09-20，由[Ericzhy0716/CoDE](https://github.com/Ericzhy0716/CoDE)维护。后续相关代码、配置、实验记录和分析统一放在这里。它与此前研究独立；旧研究资料保留为历史记录。

**目录用途**

```text
codestop-reproduction/
├── README.md                  项目入口与当前状态
├── UPSTREAM.json              官方代码来源、固定版本与校验记录
├── docs/                      复现要求、查重、实验协议和研究记录
├── upstream/CoDE-Stop/         固定版本的官方代码（Git子模块）
├── src/                       我们实现或修改的项目代码
├── configs/                   模型、数据、方法和运行参数
├── scripts/                   准备、执行、评测及汇总入口
├── data/                      本地数据与缓存，不默认提交Git
├── runs/                      原始输出、日志和运行记录，不默认提交Git
└── results/                   整理后的指标、图表和实验报告
```

**现有资料**

- [预算汇总：租GPU与调用API](docs/BUDGET_SUMMARY_20260921.md)：统一实验范围、逐基准检查步数、校准/判分/存储预留；明确哪些是公开价格、哪些是未实测的预算情景。
- [复现实验要求](docs/CODESTOP_REPRODUCTION_REQUIREMENTS_20260920.md)：模型、数据、依赖、参数、判分、代码差异及验收要求。
- [创新可行性与相关工作审查](docs/CODESTOP_NOVELTY_ASSESSMENT_20260920.md)：相邻工作、创新边界、阅读顺序及有限投入的去留流程。
- [费用估算与 Mac/API 可行性](docs/COST_AND_API_FEASIBILITY_20260921.md)：单卡预算假设、API 必备能力、重复输入费用和后续验证安排；尚无测速或付费 API 实验。
- [API 现价与分阶段预算](docs/API_TOKEN_BUDGET_20260921.md)：公开端点价格、FP8限制、双模型条件预算与可复算的离线工具。
- [API 与低价 GPU 的费用比较](docs/API_VS_GPU_COST_20260921.md)：原模型显存估算、公开租价、同任务费用及租卡盈亏平衡时间；实际吞吐仍待测试。
- [官方代码](https://github.com/sudoparsa/CoDE-Stop/tree/b5081e7c2abe23bb1d19649421cc13522fee7c50)：来源为`sudoparsa/CoDE-Stop`，固定提交`b5081e7c2abe23bb1d19649421cc13522fee7c50`，以Git子模块关联。该副本用于对照原始实现；我们的修改放在独立代码/补丁中，并注明与上游差异。原作者代码保留其MIT许可与版权声明。

**当前状态**

已建立独立目录，收纳复现要求、创新可行性、费用与API方案说明和官方代码参考副本。尚未在此目录启动GPU实验，也没有将官方代码/论文差异处理完毕；`src/`等目录目前仅预留结构。当前研究优先级以创新可行性审查为准：先对齐实现与参数、明确有限诊断协议，再决定是否扩大复现。

每次正式实验需保存代码版本、配置、模型和数据版本、样本划分、随机种子、判分方式及完整性核验；论文报告的token成本与实测运行时间分别记录。官方代码原样运行、论文公式对齐版本和新方法实验需分开标记。

**获取项目**

```bash
git clone --recurse-submodules https://github.com/Ericzhy0716/CoDE.git
```

已经克隆但未获取官方代码时，在仓库根目录运行：

```bash
git submodule update --init --recursive
```

上述命令只获取代码；不会安装依赖、下载模型或启动实验。上游环境文件仍为原始示例，需要按复现要求单独配置。

**后续同步**

本项目的同步目标为[Ericzhy0716/CoDE](https://github.com/Ericzhy0716/CoDE)，默认分支为`main`。后续经核验的相关代码、配置、文档和整理后的结果持续提交到此仓库。`.gitignore`排除本地数据、原始运行输出、权重、环境与密钥文件；官方代码只记录固定子模块版本，不混入旧项目实验。
