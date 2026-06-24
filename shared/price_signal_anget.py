"""shared.price_signal_anget — 价格指标分解智能体（多轮对话）。

调用 Claude Agent SDK（ClaudeSDKClient），把用户输入的价格指标（如 ma(10)、
kdj(9,3,3)）分解成「过去各期价格的权重」（权重和 = 1），并生成 Price Signature
Plot 保存到 results/。多个指标画在同一张图上、用颜色区分。

支持多轮对话：同一会话里连续输入多个指标，智能体记住上下文。

用法:
    from shared.price_signal_anget import generate_signal, chat

    # 单次：分解 ma(10) 和 ema(20)，画在同一张图
    generate_signal("ma(10), ema(20)")

    # 多轮交互式（input 循环）
    chat()
"""

import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import (
    ClaudeAgentOptions, ClaudeSDKClient,
    AssistantMessage, TextBlock, ResultMessage,
)

# Windows 控制台默认 GBK，助手回复含 emoji/特殊字符会 UnicodeEncodeError → 重配 utf-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent

str_system_prompt = """你是一个价格指标分解员。用户会输入一个或多个价格指标（如 ma(10)、ema(20)、kdj(9,3,3)），
你要把每个指标分解成「过去各期价格的加权和」，并把权重画成 Price Signature Plot。

规则：
1. 每个指标 = Σ 权重_i × price_i，其中 price_i 是过去第 i 期的收盘价
   （price_0 = 最近一期，price_1 = 上一期，i 越大越久远）。
2. **每个指标的权重之和必须等于 1**（归一化）。
3. 按指标的真实数学定义给权重：
   - ma(n)：过去 n 期等权，每期 1/n。
   - ema(n)：指数衰减权重，w_i = (1-α)·α^i 归一化，α = 2/(n+1)。
   - wma(n)：线性衰减权重。
   - kdj/macd 等含多分量的，分别给每个分量的权重序列。
4. 输出：用 plotly 把权重画成折线图（横轴 = 过去第 i 期，纵轴 = 权重），
   **如果用户给了多个指标，画在同一张图上，用不同颜色区分，并加图例标注哪个是哪个**。
   保存为 HTML 到项目 results/ 目录，文件名反映指标（如 signal_ma10_ema20.html）。
5. 先在回复里简述每个指标的权重公式和归一化后的前几个权重值，再写文件。
"""


def _options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=str_system_prompt,
        cwd=str(PROJECT_ROOT),
        allowed_tools=["Read", "Write", "Bash", "Glob"],
        permission_mode="acceptEdits",  # 自动批准文件编辑，避免审批卡住自动化流程
    )


def _extract_text(messages) -> str:
    """从消息流里提取助手文本回复，拼接返回。"""
    parts = []
    for msg in messages:
        if isinstance(msg, AssistantMessage):
            for block in getattr(msg, "content", []):
                if isinstance(block, TextBlock):
                    parts.append(block.text)
    return "\n".join(parts)


async def _chat_async(user_inputs):
    """多轮对话：按顺序发送 user_inputs（list[str]），返回每轮的文本回复 list。"""
    replies = []
    async with ClaudeSDKClient(options=_options()) as client:
        for prompt in user_inputs:
            print(f"\n[你] {prompt}")
            await client.query(prompt)
            msgs = [m async for m in client.receive_response()]
            text = _extract_text(msgs)
            replies.append(text)
            # 打印助手回复（截断过长内容）
            preview = text[:500] + ("..." if len(text) > 500 else "")
            print(f"[助手] {preview}")
            # 成本
            for m in msgs:
                if isinstance(m, ResultMessage) and getattr(m, "total_cost_usd", 0) > 0:
                    print(f"[成本] ${m.total_cost_usd:.4f}")
    return replies


def generate_signal(indicators):
    """分解价格指标并生成 Price Signature Plot（单次调用，可含多个指标）。

    Args:
        indicators: 指标字符串，单个或多个，如 "ma(10)" 或 "ma(10), ema(20), kdj(9,3,3)"。
    """
    return asyncio.run(_chat_async([indicators]))[0]


def chat():
    """多轮交互式对话：循环读取用户输入，每轮分解指标并画图。输入 q/quit 退出。"""

    def _input_loop():
        msgs = []
        while True:
            s = input("\n输入价格指标（如 ma(10)），多个用逗号分隔，q 退出: ").strip()
            if s.lower() in ("q", "quit", "exit"):
                break
            if not s:
                continue
            msgs.append(s)
        return msgs

    user_inputs = _input_loop()
    if user_inputs:
        asyncio.run(_chat_async(user_inputs))


if __name__ == "__main__":
    chat()
