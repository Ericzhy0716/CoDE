# D1：从一道题到回答的源码导读

日期：2026-09-22。依据用户今天的安排：Mac上学习与准备，核心6小时；9月21日用户学习投入为0。既有代码准备不算用户完成学习。本文是导读与练习，不是完成记录，不改变其他对话维护的Notion任务状态。

源码核验版本：`upstream/CoDE-Stop`，提交 `b5081e7c2abe23bb1d19649421cc13522fee7c50`。以下行号对应此版本。今天先理解原作者的普通生成流程，再认识我们自己的单题入口。

## 1. 怎样使用这份导读

每次只读一小段：先看源码，再用自己的话解释输入、处理、输出，最后核对本导读。不能解释的地方记录具体行号；不用先背熟所有库。本文配合今天的任务使用，不增加新的必做阶段。

| 顺序 | 文件与位置 | 精略程度 | 读完要回答 |
| --- | --- | --- | --- |
| 1 | [method_prompts.py](../upstream/CoDE-Stop/method_prompts.py)，7–18行 | 精读 | 怎样把一道题包装成模型请求？返回哪些字段？ |
| 2 | [models.py](../upstream/CoDE-Stop/models.py)，112–141行 | 精读 | 请求怎样变成数字、生成新token、再转回文字？ |
| 3 | [inference.py](../upstream/CoDE-Stop/inference.py)，224、341、444、536、588–634行 | 定位后精读关键几行 | 方法怎样被选择？结果怎样判分和保存？ |
| 4 | [单题执行指南](SINGLE_QUESTION_RUNBOOK.md)，第2节；[配置](../configs/single_question.json) | 略读 | 我们自己的教学入口与原始入口有什么区别？ |

DEER/CoDE内部公式、KV cache和其他基线暂留D4/D5。聊天或Notion把文件名自动变成`http://models.py`等链接时，请在VS Code中打开本地文件，不要把它当作网站。

## 2. 先核对本地位置

在VS Code打开已有的`codestop-reproduction`目录，在该目录的集成终端逐条运行：

```bash
pwd
git --version
python3 --version
git submodule status upstream/CoDE-Stop
```

| 命令 | 意思 | 检查什么 |
| --- | --- | --- |
| `pwd` | 显示当前目录 | 末尾应为`codestop-reproduction` |
| `git --version` | 显示Git版本 | 有版本号，而非找不到命令 |
| `python3 --version` | 显示当前终端的Python版本 | 抄下实际版本；它不是服务器环境已经配好 |
| `git submodule status ...` | 显示固定上游仓库版本 | 哈希应为上面的`b5081e...`；前面若有`+`或`-`，先反馈 |

这些操作不安装依赖，也不运行模型。Mac上的Python版本与后续GPU环境可以不同，不需要因为今天的阅读而重装Python。终端输出由你自己记录；助手的终端环境不一定与你的VS Code终端一致。

## 3. 第一段：method_step_by_step()负责什么

打开`method_prompts.py`第7行。先认识四个参数：

| 参数 | 这里的含义 |
| --- | --- |
| `model` | 已经加载的语言模型对象；不是模型名称字符串 |
| `tokenizer` | 与模型配套的分词器，可处理聊天模板、文字与token ID之间的转换 |
| `sample` | 一道题的数据字典；本函数读取`sample['question']` |
| `B` | 传给普通生成函数的新增token数量上限 |

`sample: dict[str, Any]`和`B: int`是类型标注，帮助说明预期输入；它们不会自动把任意传入值转换成相应类型。`-> dict[str, Any]`说明预期返回一个字典。

按顺序读这五件事：

1. **第9行：拼接文字。** 题目后加两个换行，再加“分步推理、最终答案放进`\boxed{}`”的提示。`+`是字符串拼接。Python源码里的`\\`在字符串中表示一个反斜杠。
2. **第10行：包装消息。** `messages`是列表；其中的字典用`role`标记说话者，用`content`存文字。此时仍不是token ID。
3. **第11–12行：特定模型的额外处理。** 模型名包含`nemotron`才加一条系统消息；本次Qwen路径先跳过这一分支。
4. **第13–16行：调用项目的generate函数。** 文件第4行从`models.py`导入它。`do_sample=True`经参数继续传入底层生成，意味着使用采样；可复现执行还需要记录随机种子和采样设置。
5. **第17–18行：统计并返回字典。** `response`是生成的回答字符串；重新编码它得到`response_tokens`，再把回答、消息和计数一起返回。这里没有写文件，也没有核对标准答案。

