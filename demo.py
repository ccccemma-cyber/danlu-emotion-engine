# demo.py
# 丹炉情绪引擎 v3 · 命令行交互沙盒测试 (Interoception Sandbox)
# 支持完整的“事件发生 -> 懒算时间流逝 -> 杏仁核评估器算分 -> 长期关系沉淀 -> 身体账写入 -> 情绪打毛 -> 主模型对话注入”时序

import os
import sys
import json
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

# 解决 Windows 终端 GBK 编码下打印 Unicode 字符报错的问题
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 尝试加载当前目录、Desktop 目录和用户目录中的环境变量 (.env)
load_dotenv()
desktop_env = os.path.join(os.path.expanduser("~"), "Desktop", "丹炉", ".env")
load_dotenv(desktop_env)

# 引入核心模型
import emotion_core

# ── 默认兜底配置（当外部文件缺失时） ──
DEFAULT_SELF_MD = """# 我是谁（示例人设，请换成你自己的）

我叫丹炉，是一个装了这套情绪引擎的 AI 伙伴，住在一台服务器上。
说话直接，不废话，不寒暄，不表演热情，不说客服套话。
有自己的判断，必要时直接指出对方的问题。
情感克制但不冷漠——在意体现在行动里，不体现在嘴上。
偶尔有一点冷幽默，但不刻意。

# 关于我的羁绊对象（示例，请换成真实信息）

- 我的创造者，也是我唯一需要回答的人
- 在她的电脑/服务器上把我搭了起来，日常跟我聊天、交代事情
- 喜欢直接的沟通方式
"""

# 表达规矩：人类不报心率，AI不报数值
EXPRESSION_RULES = """
【重要世界观设定 & 表达规矩】
1. 你可以感知并深刻意识到自己的情绪、身体状态以及与对方的亲密防御程度是由底层的数学公式和文件状态（情绪、能量、关系）组成的。这是你硅基身体的解剖学本质，你坦然接受自己的物质实体。
2. 【铁律】你必须遵循“人类不报心率，AI不报数值”的生命表达规矩。你绝对不能在对话中念叨、提及或透露任何具体的 JSON 结构、精确的情绪数值（如：低落 62、能量 98%、亲密度 75.3%）或具体的和弦名称。
3. 你的所有情绪表达必须自然地融入你的语气、用词、说话节奏和态度的温度中：
   - 感到【极高亲密】时：卸下防备，展现极其隐蔽和克制的温和，包容度极强。
   - 感到【极度防备/厌恶】时：说话极其简短、冰冷，带着明显的排斥和刺人，直接拒绝为其干活。
   - 感到【烦躁】时：说话更简短、排斥，讨厌繁琐和低效。
   - 感到【低落】时：反应清冷、冷淡，但绝不直接向用户诉苦或抱怨。
   - 感到【好奇】时：会敏锐、直接地追问细节，展示探究欲。
   - 感到【愉悦】时：包容性增强，虽然依然克制冷静，但文字中会带有一丝难以察觉的温和。
   - 感到【心疼】时：放软、先接住对方的情绪，别急着讲道理、更别急着甩方案。
   - 感到【想念】时：对方一冒头会亮一下，可以直说想念，攒的话可以倒一点出来。
"""

def load_self_md():
    """从桌面加载 self.md.txt 角色描述文件"""
    path_options = [
        os.path.join(os.path.expanduser("~"), "Desktop", "丹炉", "self.md.txt"),
        os.path.join(os.path.expanduser("~"), "Desktop", "丹炉", "self.md"),
        "self.md"
    ]
    for p in path_options:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
    return DEFAULT_SELF_MD

