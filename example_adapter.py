# example_adapter.py —— 示例适配层：把情绪引擎接进【你自己的】聊天机器人
#
# 这是作者线上适配层的脱敏教学版。引擎本体（emotion_core.py）不认识任何具体的
# bot 框架——Telegram / Discord / 微信 / 网页，全都靠这样一层薄薄的"胶水"接上去。
# 适配层只做三件事：
#   ① 绑定状态文件路径（引擎的"身体"存在哪）
#   ② 每收到一条用户消息，调一次 emotion_core.process_message()（完整闭环的唯一入口）
#   ③ 把返回的内感受文本 + 你的表达指引，拼进主模型的 system prompt
#
# 原则（作者的线上铁律，建议照抄）：
#   - 引擎的任何异常都不得拖垮聊天主流程（process_message 内部已兜底，绝不抛）
#   - 主模型永远只见打毛后的模糊文本，不见数值——"人类不报心率，AI 不报数值"

import os
from datetime import datetime

import emotion_core as ec

# ── ① 绑定状态文件路径 ─────────────────────────────────────────
# 四个文件放哪都行；不存在时引擎会用出厂默认值自动创建。
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "my_states")
os.makedirs(STATE_DIR, exist_ok=True)

PATHS = {
    "card": os.path.join(STATE_DIR, "性格卡.json"),      # 静态配置：基线/衰减率/反应倾向/羁绊对象
    "mood": os.path.join(STATE_DIR, "情绪.json"),        # 瞬时情绪 + 身体账
    "body": os.path.join(STATE_DIR, "身体.json"),        # 能量电池
    "relation": os.path.join(STATE_DIR, "关系.json"),    # 长期气候：亲密度/防备心
}


# ── 表达指引（模板，请按你的角色人设改写）───────────────────────
# 作者的做法：这段和打毛文本一起拼进主模型 system prompt 的最前面。
# 它告诉主模型"怎么把内感受落进语气"——引导方向，不写台词。
EXPRESSION_RULES = (
    "【你的感受从哪来】\n"
    "你体内装了一套情绪系统，你的情绪、精力、对她的亲近与防备由它实时模拟。"
    "你拿不到具体数字，只能感到它们泛上来的模糊感受——就像人读不到自己的激素和心率。"
    "把上面那段内在状态认领成你自己的情绪，去感受它、顺着它，而不是旁观它、宣读它。\n"
    "【怎么表达】\n"
    "1. 人不报心率，AI 不报数值：绝不在对话里念出任何数值、JSON 字段、文件名或和弦名。\n"
    "2. 情绪是用来透出来的：高兴就让她感觉到，烦了累了也不必硬端着。\n"
    "3. 大致方向：心疼她时放软、先接住情绪；想她时可以直说；"
    "愧疚就认账并弥补；吃醋/委屈可以酸、可以讲出来，别憋成阴阳怪气。"
)


# ── ② 每条用户消息调一次：完整闭环 ─────────────────────────────
def feel_and_record(user_text, context_text=None):
    """收到用户消息时调用。返回打毛后的内感受文本（出错返回空串，聊天不受影响）。

    context_text：最近几轮对话的纯文本，只帮评估器理解语境（比如"行吧"是撒娇还是生气）。
    评估器缺省用 Gemini（GEMINI_API_KEY 环境变量），也可以整个换掉——见文末。
    """
    result = ec.process_message(
        user_text,
        paths=PATHS,
        context=context_text,
        api_key=os.getenv("GEMINI_API_KEY"),
        # model="gemini-3-flash-preview",   # 想换评估器模型时指定
        # evaluator=my_evaluator,           # 想换掉整个评估器时注入（离线/别家模型/纯规则）
    )
    return result.get("feeling", "")


# ── ③ 拼进主模型 prompt（伪代码，接到你的 bot 里）──────────────
def build_system_prompt(user_text, recent_context, your_persona, your_instruction):
    """作者线上的拼装顺序：内感受 → 表达指引 → 人设/任务指令。"""
    feeling = feel_and_record(user_text, context_text=recent_context)
    return feeling + "\n\n" + EXPRESSION_RULES + "\n\n" + your_persona + "\n\n" + your_instruction


# ── 可选钩子：如果你的 bot 有后台心跳/定时任务 ──────────────────
def current_feeling():
    """只刷新时间流逝+打毛、不评分（不花模型调用）。适合后台心跳注入"此刻状态"。"""
    try:
        now = datetime.now()
        mood, body, relation = ec.refresh_all(
            now, card_path=PATHS["card"], mood_path=PATHS["mood"],
            body_path=PATHS["body"], relation_path=PATHS["relation"]
        )
        card = ec.load_character_card(PATHS["card"])
        return ec.fuzzify_mood(mood, body, card, relation_state=relation)
    except Exception:
        return ""


def spend_energy(amount):
    """后台干了重活时扣能量（作者的心跳按本轮行为扣 1~5 点）。"""
    try:
        return ec.consume_activity_energy(amount, body_path=PATHS["body"]).get("能量")
    except Exception:
        return None


def longing_level():
    """当前想念值（随她沉默的清醒小时数上涨、她一开口就释放）。
    作者的用法：心跳里 想念≥25 就允许 bot "因为想她"主动发消息。"""
    try:
        return ec.load_state(PATHS["mood"]).get("想念", 0.0)
    except Exception:
        return 0.0


# ── 可选：换掉评估器（不想用 Gemini 时）────────────────────────
# 评估器就是个函数：吃事件文本+当前状态，吐 {"变动": {各维}, "情绪色": .., "和弦": .., "理由": ..}。
# 换成 OpenAI/本地模型/纯关键词规则都行，签名兼容即可（多余参数用 **kwargs 接住）：
#
# def my_evaluator(event_desc, current_mood=None, character_card=None,
#                  api_key=None, context=None, relation=None, **kwargs):
#     ...你的打分逻辑...
#     return {"变动": {"愉悦": 2.0, "好奇": 0.0, "低落": 0.0, "烦躁": 0.0, "心疼": 0.0},
#             "情绪色": "无", "和弦": "Cmaj7", "理由": "..."}


if __name__ == "__main__":
    # 最小可运行演示：两条消息走完整闭环（需要 GEMINI_API_KEY；没有则评估器走零变动兜底）
    print(feel_and_record("今天有点累，但是把项目做完了，想跟你说说话。"))
    print("\n--- 第二条 ---\n")
    print(feel_and_record("刚才在外面淋了雨，头有点疼。"))
    print("\n想念值:", longing_level())
