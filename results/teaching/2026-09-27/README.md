# D2：普通生成与同种子重跑

2026-09-27，用户在单张 32GB vGPU（设备报告 RTX 4080 SUPER）上亲自执行两次普通生成。本目录保存经检查的教学实验记录，可用作小体积 GitHub 备份。

## 实际结果

题目为 `37 * 43 - 29 * 41`，标准答案 `402`。使用 Qwen3-4B BF16、seed 42、最大新增 2048 token；固定模型 revision 和受检查代码的哈希见每次运行的 `manifest.json`。

| 指标 | first | repeat |
| --- | ---: | ---: |
| 输入 token | 40 | 40 |
| 实际新生成 token | 2048 | 2048 |
| base 阶段耗时（秒） | 78.45025874697603 | 79.28048356098589 |
| 峰值 allocated 显存（字节） | 8454142976 | 8454142976 |
| 峰值 reserved 显存（字节） | 8646557696 | 8646557696 |
| 生成中包含 `</think>` | 否 | 否 |
| 末尾为配置的 EOS | 否 | 否 |
| 教学判分 | needs_review | needs_review |

两次生成的 token 序列和回答文本完全相同；均达到长度上限，在思考部分截断。推理中出现正确数值 402，但没有结束思考并给出规定格式的最终答案，因此 `correct` 保持 `null`。耗时包含诊断记录，不含模型加载时间；reserved 包含 allocated，二者不能相加。

这验证了该教学样例在当前环境和同一种子下的输出可重复。Vanilla 补答、DEER 和 CoDE 尚未运行；这些记录不是测试集准确率或在线早停加速证据。

## 文件入口

- [summary.json](summary.json)：配置、两次指标及比较结果。
- [response.txt](response.txt)：两次相同的回答文本，便于阅读。
- [first/base.json](first/base.json)、[repeat/base.json](repeat/base.json)：原始回答、完整 token ID、实际生成调用及指标。
- `first/`、`repeat/` 中还包含 `manifest.json`、`environment.json`、`grading.json`、`events.jsonl` 和 `console.log`。
- [export-manifest.json](export-manifest.json)：原文件和导出文件的 SHA-256，以及唯一的路径规范化说明。

`base.json`、`manifest.json`、判分文件、事件和终端日志均在检查后原样保留，记录哈希可继续验证。仅将两份 `environment.json` 中的模型缓存绝对路径改成仓库相对路径；原/导出文件哈希分别保留。未包含权重、虚拟环境、SSH 地址、登录凭据或个人本机路径。

## 只读检查归档

在仓库根目录执行，使用项目支持的 Python 环境；这些命令不加载模型或运行 GPU：

```bash
python scripts/single_question.py inspect --run-dir results/teaching/2026-09-27/first
python scripts/single_question.py inspect --run-dir results/teaching/2026-09-27/repeat
```

重新生成时请在 `runs/` 下使用新的目录，保留本归档。例如：

```bash
python scripts/single_question.py run --stage base --run-dir runs/d2-new-repeat
```

服务器原始 `runs/` 目录仍保留。这份归档满足本次小规模记录备份需求，后续批量轨迹、权重等大文件另行规划存储。