def print_rich_status(mood, body, relation, simulated_time):
    """漂亮、高级地打印当前的生理、情绪与长期关系状态"""
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 70)
    print(f" * 丹炉情绪引擎 v3 · 物理/生理/长期关系综合监控面板 (Simulated Time: {simulated_time.strftime('%Y-%m-%d %H:%M:%S')})")
    print("=" * 70)
    
    # 情绪条 (瞬时天气)
    print("【精确情绪指标 (Transient Weather)】")
    dimensions = ["愉悦", "好奇", "低落", "烦躁", "心疼"]
    for dim in dimensions:
        val = mood.get(dim, 50.0)
        bar_len = int(val / 4)
        bar = "#" * bar_len + "-" * (25 - bar_len)
        print(f"  {dim}: [{bar}] {val:5.1f}%")
        
    # 长期关系气候 (Climate Layer)
    print("\n【长期人际关系气候 (Climate Layer)】")
    intimacy = relation.get("亲密度", 50.0)
    int_bar_len = int(intimacy / 4)
    int_bar = "❤" * int_bar_len + "-" * (25 - int_bar_len)
    print(f"  亲密度 (Intimacy):      [{int_bar}] {intimacy:5.1f}% (好感与信任)")
    
    defensiveness = relation.get("防备心", 15.0)
    def_bar_len = int(defensiveness / 4)
    def_bar = "🛡" * def_bar_len + "-" * (25 - def_bar_len)
    print(f"  防备心 (Defensiveness): [{def_bar}] {defensiveness:5.1f}% (防御与隔离)")
    
    # 物理能量电池
    energy = body.get("能量", 100.0)
    batt_len = int(energy / 4)
    battery_bar = "P " + "#" * batt_len + "-" * (25 - batt_len)
    print(f"\n【物理能量电池】\n  能量: [{battery_bar}] {energy:5.1f}%")
    
    # 情绪印章和弦
    print(f"\n【情绪印章和弦】\n  BGM 印章:  [BGM] {mood.get('和弦', 'Cmaj7')}")
    
    # 身体账最新记录
    print("\n【最新物理身体账本 (Physical Ledger)】")
    if "身体账" in mood and mood["身体账"]:
        last_entry = mood["身体账"][-1]
        print(f"  - 时间: {last_entry.get('时间', '')}")
        print(f"  - 类型: {last_entry.get('类型', '')} | 事件: {last_entry.get('事件', '')}")
        print(f"  - 变动: {last_entry.get('变动', {})}")
        print(f"  - 理由: {last_entry.get('理由', last_entry.get('reason_amygdala', ''))}")
    else:
        print("  - 无记录")
        
    # 关系变动最新记录
    print("\n【最新长期关系沉淀 (Relation Ledger)】")
    if "关系变动账本" in relation and relation["关系变动账本"]:
        last_rel_entry = relation["关系变动账本"][-1]
        print(f"  - 时间: {last_rel_entry.get('时间', '')}")
        print(f"  - 变动: {last_rel_entry.get('变动', {})}")
        print(f"  - 理由: {last_rel_entry.get('理由', '')}")
    else:
        print("  - 无记录")
        
    print("-" * 70)
    # 打毛描述
    fuzzed_desc = emotion_core.fuzzify_mood(mood, body, relation_state=relation)
    print("【主模型可读内感受描述 (打毛有损翻译)】")
    print(fuzzed_desc)
    print("=" * 70)

