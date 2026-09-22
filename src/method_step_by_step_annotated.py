# 中文学习副本：逐行对应 upstream/CoDE-Stop/method_prompts.py 第7–18行。
# 来源：sudoparsa/CoDE-Stop，提交 b5081e7c2abe23bb1d19649421cc13522fee7c50。
# 原代码的许可见 ../upstream/CoDE-Stop/LICENSE；函数逻辑保持不变。
# 本文件供对照阅读，不作为实验入口；generate依赖原项目的models模块及其运行环境。

from typing import Any  # Any用于类型标注，表示字典的值可以是不同类型。
from models import generate  # 导入原项目models.py中的生成包装函数，下面第13行会调用它。


# 原第7行：定义函数。model是已加载的模型；tokenizer是分词器；sample是一道题的字典；B是新增token上限。
# sample: dict[str, Any]表示预期键为字符串；B: int表示预期为整数；箭头后的类型表示预期返回字典。
# 这些是类型标注，不会自动把传入数据转换为对应类型。
def method_step_by_step(model, tokenizer, sample: dict[str, Any], B: int) -> dict[str, Any]:
    # 原第8行：函数的说明文字（docstring），表示“提示模型逐步思考”；它不会自动发送给模型。
    """Prompt the model to think step-by-step."""
    # 原第9行：取出题目文字，拼接两个换行和作答要求；要求分步推理，并把最终答案写进LaTeX的框中。
    # 字符串里的\n表示换行；源码中的两个反斜杠表示字符串中的一个反斜杠，得到\boxed{}。
    content = sample['question'] + "\n\nPlease reason step by step, and put your final answer within \\boxed{}."
    # 原第10行：创建消息列表；role='user'表示用户发言，content保存刚拼好的文字。此时还未转换成token编号。
    messages = [{"role": "user", "content": content}]
    # 原第11行：把模型名称/路径转成小写，检查是否包含nemotron；当前Qwen模型不进入这个分支。
    if 'nemotron' in model.name_or_path.lower():
        # 原第12行：对Nemotron，在用户消息前添加一条系统消息，要求详细思考；列表相加保持系统消息在前。
        # 这里f字符串没有插入变量，效果与普通字符串相同。
        messages = [{"role": "system", "content": f"detailed thinking on"}] + messages
    # 原第13行：开始调用导入的generate包装函数，将其返回的回答字符串赋给response。
    response = generate(
        # 原第14行：按参数名称传入模型、分词器和消息；等号左边是参数名，右边是本函数里的变量。
        model=model, tokenizer=tokenizer, messages=messages,
        # 原第15行：传入新增token上限B，启用采样；包装函数会把这些选项继续交给底层model.generate。
        B=B, do_sample=True
    # 原第16行：结束这次多行函数调用；调用完成后，response中保存返回的文字。
    )
    # 原第17行：把回答文字重新编码成token编号，再用len统计长度；不是字符数，也不一定等于原始生成ID数。
    response_tokens = len(tokenizer.encode(response))
    # 原第18行：返回字典给调用者，包含回答、输入消息、回答token计数和work计数；这一步没有写文件或判分。
    # 本方法把work设为response_tokens；其他带额外探测的方法不能据此认为二者相等。
    return {"response": response, "messages": messages, 'response_tokens': response_tokens, 'work': response_tokens}