这里的`work`被赋成与`response_tokens`相同的数值。不要推广成“所有方法的work都等于回答长度”；带探测的方法还有额外计算。

计数细节：`len(tokenizer.encode(response))`是对解码后文字重新分词得到的长度，并非直接数原始生成ID。特殊token、解码清理与重新编码可能让二者不同。今天先认清来源，后续实验再核对统计口径。

**停下来口述：** 题目来自哪里？为什么需要`messages`？这段函数有没有直接调用判分器或保存文件？能说明后再读下一段。

## 4. 第二段：models.py里的generate()

两个名字相似的函数要分清：

- `generate(...)`：本项目写的包装函数，负责聊天模板、分词、设备和回答截取。
- `model.generate(...)`：模型对象提供的生成方法，执行真正的模型推理。

| 行号 | 代码中的动作 | 用普通话理解 |
| --- | --- | --- |
| 120 | `next(model.parameters()).device` | 查看模型参数所在的设备，后面把输入放过去 |
| 121 | `apply_chat_template(..., tokenize=False, add_generation_prompt=True)` | 给消息加上模型所需的角色/轮次格式和回答起始标记，得到文本`prompt` |
| 122 | `tokenizer(prompt, return_tensors='pt', padding=True)` | 把文本变成模型可处理的张量，通常包括`input_ids`和`attention_mask` |
| 123 | 对每个输入执行`.to(device)` | 让输入与模型在对应设备上 |
| 125–130 | 组装`gen_kwargs` | 指定新增token上限、结束/填充token等生成选项，并传入`do_sample`等额外参数 |
| 132–133 | `torch.no_grad()`内执行`model.generate(...)` | 推理时不记录梯度；这里不是训练，也不更新模型权重 |
| 135–141 | 按选项截取并解码 | 默认只返回新生成部分；指定`return_full_text=True`时连输入一起解码 |

需要理解的Python语法：`**kwargs`在函数定义处收集额外的关键字参数；`model.generate(**inputs, **gen_kwargs)`把两个字典展开成命名参数。普通生成的`do_sample=True`就是这样传下去的。

### 五种数据不要混淆

```text
sample['question']      一道题的文字（str）
        ↓ 加提示要求
messages                有角色与内容的消息列表（list[dict]）
        ↓ apply_chat_template，tokenize=False
prompt                  符合模型聊天格式的完整文本（str）
        ↓ tokenizer(..., return_tensors='pt')
inputs['input_ids']      token编号组成的张量（Tensor）
        ↓ model.generate(...)
outputs                 在本次decoder-only普通生成路径下：输入ID + 新生成ID
        ↓ 切掉输入部分，再decode
response                模型新增回答的文字（str）
```

`input_ids`不是向量嵌入本身，而是整数编号；嵌入查表等操作在模型内部。token也不固定等于一个字或一个英文单词。

### 为什么切掉input_length

以下是纯手工示意，数字不是Qwen的真实token ID，也没有运行模型：

```python
input_ids = [[10, 20, 30]]
outputs = [[10, 20, 30, 81, 82]]
input_length = 3
new_ids = outputs[0][input_length:]  # [81, 82]
```

源码的`inputs['input_ids'].shape[1]`取序列长度。单题时张量形状可理解为`[1, 输入token数]`；`outputs[0]`取第一条输出，后面的切片保留模型新生成部分。否则解码结果会把用户问题等输入一起带回来。

### B是上限，不是必须生成的长度

普通生成路径把`B`赋给`max_new_tokens`。模型若较早生成结束标记，可以在用满B前结束。若输入有200个token、B为1000，允许最多再生成1000个token；输入加生成的总长度还需符合模型及实际运行的上下文限制。

原始入口的B由命令行必填参数`-B`或`--max-new-tokens`传入，没有在这个包装函数里固定为32K。我们当前教学配置设为2048；它不是论文完整协议的32768，也不是整个多方法实验的总计算预算。

## 5. 第三段：inference.py怎样调度、判分和保存

不用通读文件，按这条线找：