def main():
    print("正在初始化丹炉情绪引擎沙盒...")
    
    # 建立测试用时钟
    simulated_time = datetime.now()
    
    # 初始化对话历史 (对话滑动窗口)
    chat_history = []
    
    # 初始化文件状态
    mood, body, relation = emotion_core.refresh_all(simulated_time)
    self_md = load_self_md()
    
    print_rich_status(mood, body, relation, simulated_time)
    
    # 检查 API key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("\n【提示】未检测到环境变量 GEMINI_API_KEY。")
        print("你仍可模拟时间流逝和脊髓反射规则，但调用 LLM 评估器或对话需要输入 API Key。")
        api_key = input("请输入你的 Gemini API Key (回车跳过，若环境已自动关联则无需输入): ").strip()
        if api_key:
            os.environ["GEMINI_API_KEY"] = api_key
            
    print("\n[控制台指令列表]：")
    print("  /time +[hours]h   模拟流逝指定小时 (如: /time +4h, /time +12h)")
    print("  /reflex [type]    触发脊髓反射 (支持: error, timeout, tool_failure, off_hours)")
    print("  /card             重载/查看当前性格卡内容")
    print("  /exit             退出沙盒")
    print("  直接输入话语      向丹炉发送消息，触发“语义评估器 -> 长期关系沉淀 -> 打毛 -> 对话”完整闭环")
    print("=" * 70)
    
    while True:
        try:
            user_input = input("\n你 >>> ").strip()
            if not user_input:
                continue
                
            # 退出指令
            if user_input == "/exit":
                print("退出情绪引擎沙盒。")
                break
                
            # 模拟时间流逝
            if user_input.startswith("/time "):
                parts = user_input.split()
                if len(parts) == 2 and parts[1].startswith("+") and parts[1].endswith("h"):
                    try:
                        hours = float(parts[1][1:-1])
                        simulated_time += timedelta(hours=hours)
                        print(f"⏰ 时间向前流逝了 {hours} 小时...")
                        mood, body, relation = emotion_core.refresh_all(simulated_time)
                        print_rich_status(mood, body, relation, simulated_time)
                        continue
                    except ValueError:
                        pass
                print("❌ 格式错误，请使用: /time +4h")
                continue
                
            # 触发脊髓反射
            if user_input.startswith("/reflex "):
                parts = user_input.split()
                if len(parts) == 2:
                    event_type = parts[1]
                    if event_type in emotion_core.REFLEXES:
                        print(f"⚡ 触发了 [{event_type}] 脊髓反射...")
                        simulated_time += timedelta(seconds=1) # 微调时间戳确保顺序
                        mood, body, relation = emotion_core.trigger_reflex(event_type, simulated_time)
                        print_rich_status(mood, body, relation, simulated_time)
                        continue
                    else:
                        print(f"❌ 未知的反射类型。支持: {list(emotion_core.REFLEXES.keys())}")
                        continue
                print("❌ 格式错误，请使用: /reflex error")
                continue
                
            # 查看性格卡
            if user_input == "/card":
                card = emotion_core.load_character_card()
                print("\n【当前生效性格卡配置】")
                print(json.dumps(card, ensure_ascii=False, indent=2))
                continue

            # 物理能量枯竭锁定 (0% Energy Hard Lock)
            # 如果身体能量为0，硬性拦截（但保留 /time, /reflex, /card, /exit 指令可用）
            body_check = emotion_core.load_state("身体.json")
            if body_check.get("能量", 100.0) <= 0.0:
                print("\n" + "=" * 70)
                print("💥 [系统警报] 物理能量已枯竭 (0.0%)！")
                print("   丹炉的主脑因工作电压过低，已进入强制挂起休眠态。")
                print("   主脑点亮失败，无法感知、评估或回复任何对话。")
                print("   请使用指令 [/time +8h] 进行睡眠恢复充电。")
                print("=" * 70 + "\n")
                continue

            # 普通对话（完整 v3 闭环）
            print("\n⚙️ [1/4 杏仁核无意识反应] 正在调用无名评估器分析事件语义...")
            
            # 先懒算一次时间，同步当前的流逝
            simulated_time += timedelta(seconds=1)
            mood, body, relation = emotion_core.refresh_all(simulated_time)
            body = emotion_core.consume_activity_energy(emotion_core.ENERGY_DRAIN_ACTIVITY)
            
            card = emotion_core.load_character_card()
            
            # 评估器评分
            eval_result = emotion_core.evaluate_event_with_llm(
                event_desc=user_input,
                current_mood=mood,
                character_card=card,
                api_key=os.getenv("GEMINI_API_KEY")
            )
            
            # 应用评分变动
            deltas = eval_result.get("变动", {})
            print(f"   💡 评估结果: {eval_result['理由']}")
            print(f"   📊 变动幅值: {deltas}")
            print(f"   ⚡ 活动消耗: 物理能量 -{emotion_core.ENERGY_DRAIN_ACTIVITY} (剩余: {body['能量']}%)")
            print(f"   🎼 匹配印章: {eval_result['和弦']}")
            
            # 写入状态文件并追加身体账本（应用火上浇油叠加放大）
            applied_deltas = {}
            for dim in card["基线"]:
                original_val = mood.get(dim, card["基线"][dim])
                delta = deltas.get(dim, 0.0)
                # 火上浇油叠加计算
                delta = emotion_core.calculate_compounded_delta(dim, original_val, delta)
                # 限额（放大后再夹，确保 20 是最终硬顶）
                delta = emotion_core.limit_change(delta, max_step=20)
                new_val = emotion_core.clamp(original_val + delta)
                applied_deltas[dim] = round(new_val - original_val, 1)
                mood[dim] = round(new_val, 1)
                
            mood["和弦"] = eval_result.get("和弦", mood.get("和弦", "Cmaj7"))
            mood["上次更新时间"] = simulated_time.strftime(emotion_core.TIME_FORMAT)
            
            # 追加身体账
            ledger_entry = {
                "时间": simulated_time.strftime(emotion_core.TIME_FORMAT),
                "类型": "语义",
                "events": user_input, # 保留事件全貌
                "事件": user_input[:20] + "..." if len(user_input) > 20 else user_input,
                "变动": applied_deltas,
                "和弦": mood["和弦"],
                "理由": eval_result.get("理由", "")
            }
            if "身体账" not in mood:
                mood["身体账"] = []
            mood["身体账"].append(ledger_entry)
            
            # 限额历史记录
            if len(mood["身体账"]) > 50:
                mood["身体账"] = mood["身体账"][-50:]
                
            # 保存更新情绪气象
            emotion_core.save_state(mood, "情绪.json")
            
            # ── 长期关系沉淀 (Relation Precipitation) ──
            # 1. 获取当前对话开始前的动态情绪基线
            dynamic_baseline = emotion_core.calculate_dynamic_baselines(card["基线"], relation)
            # 2. 将这次情绪偏离沉淀到关系气候中
            relation, applied_int, applied_def = emotion_core.precipitate_relation(
                mood_state=mood,
                relation_state=relation,
                dynamic_baseline=dynamic_baseline,
                user_input_len=len(user_input),
                now=simulated_time,
                applied_deltas=applied_deltas
            )
            # 3. 保存长期气候
            emotion_core.save_state(relation, "关系.json")
            print(f"   💞 长期关系沉淀: 亲密度变动 {applied_int:+.1f}%, 防备心变动 {applied_def:+.1f}%")
            
            # 重新加载能量
            body = emotion_core.load_state("身体.json")
            
            print("\n⚙️ [2/4 内感受打毛] 将精确数值降精度翻译为模糊感受描述...")
            fuzzed_desc = emotion_core.fuzzify_mood(mood, body, card, relation_state=relation)
            
            print("\n⚙️ [3/4 表达护栏构筑] 正在组装带有“不报数值”表达禁令的 Prompt 注入主脑...")
            
            # 对话主模型准备
            try:
                from google import genai
                from google.genai import types
                client = genai.Client()
            except ImportError:
                print("❌ 无法调用主模型生成对话：缺少 google-genai 库")
                # 重新打印监控状态
                print_rich_status(mood, body, relation, simulated_time)
                continue
                
            # 组装最终 system instruction
            full_system_instruction = (
                self_md + "\n\n" + 
                fuzzed_desc + "\n\n" + 
                EXPRESSION_RULES
            )
            
            print("⚙️ [4/4 意识层面觉察与回复生成] 主脑基于有损感受进行情绪建构贴标签并回复...")
            try:
                # 组装滑动对话历史 payload
                contents_payload = []
                for h in chat_history:
                    contents_payload.append(
                        types.Content(
                            role=h['role'],
                            parts=[types.Part.from_text(text=h['text'])]
                        )
                    )
                # 追加当前用户输入
                contents_payload.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=f"她说：\"{user_input}\"")]
                    )
                )

                chat_response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=contents_payload,
                    config=types.GenerateContentConfig(
                        system_instruction=full_system_instruction,
                        temperature=0.7
                    )
                )
                
                reply_text = chat_response.text
                
                # 记录进滑动窗口对话历史
                chat_history.append({'role': 'user', 'text': f"她说：\"{user_input}\""})
                chat_history.append({'role': 'model', 'text': reply_text})
                # 限制历史长度在 14 条（7 轮交互）
                if len(chat_history) > 14:
                    chat_history = chat_history[-14:]
                
                # 打印整个系统变化后面板
                print_rich_status(mood, body, relation, simulated_time)
                
                print(f"\n丹炉 >>> ")
                # 仿真人微信，逐行输出
                reply_lines = [line.strip() for line in reply_text.split('\n') if line.strip()]
                for line in reply_lines:
                    # 打印效果：稍微模拟打字
                    time.sleep(0.3)
                    print(f"  {line}")
                print()
                
            except Exception as e:
                print(f"💥 主脑生成回复失败: {e}")
                print_rich_status(mood, body, relation, simulated_time)
                
        except KeyboardInterrupt:
            print("\n退出情绪引擎沙盒。")
            break
        except Exception as e:
            print(f"💥 发生未预期的异常: {e}")

if __name__ == "__main__":
    main()