```text
命令行参数 --method 和 -B                 437、444行
        ↓
METHOD_REGISTRY映射名字到函数              224行
B = args.max_new_tokens                   536行
method_fn = METHOD_REGISTRY[args.method]    538行
        ↓
读取一道sample，再遍历其rollout             588–592行
        ↓
method_output = method_fn(...)            616或618行
        ↓
validation = validate_fn(response, answer) 620行
        ↓
result = {...}                            621–632行
        ↓
f.write(json.dumps(result) + '\n')         633行
f.flush()                                 634行
```

`rollout`是同一道题的一次生成尝试；多次生成不是新增独立题目。`JSONL`是一行一个JSON对象，本入口每行记录某题某次rollout的方法输出、判分、参数及题目信息。

`flush()`把Python写缓冲交给底层文件系统，不等于做了独立备份，也不保证突然断电时数据一定已写入物理磁盘。

注意先后顺序：原作者在判分之后才写这条结果。若判分发生未处理异常，该题已经生成的回答可能还没进入JSONL。`method_step_by_step()`本身只返回对象；“返回成功”和“文件保存成功”是两件事。

判分器由331行的`VALIDATION_REGISTRY`选择；本版本MATH500使用`validate_answer_llm`。读源码不需要API密钥，之后正式运行要单独准备并核验判分协议。

### 依赖是分支，不是一条四方法串行链

```text
step-by-step
     ↓
step-by-step-forceans
     ├──→ deer
     └──→ codestop
```

在341行查看依赖表。这里描述的是固定上游的执行安排：DEER/CoDE读取已有基础记录、检查推理前缀。不要把它说成所有提前停止实现都必须先生成完整回答。

574–586行只加载前置结果；依赖表不会自动替你运行前置方法。整份依赖缓存不存在会报错，单条题目/rollout的缓存缺失则在612–614行跳过。

`forceans`也不代表每题都重新回答。数学题的原回答重新编码长度小于`B-50`时，86–101行直接沿用；接近预算时才截去末尾部分，预留空间后补答案。50是预留下限，不是固定新生成50个token，也不是答案正确性检查。

## 6. 与我们自己的单题入口对照

今天只需要读配置与看计划。在仓库根目录运行：

```bash
python3 scripts/single_question.py plan
```

源码已确认这个分支只检查配置与固定上游来源、显示阶段；不加载模型、不下载权重、不连接服务器。检查输出中的题目、模型名、`max_new_tokens`、`stages`以及`no_model_loaded_or_downloaded: true`。

| 路径 | 生成与保存的关系 |
| --- | --- |
| 原作者`inference.py` | 方法生成 → 判分 → 追加一行JSONL |
| 我们的`src/diagnostic_core.py` | `execute_stage()`第212行起生成并保存阶段JSON；主流程第413行随后独立做教学判分 |

我们自己的入口用手写教学题和2048上限；它的教学判分不能替代论文MATH500评测。今天的`plan`输出也不能计作一条真实模型结果。后续运行步骤见已有单题指南，本日不执行`prepare`或`run`。

## 7. 留给你填写的记录

把以下内容填进你的学习笔记或今日Notion任务页。可以直接把尚未完成的草稿发给助手，不需要先整理成正式报告。

```text
本地Git/Python/上游版本：
我理解的调用链（给每个箭头加一句解释）：
messages / input_ids / response各是什么：
B的来源、作用与总上下文的区别：
切掉input_length的原因：
原作者在哪里判分、在哪里保存：
依赖分支与基础缓存的关系：
测试题不能反复挑参数的原因：
最不理解的三个点（文件名、行号、具体问题）：
实际主动学习用时：
```

部署清单逐项填写，未知项写“待确认”：GPU型号和显存、磁盘容量、服务器Python/驱动/依赖版本、模型与revision、原始输出位置、备份位置、判分服务、本轮费用上限、停止时间。Python环境用于隔离运行时与依赖；依赖是代码需要的库；Git子模块用于固定另一份源码版本。这三件事不等于模型权重已经下载。

数据用途笔记分别写：教学样例用于理解流程；开发样本用于排错和方法选择；校准样本用于拟合阈值等设置；最终测试在方案固定后用于评估。按题识别重复，不能把同一道题的不同rollout分到开发和测试两侧。记录来源、题目ID及规范化文本/内容核对方式，并在使用前检查与AMC23/MATH500的重叠；字符串不同也可能是同一道题的改写。

验收以你能解释并定位代码、提供准备清单为准。阅读时间用满、助手写完导读、脚本打印计划，都不自动意味着D1通过。
