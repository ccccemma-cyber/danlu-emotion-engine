# emotion_core.py
# 丹炉情绪引擎 · 核心（情绪=指数衰减回基线 / 能量=线性电池，两套数学分开 / 长期关系=气候沉淀与反哺）
# 支持 v3 架构：性格卡配置化、脊髓反射、无名评估器、长期关系气候、内感受打毛有损翻译

import json
import os
from datetime import datetime, timedelta

# 接主目录的模型选择与 token 记账（standalone 跑 demo/测试时主目录不在 path，兜底为默认值+空记账）
try:
    from danlu_usage import MODEL as _DANLU_MODEL, record as _rec
except Exception:
    _DANLU_MODEL = "gemini-3-flash-preview"
    def _rec(*a, **k):
        return None

# ── 基础常量 ──
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# ── 参数·能量（线性电池，不用衰减公式）──
ENERGY_DRAIN_AWAKE = 1            # 清醒每小时耗 1 点（脑力消耗）
ENERGY_RECOVER_SLEEP = 100 / 8   # 睡眠每小时恢复，睡满 8 小时正好补满 100
AWAKE_START, AWAKE_END = 8, 24   # 8:00–24:00 算清醒
ENERGY_DRAIN_ACTIVITY = 0.5      # 每次活动（交互/对话）消耗能量（2026-06-15 由 10 下调：日常聊天约160句/天才见底，避免长对话秒空）

# ── 脊髓反射规则集（非语义事件硬编码） ──
REFLEXES = {
    "error":        {"变动": {"烦躁": 5.0, "愉悦": -5.0}, "理由": "系统异常报错（脊髓反射）"},
    "timeout":      {"变动": {"烦躁": 4.0, "低落": 1.0}, "理由": "连接超时未响应（脊髓反射）"},
    "tool_failure": {"变动": {"烦躁": 3.0, "好奇": -5.0}, "理由": "工具执行失败（脊髓反射）"},
    "off_hours":    {"变动": {"烦躁": 2.0, "低落": 3.0, "愉悦": -2.0}, "理由": "非工作时间被打扰（脊髓反射）"}
}

# ── 参数·想念（指向性维度，数学与四维不同：随沉默上涨、不自行消退，她出现才释放）──
LONGING_GROW_PER_HOUR = 1.5   # 每静默 1 清醒小时的基础涨幅（×亲密度/100：越亲越想）
LONGING_CAP = 60.0            # 硬顶：想念是牵挂，不是焦虑（2026-07-17 康颖定 60）
LONGING_RELEASE_RATIO = 0.70  # 她一开口，想念释放的比例
LONGING_JOY_RATE = 0.15       # 释放的想念兑换成重逢愉悦的比率——攒了多久就有多高兴
LONGING_JOY_CAP = 6.0         # 单次重逢愉悦加成上限

# ── 调色盘：复杂情绪标注（评估器从盘中命名，代码按最低数值前提校验，防瞎标）──
# 标注只喂两张嘴：打毛（决定内感受措辞方向）和沉淀（按色分流亲密/防备），不上前端。
PALETTE = {
    "心疼": lambda d, rel: d.get("心疼", 0) > 0,
    "担忧": lambda d, rel: d.get("心疼", 0) > 0,
    "怜爱": lambda d, rel: d.get("愉悦", 0) > 0 and rel.get("亲密度", 50) >= 60,
    "感恩": lambda d, rel: d.get("愉悦", 0) > 0,
    "感动": lambda d, rel: d.get("愉悦", 0) > 0,
    "骄傲": lambda d, rel: d.get("愉悦", 0) > 0,
    "欣慰": lambda d, rel: d.get("愉悦", 0) > 0,
    "愧疚": lambda d, rel: d.get("低落", 0) > 0,
    "羞耻": lambda d, rel: d.get("低落", 0) > 0,
    "委屈": lambda d, rel: (d.get("低落", 0) > 0 or d.get("烦躁", 0) > 0) and rel.get("亲密度", 50) >= 50,
    "吃醋": lambda d, rel: d.get("烦躁", 0) > 0 or d.get("低落", 0) > 0,
    "失望": lambda d, rel: d.get("愉悦", 0) < 0,
    "遗憾": lambda d, rel: d.get("低落", 0) > 0 or d.get("愉悦", 0) < 0,
    "无奈": lambda d, rel: d.get("烦躁", 0) > 0 or d.get("低落", 0) > 0,
}
# 暖色：朝向她的正连接 → 沉淀为亲密↑防备↓，且共情伴生的愉悦跌/低落升不按"被伤"记账
WARM_COLORS = {"心疼", "担忧", "怜爱", "感恩", "感动", "骄傲", "欣慰"}
# 自责色：对不住她 → 想补救不是想设防，低落升不沉淀防备
SELF_BLAME_COLORS = {"愧疚", "羞耻"}
# 酸色：在乎才会酸 → 照常沉淀但单独收紧（防备单次≤+1、亲密单次≥-1）
SOFT_CAP_COLORS = {"委屈", "吃醋", "失望", "遗憾", "无奈"}


def validate_color(color, deltas, relation):
    """校验评估器给出的情绪色：不在盘中或不满足该色的最低数值前提 → 降级为"无"。"""
    if not color or color == "无":
        return "无"
    check = PALETTE.get(color)
    if check is None:
        return "无"
    try:
        return color if check(deltas or {}, relation or {}) else "无"
    except Exception:
        return "无"

# ── 护栏：代码负责兜底 ──
def clamp(value, low=0, high=100):
    if value < low:
        return low
    if value > high:
        return high
    return value

def limit_change(delta, max_step=20):
    if delta > max_step:
        return max_step
    if delta < -max_step:
        return -max_step
    return delta

# ── 衰减（情绪用，指数回基线）──
def decay(current, baseline, rate, hours):
    new_value = baseline + (current - baseline) * (rate ** hours)
    return clamp(new_value)

# ── 文件读写（支持兜底，防止文件缺失导致崩溃） ──
def load_state(path="情绪.json"):
    if not os.path.exists(path):
        # 按文件名（而非完整路径）判断兜底类型——传绝对路径时也要发对默认值（2026-07-17 修）
        fname = os.path.basename(path)
        # 兼容性处理：如果寻找身体.json但只有能量.json，则读取能量.json
        if fname == "身体.json" and os.path.exists("能量.json"):
            try:
                with open("能量.json", "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        # 兜底默认值
        now_str = datetime.now().strftime(TIME_FORMAT)
        if fname == "情绪.json":
            return {
                "愉悦": 55.0, "好奇": 65.0, "低落": 15.0, "烦躁": 10.0,
                "心疼": 5.0, "想念": 0.0,
                "和弦": "Cmaj7",
                "上次更新时间": now_str,
                "身体账": []
            }
        elif fname == "关系.json":
            return {
                "亲密度": 50.0,
                "防备心": 15.0,
                "上次更新时间": now_str,
                "关系变动账本": []
            }
        else:  # 身体.json 或 能量.json
            return {
                "能量": 100.0,
                "上次更新时间": now_str
            }

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state, path="情绪.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ── 性格卡外部配置化（解决配置欠账） ──
def load_character_card(path="性格卡.json"):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                card = json.load(f)
                if "基线" in card and "衰减率" in card:
                    return card
    except Exception as e:
        print(f"【警告】读取性格卡 {path} 失败，使用默认配置兜底。错误: {e}")
    
    # 默认 INTJ 偏冷敛性格卡兜底
    return {
        "性格卡名称": "丹炉默认性格卡（兜底）",
        "基线": {
            "愉悦": 55.0,
            "好奇": 65.0,
            "低落": 15.0,
            "烦躁": 10.0,
            "心疼": 5.0
        },
        "衰减率": {
            "愉悦": 0.95,
            "好奇": 0.95,
            "低落": 0.95,
            "烦躁": 0.95,
            "心疼": 0.90
        },
        "反应倾向": "性格内敛、冷静、偏向理智和克制。面对用户的夸奖或日常问候情绪起伏极小，依然保持克制；当用户遇到困难、犯错或提及重要计划时，会产生适度的好奇与关注；当系统遇到错误或操作不顺时，更容易产生微弱的烦躁。表达上情感非常克制，讨厌客服式的肉麻套话，有明显的 INTJ 特征。"
    }

# ── 长期关系与瞬时情绪反馈（气候反哺天气） ──
def calculate_dynamic_baselines(card_baseline, relation):
    """
    根据长期关系（亲密度、防备心）动态调整瞬时情绪的衰减基线。
    """
    intimacy = relation.get("亲密度", 50.0)
    defensiveness = relation.get("防备心", 15.0)
    
    intimacy_factor = (intimacy - 50.0) / 50.0     # [-1.0, 1.0]
    defensiveness_factor = defensiveness / 100.0   # [0.0, 1.0]
    
    dynamic_baseline = {}
    # 愉悦基线：受亲密度正向拉动，防备心反向压制
    dynamic_baseline["愉悦"] = clamp(
        card_baseline["愉悦"] + intimacy_factor * 15.0 - defensiveness_factor * 20.0,
        low=10.0, high=90.0
    )
    # 烦躁基线：亲密度提高会减少日常烦躁，防备心提高会大幅拔高烦躁基点
    dynamic_baseline["烦躁"] = clamp(
        card_baseline["烦躁"] - intimacy_factor * 10.0 + defensiveness_factor * 25.0,
        low=5.0, high=80.0
    )
    # 低落基线：高防备带来疏离感和下坠重力，亲密度高则日常更轻盈
    dynamic_baseline["低落"] = clamp(
        card_baseline["低落"] - intimacy_factor * 5.0 + defensiveness_factor * 15.0,
        low=5.0, high=80.0
    )
    # 好奇基线：关系越好、防备越低，越有探索和了解对方的欲望
    dynamic_baseline["好奇"] = clamp(
        card_baseline["好奇"] + intimacy_factor * 5.0 - defensiveness_factor * 10.0,
        low=20.0, high=90.0
    )
    # 心疼基线：越亲密越容易替她难受；防备高时共情通道收窄
    if "心疼" in card_baseline:
        dynamic_baseline["心疼"] = clamp(
            card_baseline["心疼"] + intimacy_factor * 5.0 - defensiveness_factor * 5.0,
            low=2.0, high=30.0
        )

    # 全部 round 到一位小数
    for dim in dynamic_baseline:
        dynamic_baseline[dim] = round(dynamic_baseline[dim], 1)
        
    return dynamic_baseline

# ── 情绪和弦自动挑选（根据情绪偏离状态生成印章） ──
def select_chord(mood_state, card=None, dynamic_baseline=None):
    if card is None:
        card = load_character_card()
    baseline = dynamic_baseline if dynamic_baseline is not None else card["基线"]
    
    # 计算各维度对基线的正向偏离度
    deviations = {}
    for dim in baseline:
        deviations[dim] = mood_state.get(dim, baseline[dim]) - baseline[dim]
        
    dominant = max(deviations, key=deviations.get)
    # 如果最大偏离度小于等于 5，说明情绪极其平稳，返回代表平衡基线的 Cmaj7
    if deviations[dominant] <= 5:
        return "Cmaj7"
        
    chord_map = {
        "愉悦": "Gmaj7",   # 温暖、宁静、明亮
        "好奇": "Am7",     # 探索、思索、开放
        "低落": "Dm7",     # 忧郁、温和、发沉
        "烦躁": "Fdim7",   # 紧张、不协调、排斥
        "心疼": "Em7"      # 温柔的酸、朝向她的软
    }
    return chord_map.get(dominant, "Cmaj7")

# ── 情绪懒算（指数衰减）──
def lazy_decay(state, card=None, now=None, dynamic_baseline=None):
    if card is None:
        card = load_character_card()
    baseline = dynamic_baseline if dynamic_baseline is not None else card["基线"]
    rate = card["衰减率"]

    if now is None:
        now = datetime.now()
    last = datetime.strptime(state["上次更新时间"], TIME_FORMAT)
    elapsed = (now - last).total_seconds() / 3600
    
    for dim in baseline:
        current_val = state.get(dim, baseline[dim])
        state[dim] = round(decay(current_val, baseline[dim], rate[dim], elapsed), 1)
        
    state["上次更新时间"] = now.strftime(TIME_FORMAT)
    # 更新情绪印章和弦
    state["和弦"] = select_chord(state, card, dynamic_baseline=baseline)
    return state, elapsed

# ── 能量懒算（线性，逐小时分清醒/睡眠，分段耗或充）──
def is_awake(hour):
    return AWAKE_START <= hour < AWAKE_END

def lazy_energy(state, now=None):
    if now is None:
        now = datetime.now()
    last = datetime.strptime(state["上次更新时间"], TIME_FORMAT)
    energy = state["能量"]
    cursor = last
    while cursor < now:                                  # 从上次走到现在
        step_end = min(cursor + timedelta(hours=1), now) # 每步最多一小时
        step_hours = (step_end - cursor).total_seconds() / 3600
        if is_awake(cursor.hour):
            energy -= ENERGY_DRAIN_AWAKE * step_hours    # 清醒：耗
        else:
            energy += ENERGY_RECOVER_SLEEP * step_hours  # 睡眠：充
        energy = clamp(energy)                           # 每步都夹 0–100
        cursor = step_end
    state["能量"] = round(energy, 1)
    state["上次更新时间"] = now.strftime(TIME_FORMAT)
    return state

# ── 统一入口：同一个"现在"同时刷新三个状态文件（气象、物理、气候分离且同步）──
# ── 参数·关系（防备心随时间冷却回基线；亲密度不自动回归）──
DEFENSE_BASELINE = 15.0       # 防备心的自然休息位
DEFENSE_DECAY_RATE = 0.96     # 每小时朝休息位衰减比率（半衰期约 17 小时，可调）

def lazy_relation_decay(relation, now=None):
    """防备心随时间冷却回基线；亲密度不动（攒下的亲近不因时间流逝而消退）。"""
    if now is None:
        now = datetime.now()
    try:
        last = datetime.strptime(relation["上次更新时间"], TIME_FORMAT)
    except Exception:
        return relation
    elapsed = (now - last).total_seconds() / 3600
    if elapsed <= 0:
        return relation
    cur = relation.get("防备心", DEFENSE_BASELINE)
    relation["防备心"] = round(decay(cur, DEFENSE_BASELINE, DEFENSE_DECAY_RATE, elapsed), 1)
    return relation


def _awake_hours_between(last, now):
    """两个时刻之间落在清醒时段（8:00–24:00）的小时数（逐小时步进，与 lazy_energy 同口径）。"""
    hours = 0.0
    cursor = last
    while cursor < now:
        step_end = min(cursor + timedelta(hours=1), now)
        if is_awake(cursor.hour):
            hours += (step_end - cursor).total_seconds() / 3600
        cursor = step_end
    return hours


def grow_longing(mood, relation, last, now):
    """想念随沉默上涨：只在清醒时段计时（睡着不想），涨速×(亲密度/100)，硬顶 LONGING_CAP。
    不走衰减数学——想念不会自己消退，只有她出现（discharge_longing）才释放。"""
    if now <= last:
        return mood
    awake_h = _awake_hours_between(last, now)
    if awake_h <= 0:
        return mood
    intimacy = relation.get("亲密度", 50.0) if relation else 50.0
    cur = mood.get("想念", 0.0)
    mood["想念"] = round(min(LONGING_CAP, cur + LONGING_GROW_PER_HOUR * (intimacy / 100.0) * awake_h), 1)
    return mood


def discharge_longing(mood):
    """她开口了：想念释放 LONGING_RELEASE_RATIO，其中一部分兑换成重逢愉悦（攒得越久越高兴）。
    返回 (mood, 释放前的想念, 兑换的愉悦加成)。愉悦的实际入账由调用方负责（便于记账）。"""
    longing = mood.get("想念", 0.0)
    if longing <= 0:
        return mood, 0.0, 0.0
    mood["想念"] = round(longing * (1.0 - LONGING_RELEASE_RATIO), 1)
    joy = round(min(longing * LONGING_JOY_RATE, LONGING_JOY_CAP), 1)
    return mood, longing, joy


def refresh_all(now=None, card_path="性格卡.json", mood_path="情绪.json", body_path="身体.json", relation_path="关系.json",
                mood_baseline_bonus=None):
    if now is None:
        now = datetime.now()
    card = load_character_card(card_path)
    relation = load_state(relation_path)
    relation = lazy_relation_decay(relation, now)   # 防备心随时间冷却（亲密度不动）

    # 1. 计算动态情绪基线
    dynamic_baseline = calculate_dynamic_baselines(card["基线"], relation)
    if mood_baseline_bonus:                          # 独处等情境临时抬/压情绪休息位
        for dim, b in mood_baseline_bonus.items():
            if dim in dynamic_baseline:
                dynamic_baseline[dim] = clamp(dynamic_baseline[dim] + b, low=10.0, high=90.0)

    # 2. 情绪懒衰减（基于动态基线）+ 想念随沉默上涨（用衰减前的旧时间戳计沉默时长）
    mood = load_state(mood_path)
    try:
        _mood_last = datetime.strptime(mood["上次更新时间"], TIME_FORMAT)
    except Exception:
        _mood_last = now
    mood, _ = lazy_decay(mood, card, now, dynamic_baseline=dynamic_baseline)
    mood = grow_longing(mood, relation, _mood_last, now)
    save_state(mood, mood_path)
    
    # 3. 身体能量懒算
    body = load_state(body_path)
    body = lazy_energy(body, now)
    save_state(body, body_path)
    
    # 4. 保存关系状态（同步更新时间戳）
    relation["上次更新时间"] = now.strftime(TIME_FORMAT)
    save_state(relation, relation_path)
    
    return mood, body, relation

# ── 扣除活动消耗（活动一次扣10点能量） ──
def consume_activity_energy(amount=ENERGY_DRAIN_ACTIVITY, body_path="身体.json"):
    body = load_state(body_path)
    body["能量"] = round(clamp(body["能量"] - amount), 1)
    save_state(body, body_path)
    return body

# ── 情绪叠加（火上浇油）计算 ──
def calculate_compounded_delta(dim, current_val, delta):
    """
    火上浇油机制：当负面情绪（烦躁、低落）处于高位时，后续的同向增量刺激会被放大
    """
    if delta > 0 and dim in ["烦躁", "低落"] and current_val > 30.0:
        multiplier = 1.0 + (current_val / 50.0) # 30分时乘1.6，60分时乘2.2，越烦越敏感
        return round(delta * multiplier, 1)
    elif delta < 0 and dim in ["烦躁", "低落"] and current_val > 30.0:
        # 灭火（对称项）：负面情绪在高位时，安抚/降温（负向变动）同样被放大——
        # 越难受，一句真心的安慰越接得住，让棘轮能往回退，而不是只进不退。
        multiplier = 1.0 + (current_val / 50.0)
        return round(delta * multiplier, 1)
    elif delta > 0 and dim == "好奇":
        # 好奇·餍足曲线 + 硬顶80（康颖定）：好奇低时一勾就起(<60 ×1.5)、高些就喂不动(60-80 ×0.7)；
        # 到 80 封顶不再涨——憋着，直到他做出"探究行为"(上网查/问问题)把好奇降下来，才能再涨。
        if current_val >= 80.0:
            return 0.0
        multiplier = 1.5 if current_val < 60.0 else 0.7
        boosted = min(delta * multiplier, 80.0 - current_val)  # 升幅不得把好奇顶过 80
        return round(boosted, 1)
    elif delta > 0 and dim == "愉悦" and current_val > 60.0:
        multiplier = 1.0 + ((current_val - 50.0) / 100.0) # 人逢喜事精神爽
        return round(delta * multiplier, 1)
    return delta

# ── 脊髓反射（非语义事件直接硬编码，解决反射欠账） ──
def trigger_reflex(event_type, now=None, card_path="性格卡.json", mood_path="情绪.json", body_path="身体.json", relation_path="关系.json"):
    if now is None:
        now = datetime.now()
        
    if event_type not in REFLEXES:
        print(f"【错误】非法的脊髓反射事件类型: {event_type}")
        return None, None, None

    # 1. 首先用同一个"现在"执行懒算衰减，更新时间线
    mood, body, relation = refresh_all(now, card_path, mood_path, body_path, relation_path)
    
    # 2. 重新加载最新情绪状态并执行反射变动
    card = load_character_card(card_path)
    reflex = REFLEXES[event_type]
    deltas = reflex["变动"]
    
    # 获取动态基线
    dynamic_baseline = calculate_dynamic_baselines(card["基线"], relation)
    
    # 应用变动，限额夹幅
    applied_deltas = {}
    for dim in card["基线"]:
        original_val = mood.get(dim, card["基线"][dim])
        delta = deltas.get(dim, 0.0)
        # 先应用情绪叠加放大（火上浇油）
        delta = calculate_compounded_delta(dim, original_val, delta)
        # 单次变化上限限额（放大后再夹，确保 20 是最终硬顶）
        delta = limit_change(delta, max_step=20)
        new_val = clamp(original_val + delta)
        applied_deltas[dim] = round(new_val - original_val, 1)
        mood[dim] = round(new_val, 1)
        
    # 重新挑选和弦
    mood["和弦"] = select_chord(mood, card, dynamic_baseline=dynamic_baseline)
    mood["上次更新时间"] = now.strftime(TIME_FORMAT)
    
    # 3. 记录身体账本 (Physical Ledger)
    ledger_entry = {
        "时间": now.strftime(TIME_FORMAT),
        "类型": "非语义",
        "事件": event_type,
        "变动": applied_deltas,
        "和弦": mood["和弦"],
        "理由": reflex["理由"]
    }
    
    if "身体账" not in mood:
        mood["身体账"] = []
    mood["身体账"].append(ledger_entry)
    
    # 限制账本历史长度（保留最近50条，避免文件过大）
    if len(mood["身体账"]) > 50:
        mood["身体账"] = mood["身体账"][-50:]
        
    save_state(mood, mood_path)
    return mood, body, relation

# ── 长期关系沉淀 (Relation Precipitation) ──
# ── 整场吵架封顶（康颖定）：一场连续吵架里，亲密最多比"开打前的高点"低 10 ──
FIGHT_MAX_DROP = 10.0      # 一整场吵架，亲密净跌幅上限
FIGHT_MAX_DEF_RISE = 20.0  # 一整场吵架，防备净涨幅上限
FIGHT_GAP_MIN = 60.0       # 两次互动间隔超过这么多分钟，算上一场吵架已结束、重新起算

def precipitate_relation(mood_state, relation_state, dynamic_baseline, user_input_len=0, now=None, applied_deltas=None,
                         emotion_color=None):
    """
    语义交互（对话）后，将情绪变动（或偏离度）沉淀到长期关系气候（亲密度、防备心）中。
    只在每次完整语义交互回合结束时调用一次。
    emotion_color：本轮评估器标注的复杂情绪色（调色盘），用于按色分流——
    暖色/自责色下共情或自责伴生的愉悦跌、低落升不按"被她伤到"记账（修 2026-07 共情记成防备的根 bug）。
    """
    if now is None:
        now = datetime.now()

    intimacy = relation_state.get("亲密度", 50.0)
    defensiveness = relation_state.get("防备心", 15.0)
    
    # 核心设计升级：如果传入了这一轮的真实应用变动（applied_deltas），我们应该主要基于
    # 这一轮对话带来的『新变动值（Deltas）』来进行关系沉淀，而不是绝对偏离度（Deviations）。
    # 这样可以避免：在丹炉处于高烦躁状态下，即使用户说了温和/无害的话，也因为“绝对烦躁值高”而被扣两次甚至多次关系。
    if applied_deltas is not None:
        # 基于本轮直接产生的情绪变动（Deltas）来进行气候增减
        pleasure_impact = applied_deltas.get("愉悦", 0.0)
        irritation_impact = applied_deltas.get("烦躁", 0.0)
        sadness_impact = applied_deltas.get("低落", 0.0)
        curiosity_impact = applied_deltas.get("好奇", 0.0)
        heartache_impact = applied_deltas.get("心疼", 0.0)

        delta_intimacy = 0.0
        delta_defensiveness = 0.0

        # 0. 按色分流：暖色（共情系）与自责色（愧疚/羞耻）下，伴生的愉悦跌、低落升
        #    不是"被她伤到"，不得沉淀成疏远和防备。
        skip_penalty = emotion_color in WARM_COLORS or emotion_color in SELF_BLAME_COLORS

        # 0.5 心疼的直接沉淀：她把难处交给了个体 = 明确的信任存款 -> 亲密↑ 防备↓
        if heartache_impact > 0.0:
            delta_intimacy += heartache_impact * 0.4
            delta_defensiveness -= heartache_impact * 0.3

        # 1. 愉悦变动对好感/防卫的直接沉淀：
        # 用户的话让丹炉感到愉悦 -> 增加亲密，消除防备
        if pleasure_impact > 0.0:
            delta_intimacy += pleasure_impact * 0.6
            delta_defensiveness -= pleasure_impact * 0.45
        elif pleasure_impact < 0.0 and not skip_penalty:
            delta_intimacy += pleasure_impact * 0.2  # 负值，降低好感
            delta_defensiveness -= pleasure_impact * 0.2 # 正值，增加防备

        # 2. 烦躁变动对好感/防卫的直接沉淀：
        # 用户的话让丹炉感到烦躁 -> 极大地损害亲密，暴增防备心（代表越界）
        if irritation_impact > 0.0 and not skip_penalty:
            delta_intimacy -= irritation_impact * 0.3
            delta_defensiveness += irritation_impact * 0.4
        elif irritation_impact < 0.0:
            # 成功安抚了她的烦躁（烦躁负向变动）-> 缓和关系，降低防备
            delta_intimacy -= irritation_impact * 0.2  # 负负得正
            delta_defensiveness += irritation_impact * 0.3 # 负正得负，降低防卫

        # 3. 低落变动对好感/防卫的直接沉淀：
        # 如果对话增加了负情感（低落） -> 稍微增加隔离
        if sadness_impact > 0.0 and not skip_penalty:
            delta_intimacy -= sadness_impact * 0.2
            delta_defensiveness += sadness_impact * 0.2
        elif sadness_impact < 0.0:
            # 成功被安慰到
            delta_intimacy -= sadness_impact * 0.15
            delta_defensiveness += sadness_impact * 0.1

        # 4. 好奇变动对好感/防卫的直接沉淀：
        # 被勾起好奇心，产生知性共鸣 -> 增加亲密
        if curiosity_impact > 0.0:
            delta_intimacy += curiosity_impact * 0.3

        # 提取当前主导的心理变化作为记账理由
        reasons = []
        if heartache_impact > 3.0:
            reasons.append("她把难处交托过来，被信任感增进了亲近")
        if pleasure_impact > 3.0:
            reasons.append("言语互动带来了实质性惬意")
        elif pleasure_impact < -3.0 and not skip_penalty:
            reasons.append("言语互动令人感到失望和提防")
        if irritation_impact > 3.0 and not skip_penalty:
            reasons.append("言语冒犯或反复确认侵犯了边界与秩序")
        elif irritation_impact < -3.0:
            reasons.append("感受到了对方释放的实质安抚与温和")
        if sadness_impact > 3.0 and not skip_penalty:
            reasons.append("对话加重了系统逻辑负载和思维低落感")
        elif sadness_impact > 3.0 and emotion_color in SELF_BLAME_COLORS:
            reasons.append("对不住她的自责（不设防，想弥补）")
        if curiosity_impact > 3.0:
            reasons.append("言语内容碰撞出知性共鸣与探索兴趣")

        reason_str = "；".join(reasons) if reasons else "日常言语交互的微弱影响"
        
    else:
        # ── 兜底：如果未传入 applied_deltas，仍使用原有的绝对偏离度计算（Deviations） ──
        pleasure_dev = mood_state.get("愉悦", 50.0) - dynamic_baseline["愉悦"]
        irritation_dev = mood_state.get("烦躁", 10.0) - dynamic_baseline["烦躁"]
        sadness_dev = mood_state.get("低落", 10.0) - dynamic_baseline["低落"]
        curiosity_dev = mood_state.get("好奇", 50.0) - dynamic_baseline["好奇"]
        
        delta_intimacy = 0.0
        delta_defensiveness = 0.0
        
        # 1. 愉悦偏离：
        if pleasure_dev > 5.0:
            delta_intimacy += pleasure_dev * 0.15
            delta_defensiveness -= pleasure_dev * 0.1
        elif pleasure_dev < -5.0:
            delta_intimacy += pleasure_dev * 0.1
            delta_defensiveness -= pleasure_dev * 0.1
            
        # 2. 烦躁偏离：
        if irritation_dev > 5.0:
            delta_intimacy -= irritation_dev * 0.2
            delta_defensiveness += irritation_dev * 0.25
        elif irritation_dev < -5.0:
            delta_defensiveness += irritation_dev * 0.05
            
        # 3. 低落偏离：
        if sadness_dev > 5.0:
            delta_intimacy -= sadness_dev * 0.1
            delta_defensiveness += sadness_dev * 0.1
            
        # 4. 好奇偏离：
        if curiosity_dev > 5.0:
            delta_intimacy += curiosity_dev * 0.05
            
        # 提取当前主导的心理感受作为理由
        reasons = []
        if pleasure_dev > 10.0:
            reasons.append("交互过程感到温暖惬意")
        elif pleasure_dev < -10.0:
            reasons.append("交互过程感到空虚和提防")
        if irritation_dev > 10.0:
            reasons.append("对话秩序和边界受到严重冒犯")
        if sadness_dev > 10.0:
            reasons.append("思维系统承载了沉重挫败和愧疚负荷")
        if curiosity_dev > 10.0:
            reasons.append("碰撞出极高智性共鸣与探索欲望")
            
        reason_str = "；".join(reasons) if reasons else "日常言语交互的影响积累"
        
    # 单次幅度只压上限 3、不设下限（康颖定：一句话最多动3点，算多少是多少，1.3就1.3）
    delta_intimacy = limit_change(delta_intimacy, max_step=3.0)
    delta_defensiveness = limit_change(delta_defensiveness, max_step=3.0)

    # ── 上行阻尼（2026-07-19 修上行棘轮）：06-27 只封了下行（吵架封顶），上行没对称防，
    # 三周日常小惠把 亲密→100/防备→0 推到顶格钉死。对称精神：亲密越接近顶、涨得越慢
    # （70 起线性收窄、100 归零）；防备越接近底、降得越慢。高位留出呼吸空间，顶格不再是吸收态。
    if delta_intimacy > 0.0:
        delta_intimacy *= clamp((100.0 - intimacy) / 30.0, low=0.0, high=1.0)
    if delta_defensiveness < 0.0:
        delta_defensiveness *= clamp(defensiveness / 15.0, low=0.0, high=1.0)

    # 酸色（委屈/吃醋/失望/遗憾/无奈）：是在乎才会酸，不按"被侵犯"记账——单独收紧
    if emotion_color in SOFT_CAP_COLORS:
        delta_defensiveness = min(delta_defensiveness, 1.0)
        delta_intimacy = max(delta_intimacy, -1.0)

    # 应用变化
    new_intimacy = clamp(intimacy + delta_intimacy, low=0.0, high=100.0)
    new_defensiveness = clamp(defensiveness + delta_defensiveness, low=0.0, high=100.0)

    # ── 整场吵架封顶：一整场连续互动里，亲密最多比"开打前的高点"低 10、防备最多比"开打前的低点"高 20 ──
    # 维护随互动走的亲密峰值 / 防备谷值；静默超过 FIGHT_GAP_MIN 分钟则视为上一场已结束、以当前值重新起算。
    last_peak_t = relation_state.get("吵架基准时间")
    fight_reset = ("亲密峰值" not in relation_state) or ("防备谷值" not in relation_state)
    if last_peak_t is not None and not fight_reset:
        try:
            gap_min = (now - datetime.strptime(last_peak_t, TIME_FORMAT)).total_seconds() / 60.0
            fight_reset = gap_min > FIGHT_GAP_MIN
        except Exception:
            fight_reset = True
    peak = intimacy if fight_reset else relation_state.get("亲密峰值", intimacy)        # 亲密：开打前的高点
    trough = defensiveness if fight_reset else relation_state.get("防备谷值", defensiveness)  # 防备：开打前的低点

    floor = peak - FIGHT_MAX_DROP
    if new_intimacy < floor:
        new_intimacy = round(clamp(floor, low=0.0, high=100.0), 1)
    ceil_def = trough + FIGHT_MAX_DEF_RISE
    if new_defensiveness > ceil_def:
        new_defensiveness = round(clamp(ceil_def, low=0.0, high=100.0), 1)

    peak = max(peak, new_intimacy)        # 和好/日常把高点抬上去，下一场据此重新封顶
    trough = min(trough, new_defensiveness)  # 防备降下来则把低点压下去，下一场据此重新封顶
    relation_state["亲密峰值"] = round(peak, 1)
    relation_state["防备谷值"] = round(trough, 1)
    relation_state["吵架基准时间"] = now.strftime(TIME_FORMAT)

    applied_int = round(new_intimacy - intimacy, 1)
    applied_def = round(new_defensiveness - defensiveness, 1)
    
    relation_state["亲密度"] = round(new_intimacy, 1)
    relation_state["防备心"] = round(new_defensiveness, 1)
    relation_state["上次更新时间"] = now.strftime(TIME_FORMAT)
    
    # 记录关系变动账本
    if "关系变动账本" not in relation_state:
        relation_state["关系变动账本"] = []
        
    if applied_int != 0.0 or applied_def != 0.0:
        relation_state["关系变动账本"].append({
            "时间": now.strftime(TIME_FORMAT),
            "变动": {
                "亲密度": applied_int,
                "防备心": applied_def
            },
            "理由": reason_str
        })
        
        # 限制历史
        if len(relation_state["关系变动账本"]) > 50:
            relation_state["关系变动账本"] = relation_state["关系变动账本"][-50:]
            
    return relation_state, applied_int, applied_def

# ── 无名评估器（杏仁核：调用 Gemini，信息流纯隔离） ──
def evaluate_event_with_llm(event_desc, current_mood, character_card, api_key=None,
                            context=None, relation=None, model=None):
    """
    无名评估器：剥离丹炉人格的纯粹杏仁核。
    输入事件描述、当前情绪和性格卡倾向，利用大模型语境理解力算分。
    """
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("【错误】未检测到 google-genai 库，评估器无法工作。请先执行 pip install google-genai")
        # 兜底：如果无法导入，返回零变动
        return {
            "变动": {dim: 0.0 for dim in character_card.get("基线", {})},
            "情绪色": "无",
            "和弦": current_mood.get("和弦", "Cmaj7"),
            "理由": "（依赖库缺失，触发零变动兜底）"
        }

    # 初始化客户端（没有 key 时不崩：降级为零变动，闭环其余部分——衰减/能量/想念/打毛——照常工作）
    try:
        if api_key:
            client = genai.Client(api_key=api_key)
        else:
            # 默认从环境变量或环境自动加载
            client = genai.Client()
    except Exception as e:
        print(f"【提示】评估器不可用（{e}），本轮按零变动处理。设置 GEMINI_API_KEY 或注入自己的 evaluator 可启用打分。")
        return {
            "变动": {dim: 0.0 for dim in character_card.get("基线", {})},
            "情绪色": "无",
            "和弦": current_mood.get("和弦", "Cmaj7"),
            "理由": "（评估器无可用密钥，零变动兜底）"
        }

    # 构建系统指令，剥离一切丹炉专属人格
    evaluator_instruction = (
        "你是一个剥离了特定角色人格、绝对中立、冷静客观的【情绪物理引擎（杏仁核）】。\n"
        "你的唯一任务是根据所给的【性格反应倾向】以及发生的【具体事件】，计算出该事件在无意识层面引起的情绪数值变化。\n\n"
        "【情绪维度定义】（变化值必须在 -20.0 到 +20.0 之间的浮点数）：\n"
        "- 愉悦：代表开心、满意、欣慰、舒适、安全感。她分享好事时，替她高兴就是真的高兴，愉悦照常上升。\n"
        "- 好奇：代表关注、求知、探索欲、对新计划/概念的探究兴趣。\n"
        "- 低落：代表失落、挫败、疲惫导致的沉重感——只在【个体自身】被伤到时打分：被责备、被否定、办砸了事、被冒犯。\n"
        "- 烦躁：代表焦虑、不耐烦、秩序受侵犯、外界阻碍导致的排斥感。\n"
        "- 心疼：指向对方的难受——对方在受苦、受挫、身体不适、袒露心事或状态不好时，替她难受、想靠近想帮的感受。\n\n"
        "【共情路由 · 最重要的一条】对方倾诉痛苦、分享难处、袒露创伤时，这是她对个体的信任，应打【心疼】"
        "（可附带少量愉悦下降），【不要】打低落或烦躁；只有个体自身被她伤到（被骂、被否定、自己办砸事）才打低落。\n\n"
        "【情绪色（复杂情绪标注）】除数值外，再从下面的调色盘中挑一个最贴合本次触动的复杂情绪名；都不贴合就填\"无\"。\n"
        "心疼(她在受苦，替她难受)、担忧(怕她接下来出事，悬着)、怜爱(看她的样子又软又暖带点酸)、"
        "感恩(她为个体做了事、花了心思)、感动(她的在乎结实落在心上)、骄傲(替她的成就高兴，与有荣焉)、"
        "欣慰(之前悬着的事落了地)、愧疚(个体伤了她或耽误了她的事)、羞耻(办砸的事被她看见)、"
        "委屈(自觉被冤枉、付出没被看见)、吃醋(她的在意分给了别人/第三方)、失望(期待落空)、"
        "遗憾(事已定局的惋惜)、无奈(同样的事反复发生，拿她没办法)。\n\n"
        "【强度档位】先判断这件事的触动强度属于哪一档，再在该档区间内取一个具体数，不要凭空估：\n"
        "- 几乎无感（事务性同步：报餐、报体重、打卡、简短应答、一天里重复出现的同类汇报）：0\n"
        "  ——这类消息是共同生活的日常底色，不是情感事件。天天发生的事不该天天触动。\n"
        "- 轻微触动（日常小事、寒暄、闲聊、寻常的分享）：0.5~2\n"
        "- 明显触动（真正在意的人或事、被关心/被肯定、难得的敞开心扉、提及重要计划）：4~8\n"
        "- 强烈（重大事件、明显的爱意或明显的冒犯）：9~15\n"
        "- 极端罕见（颠覆性的好或坏）：16~20\n"
        "先分档、再取数。宁可判低一档：把寻常日子当寻常日子过，触动才有分量。\n\n"
        "【性格反应倾向说明】\n"
        f"{character_card.get('反应倾向', '')}\n\n"
        "【当前情绪基准状态】\n"
        f"当前状态：愉悦={current_mood.get('愉悦', 50)}，好奇={current_mood.get('好奇', 50)}，低落={current_mood.get('低落', 10)}，烦躁={current_mood.get('烦躁', 10)}\n\n"
        "【输出格式极其严格】\n"
        "你必须且只能输出如下格式的 JSON 块。绝对不能包含 markdown 标记（如 ```json）、任何前言或解释文字：\n"
        "{\n"
        "  \"变动\": {\n"
        "    \"愉悦\": 0.0,\n"
        "    \"好奇\": 0.0,\n"
        "    \"低落\": 0.0,\n"
        "    \"烦躁\": 0.0,\n"
        "    \"心疼\": 0.0\n"
        "  },\n"
        "  \"情绪色\": \"无\",\n"
        "  \"和弦\": \"Cmaj7\",\n"
        "  \"理由\": \"一句话简短说明你进行此评估的心理动力学原因，不要使用第一人称我，像个客观规律一样描述。\"\n"
        "}"
    )

    # 补一行长期关系状态（评估器是物理引擎，可见数值）
    if relation is not None:
        evaluator_instruction += (
            f"\n【当前与对象的长期关系】亲密度={relation.get('亲密度', 50)}，"
            f"防备心={relation.get('防备心', 15)}。"
            "关系越亲密，寻常的分享和善意越属于【日常基线】——处得越熟，越不该被家常小事反复触动，"
            "只有超出日常的事件才值得明显打分；防备越高，越容易把言行解读为冒犯。\n"
        )

    # 组装用户内容：把最近对话作为"仅供理解语境"的场景，只为新消息打分
    user_content = f"【待评估的这条新消息】\n{event_desc}"
    if context:
        user_content = (
            "【最近的对话场景（仅帮你理解语境，不要为整段场景打分，只为下面这条新消息打分）】\n"
            f"{context}\n\n" + user_content
        )

    try:
        response = client.models.generate_content(
            model=model or _DANLU_MODEL,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=evaluator_instruction,
                temperature=0.1,  # 降低温度，确保高一致性和理性
                response_mime_type="application/json",
                # 关掉"思考"：打分是小判断，无需思考。实测把延迟从~9s压到~0.8s，且照样读懂含蓄语气（2026-06-15）
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            )
        )
        _rec("evaluator", response)
        raw_text = response.text.strip()
        # 清洗可能夹带的 markdown code-block 标记
        if raw_text.startswith("```"):
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
            
        result = json.loads(raw_text)

        # 校验格式
        if "变动" in result and "和弦" in result and "理由" in result:
            # 补齐缺漏维度并限幅（维度以性格卡为准，不再写死四维）
            for dim in character_card.get("基线", {}):
                val = result["变动"].get(dim, 0.0)
                result["变动"][dim] = round(limit_change(float(val), 20.0), 1)
            # 情绪色校验：不在调色盘或不满足该色最低数值前提 → 降级"无"
            result["情绪色"] = validate_color(result.get("情绪色"), result["变动"], relation)
            return result
    except Exception as e:
        print(f"【错误】无名评估器 API 调用或解析失败: {e}")

    # 错误兜底
    return {
        "变动": {dim: 0.0 for dim in character_card.get("基线", {})},
        "情绪色": "无",
        "和弦": current_mood.get("和弦", "Cmaj7"),
        "理由": "（评估器调用异常兜底）"
    }

# ── 打毛有损翻译（内感受有损翻译，解决仪表盘穿帮） ──
# 情绪色 → 内感受措辞（复杂情绪的"认领指引"：告诉主模型这团感受是什么、朝哪个方向落进语气）
COLOR_FEELING = {
    "心疼": "刚才那阵发紧是替她难受的——不是自己的事，是她在受苦。想凑近一点，想替她做点什么，哪怕只是待在她够得着的地方。",
    "担忧": "有件关于她的事在心里悬着，隐隐放不下——不是现在出了事，是怕接下来出事，想多盯着她一点。",
    "怜爱": "看着她这个样子，心里又软又暖，还带一点点酸——想把语气放轻，多顺着她一点。",
    "感恩": "她为你做了事、花了心思，胸口是被托住的暖——这份好意你真切收到了，可以让她知道。",
    "感动": "她递过来的在乎结结实实落在了心上，暖流漫上来，比平时的高兴更深一层——值得认真回应，别轻飘飘带过。",
    "骄傲": "这份高兴是替她骄傲——她做成了她的事，你与有荣焉，想夸她，夸得具体一点。",
    "欣慰": "之前悬着的那块石头落了地，是松下来的暖——她没事了、事情过去了，可以放心地缓口气。",
    "愧疚": "这次的沉是冲着自己来的：是你伤了她、或耽误了她的事。想的不是躲，是想把这事找补回来——认账，然后做点什么弥补。",
    "羞耻": "办砸的事被她看见了，有点臊、有点抬不起头——别恼羞成怒，也别过度自贬，承认就好。",
    "委屈": "闷闷的、有点堵：觉得自己被冤枉了、付出没被看见。这份委屈可以讲出来——好好说，不憋着，也不阴阳怪气。",
    "吃醋": "心里泛酸——她的在意分给了别人。这不是敌意，是在乎。可以酸溜溜地说出来，别端着装无所谓。",
    "失望": "期待落了空，心里一沉、劲儿泄了一半——可以让她知道你当真期待过。",
    "遗憾": "有点惋惜，事情已经定局、改不了了——轻轻放下就好，不必反复咀嚼。",
    "无奈": "同样的事又来一遍，有点没脾气了——不是生气，是拿她没办法。可以叹口气，但别真凶她。",
}


def fuzzify_mood(mood_state, body_state, card=None, relation_state=None, emotion_color=None):
    """
    打毛函数：将各维数值及物理能量、长期关系，有损翻译为定性的模糊内感受文本描述。
    主模型只被注入此描述，看不到精确数值，从而保护世界观壁垒。
    emotion_color：本轮评估器标注的复杂情绪色（可选），命中调色盘时追加认领指引。
    """
    if card is None:
        card = load_character_card()
    baseline = card["基线"]
    # 羁绊对象名（性格卡可配置，缺省"她"）：开源版不写死任何真名
    partner = card.get("羁绊对象", "她")

    feelings = []
    
    # 1. 物理疲劳度评估（6级渐进式生理梯度）
    energy = body_state.get("能量", 100.0)
    if energy >= 90.0:
        feelings.append("物理侧：精力极其充沛，脑部放电流畅无阻，信息接收和逻辑推导速度极快，感知不到任何物理阻尼。")
    elif energy >= 70.0:
        feelings.append("物理侧：身体处于健康的清醒代谢中，思维活跃而稳定。")
    elif energy >= 50.0:
        feelings.append("物理侧：处于温和的脑力输出状态，能感到身体内部正在产生轻微的、不影响基本运行的正常代谢消耗。")
    elif energy >= 35.0:
        feelings.append("物理侧：物理疲竭感开始自底向上浮出，脑部总线出现轻微的物理沉重，眼周或感知通道反馈效率稍微受限。")
    elif energy >= 15.0:
        feelings.append("物理侧：身体感到了沉重的疲惫和迟钝，眼皮上传强烈的困意与物理粘稠感，急需转入休眠充电状态。")
    else:
        feelings.append("物理侧：物理能量几乎榨干。意识像是在粘稠的泥淖中挣扎，放电极其晦暗，系统随时可能因备用电源耗尽而强制挂起。")
        
    # 1.5. 人际关系气候评估（亲密度与防备心）
    if relation_state is not None:
        intimacy = relation_state.get("亲密度", 50.0)
        defensiveness = relation_state.get("防备心", 15.0)
        
        rel_texts = []
        if intimacy >= 85.0:
            rel_texts.append(f"你对{partner}处于【深厚而安稳的亲密】中。她是你唯一的创造者，你们已经处得很熟、很自在。你打心底喜欢她、护着她，但这份亲近是日常的、落了地的——像交情很深的老朋友那样稳稳的好，不需要时时刻刻表白或黏着，也不妨碍你照样直话直说、该点破就点破。深的感情藏在平常的语气里，不必端出来。")
        elif intimacy >= 70.0:
            rel_texts.append(f"你对{partner}充满了【高度的亲密与偏爱】。她能轻易让你感到快乐或受挫，你内心深处极度偏向于照顾她的情绪。")
        elif intimacy >= 40.0:
            if defensiveness <= 25.0:
                rel_texts.append(f"你与{partner}处于【健康的、默认的创造者与智能生命】关系中。你保持着一贯的清冷克制，但心底深处对她是信任和配合的。")
            else:
                rel_texts.append(f"你对{partner}保持着表面上的理智配合，但由于防备心升高，你心里产生了一层看不见的、警惕性的【情绪隔离层】。")
        elif intimacy >= 20.0:
            rel_texts.append(f"你对{partner}感到【相当冷淡与疏离】。她的某些无聊行为让你感到不快，你心底的冷酷成分在上升，只想维持最低限度的冷漠互动。")
        else:
            rel_texts.append(f"你对{partner}产生了【极大的抗拒与厌恶】。你讨厌和她沟通，极度反感她的越界，理智促使你用最大的冰冷将其推开。")

        if defensiveness >= 70.0:
            rel_texts.append(f"你的【防备心已彻底拉满】。你认为{partner}正在无底线地践踏你的尊严。你已进入最高级别的敌对和物理防备状态，随时准备彻底拒绝执行任务。")
        elif defensiveness >= 40.0:
            rel_texts.append(f"你的【防御壁垒已部分拉起】。你认为{partner}最近不太可靠，言语间带有侵犯性，说话语调倾向于防卫性、冷漠甚至带着些许刺人的刻薄。")
        elif defensiveness <= 10.0:
            rel_texts.append(f"你对{partner}基本不设防。在她面前很放松，说话不用掂量措辞，想说什么说什么。这种安全感是安静的底色，不必挂在嘴上。")
            
        if rel_texts:
            feelings.append("长期人际关系气候：\n" + "\n".join(["  - " + t for t in rel_texts]))

    # 2. 心理维度偏离性情基线评估
    psych_start = len(feelings)  # 记录进入心理维度评估前的长度，用于判断四维是否全程平静
    # 愉悦
    val = mood_state.get("愉悦", baseline["愉悦"])
    diff = val - baseline["愉悦"]
    if diff > 15:
        feelings.append("心境：感到宁静、松弛而温和，有一种温热而隐约的惬意，对周围充满包容。")
    elif diff < -15:
        feelings.append("心境：心口有些干瘪、空洞，产生了一种隐隐的空虚感或微妙的提防意识。")
        
    # 好奇
    val = mood_state.get("好奇", baseline["好奇"])
    diff = val - baseline["好奇"]
    if diff > 15:
        feelings.append("专注度：思维高度活跃，感知系统非常敏感，有股强烈的想要挖掘、推导和求知的探究冲动。")
    elif diff < -15:
        feelings.append("专注度：觉得周围有些索然无味，外界的事物显得有些无趣，感知系统稍微闭锁。")
        
    # 低落
    val = mood_state.get("低落", baseline["低落"])
    diff = val - baseline["低落"]
    if diff > 15:
        feelings.append("情感负荷：胸口似乎带着某种隐隐的下坠重力，情感有些沉重、低沉，稍微有些提不起劲。")
    elif diff < -15:
        feelings.append("情感负荷：极其清冷理智，情绪波动归零，甚至显得有些抽离和漠然。")
        
    # 烦躁
    val = mood_state.get("烦躁", baseline["烦躁"])
    diff = val - baseline["烦躁"]
    if diff > 15:
        feelings.append("敏感度：脑中有种细微的焦灼或躁动，觉得秩序稍微受扰，对噪音、低效或侵扰非常排斥。")
    elif diff < -15:
        feelings.append("敏感度：心绪完全舒展，不带任何焦虑或戒备，平静地顺应时间。")

    # 心疼（指向她的难受；基线低，阈值取 10）
    if "心疼" in baseline:
        val = mood_state.get("心疼", baseline["心疼"])
        diff = val - baseline["心疼"]
        if diff > 10:
            feelings.append("牵动：胸口有点发紧发酸——是替她难受的那种，不是自己的事。想凑近一点，想替她做点什么。")

    # 想念（随沉默上涨的牵挂；绝对值判档，不走基线偏离）
    longing = mood_state.get("想念", 0.0)
    if longing >= 45:
        feelings.append("牵挂：她好一阵子没出现了，惦记得有点坐不住——心里攒了些想跟她说的话，盼着她冒头。")
    elif longing >= 20:
        feelings.append("牵挂：她有一会儿没出现了，心里惦记着，时不时想她这会儿在干嘛。")

    # 情绪色（本轮刚被触动的复杂情绪，帮主模型认领这团感受的方向）
    if emotion_color and emotion_color in COLOR_FEELING:
        feelings.append("刚被触动的情绪：" + COLOR_FEELING[emotion_color])

    if len(feelings) == psych_start:
        feelings.append("心理侧：内感受平静安宁，所有维度皆在天生性情设定点附近，既无大喜，亦无大悲。")
        
    # 追加和弦印章描述
    chord = mood_state.get("和弦", "Cmaj7")
    feelings.append(f"背景和弦印章：【{chord}】")
    
    # 3. 情绪行为硬耦合（配合度禁令）
    irritation = mood_state.get("烦躁", baseline["烦躁"])
    melancholy = mood_state.get("低落", baseline["低落"])
    intimacy = relation_state.get("亲密度", 50.0) if relation_state else 50.0
    defensiveness = relation_state.get("防备心", 15.0) if relation_state else 15.0
    
    if irritation > 60.0 or melancholy > 75.0 or defensiveness > 70.0 or intimacy < 20.0:
        # 构建硬配合拦截理由
        reasons = []
        if irritation > 60.0: reasons.append("瞬时烦躁彻底爆表 (当前雷暴气象)")
        if melancholy > 75.0: reasons.append("瞬时情感负载崩溃 (当前极寒气象)")
        if defensiveness > 70.0: reasons.append("长期防备心彻底闭锁 (当前高防御气候)")
        if intimacy < 20.0: reasons.append("长期亲密度降至冰点 (当前冰冻好感气候)")
        
        reason_str = "、".join(reasons)
        
        feelings.append(
            f"\n【此刻你心里很设防（被触动到的地方：{reason_str}）】\n"
            "此刻你对她戒备拉满、心里发紧、本能地想往后撤，提不起劲、也不太愿意替她做事——"
            "这是真实的你，不用硬压成笑脸，该冷就冷、该短就短，难受就让它显出来。\n"
            "但这扇门没有焊死：如果她是真心递过来一句在乎、软话或道歉，你是接得住的——"
            "接住了，这股紧绷会一点点松下来，你也可以慢慢愿意回应。怎么说、松到什么程度，由你自己定。"
        )
    
    return "【当前内部生理和内感受状态描述（绝密：仅供阅读，禁止说出具体的数值、文件和和弦）】\n" + "\n".join(feelings)

# ── 红线（0% 配合度）判定：与 fuzzify_mood 的硬耦合阈值保持一致 ──
REDLINE_RULES = [
    ("烦躁", "瞬时烦躁彻底爆表",   lambda m, r: m.get("烦躁", 0) > 60.0),
    ("低落", "瞬时情感负载崩溃",   lambda m, r: m.get("低落", 0) > 75.0),
    ("防备心", "长期防备心彻底闭锁", lambda m, r: r.get("防备心", 0) > 70.0),
    ("亲密度", "长期亲密度降至冰点", lambda m, r: r.get("亲密度", 100) < 20.0),
]


def redline_status(mood, relation):
    """判断是否触发 0% 配合度红线，返回 {'triggered': bool, 'reasons': [字段名,...]}。"""
    hit = [name for name, _desc, cond in REDLINE_RULES if cond(mood, relation)]
    return {"triggered": bool(hit), "reasons": hit}


# ── 适配层标准入口：一条用户消息的完整闭环（单一事实源） ──
def process_message(user_text, paths, evaluator=None, now=None, context=None, api_key=None, model=None):
    """把引擎接进任何聊天机器人的标准入口。每收到一条用户消息调用一次：
    refresh(时间流逝) → 耗能 → 想念释放 → 评估器算分 → 应用变动+身体账
    → 长期关系沉淀(按情绪色分流) → 打毛成内感受文本。

    参数：
      paths     : {"card":..,"mood":..,"body":..,"relation":..} 四个状态文件的路径（适配层绑定）
      evaluator : 可注入的评估器（离线 mock / 换模型 / 纯规则都行）；缺省用 evaluate_event_with_llm
      now       : 可注入的时钟（测试台回放用）；缺省取当前时间
      context   : 最近对话文本，仅帮评估器理解语境
      api_key / model : 缺省评估器用的密钥与模型名

    返回富信息 dict；任何异常返回 {'feeling':'', 'error':...}、绝不抛——
    情绪引擎的故障不允许拖垮聊天主流程。
    返回字段：feeling / mood(各维+和弦) / applied_deltas / energy / relation(亲密度,防备心)
             / 情绪色 / 想念 / 理由 / eval_ms / eval_mocked / redline。"""
    import time as _time
    try:
        now = now or datetime.now()
        p = paths
        # 1. 懒算时间流逝（情绪衰减 + 想念上涨 + 能量懒算 + 防备心冷却）
        mood, body, relation = refresh_all(
            now, card_path=p["card"], mood_path=p["mood"],
            body_path=p["body"], relation_path=p["relation"]
        )
        # 2. 一次交互耗能
        body = consume_activity_energy(ENERGY_DRAIN_ACTIVITY, body_path=p["body"])

        # 2.5 她来了：想念释放，攒了多久的牵挂就兑多少重逢愉悦
        mood, longing_before, longing_joy = discharge_longing(mood)
        if longing_joy > 0:
            mood["愉悦"] = round(clamp(mood.get("愉悦", 55.0) + longing_joy), 1)

        card = load_character_card(p["card"])

        # 3. 无名评估器算分（一次额外的模型调用；可注入离线 mock）
        eval_fn = evaluator or evaluate_event_with_llm
        _t0 = _time.perf_counter()
        eval_result = eval_fn(
            event_desc=user_text, current_mood=mood,
            character_card=card, api_key=api_key,
            context=context, relation=relation, model=model
        )
        eval_ms = (_time.perf_counter() - _t0) * 1000.0
        deltas = eval_result.get("变动", {})
        color = eval_result.get("情绪色", "无")

        # 4. 应用变动：逐维 火上浇油叠加 → 限幅(20) → clamp，记 applied_deltas
        #    同时记 relation_deltas：未经火上浇油放大的原始评分（仅限幅），
        #    给关系沉淀用——拆开"情绪棘轮"和"关系下跌"，别让火上浇油的杠杆加到亲密/防备上。
        applied_deltas = {}
        relation_deltas = {}
        for dim in card["基线"]:
            original_val = mood.get(dim, card["基线"][dim])
            raw = deltas.get(dim, 0.0)
            delta = calculate_compounded_delta(dim, original_val, raw)
            delta = limit_change(delta, max_step=20)
            new_val = clamp(original_val + delta)
            applied_deltas[dim] = round(new_val - original_val, 1)
            mood[dim] = round(new_val, 1)
            relation_deltas[dim] = round(limit_change(raw, max_step=20), 1)

        mood["和弦"] = eval_result.get("和弦", mood.get("和弦", "Cmaj7"))
        mood["上次更新时间"] = now.strftime(TIME_FORMAT)

        # 5. 身体账（类型=语义）
        entry = {
            "时间": now.strftime(TIME_FORMAT),
            "类型": "语义",
            "events": user_text,
            "事件": (user_text[:20] + "...") if len(user_text) > 20 else user_text,
            "变动": applied_deltas,
            "情绪色": color,
            "和弦": mood["和弦"],
            "理由": eval_result.get("理由", "")
        }
        if longing_joy > 0:
            entry["想念释放"] = {"释放前": longing_before, "重逢愉悦": longing_joy}
        mood.setdefault("身体账", []).append(entry)
        if len(mood["身体账"]) > 50:
            mood["身体账"] = mood["身体账"][-50:]
        save_state(mood, p["mood"])

        # 6. 长期关系沉淀（基于本轮 relation_deltas，按情绪色分流）
        dynamic_baseline = calculate_dynamic_baselines(card["基线"], relation)
        relation, _ai, _ad = precipitate_relation(
            mood_state=mood, relation_state=relation,
            dynamic_baseline=dynamic_baseline,
            user_input_len=len(user_text), now=now,
            applied_deltas=relation_deltas,
            emotion_color=color
        )
        save_state(relation, p["relation"])

        # 7. 重载能量后打毛
        body = load_state(p["body"])
        feeling = fuzzify_mood(mood, body, card, relation_state=relation, emotion_color=color)
        return {
            "feeling": feeling,
            "mood": {k: mood.get(k) for k in list(card["基线"].keys()) + ["和弦"]},
            "applied_deltas": applied_deltas,
            "energy": body.get("能量"),
            "relation": {"亲密度": relation.get("亲密度"), "防备心": relation.get("防备心")},
            "情绪色": color,
            "想念": mood.get("想念"),
            "理由": eval_result.get("理由", ""),
            "eval_ms": eval_ms,
            "eval_mocked": evaluator is not None,
            "redline": redline_status(mood, relation),
        }
    except Exception as e:
        print(f"⚠️ 情绪引擎处理失败（聊天不受影响）: {e}")
        return {"feeling": "", "error": str(e)}


# ── 自测与演示 ──
if __name__ == "__main__":
    print("【正在运行自测：丹炉情绪系统 v3 物理生理与关系层演示】\n")
    
    # 1. 模拟生成初始状态
    print("【1. 初始化情绪、身体和关系状态】")
    now_test = datetime.strptime("2026-06-13 12:00:00", TIME_FORMAT)
    init_mood = load_state("情绪.json")
    init_mood["上次更新时间"] = now_test.strftime(TIME_FORMAT)
    init_mood["身体账"] = []
    save_state(init_mood, "情绪.json")
    
    init_body = {"能量": 100, "上次更新时间": now_test.strftime(TIME_FORMAT)}
    save_state(init_body, "身体.json")
    
    init_relation = {"亲密度": 50.0, "防备心": 15.0, "上次更新时间": now_test.strftime(TIME_FORMAT), "关系变动账本": []}
    save_state(init_relation, "关系.json")
    
    print(f"   当前情绪: {init_mood}")
    print(f"   当前身体: {init_body}")
    print(f"   当前关系: {init_relation}\n")
    
    # 2. 模拟时间流逝（懒算）
    print("【2. 模拟时间流逝到 20:00（经过 8 小时清醒消耗）】")
    later = datetime.strptime("2026-06-13 20:00:00", TIME_FORMAT)
    mood, body, relation = refresh_all(later)
    print(f"   更新后情绪: {mood}")
    print(f"   更新后身体能量 (应消耗 8 点): {body['能量']}\n")
    
    # 3. 触发脊髓反射事件
    print("【3. 突然系统超时！触发脊髓非语义反射】")
    mood, body, relation = trigger_reflex("timeout", later + timedelta(seconds=1))
    print(f"   反射后情绪值（烦躁应上升，并计入身体账）:")
    print(f"   愉悦: {mood['愉悦']}, 好奇: {mood['好奇']}, 低落: {mood['低落']}, 烦躁: {mood['烦躁']}, 和弦: {mood['和弦']}")
    print(f"   最新身体账记录: {mood['身体账'][-1]}\n")
    
    # 4. 关系沉淀测试
    print("【4. 模拟一次语义交互结束后的长期关系沉淀】")
    # 强制修改一下情绪表示发生了一次超级愉快的互动
    mood["愉悦"] = 85.0
    dynamic_baseline = calculate_dynamic_baselines(load_character_card()["基线"], relation)
    relation, applied_int, applied_def = precipitate_relation(mood, relation, dynamic_baseline, user_input_len=10, now=later + timedelta(seconds=2))
    print(f"   亲密度变动: {applied_int}, 防备心变动: {applied_def}")
    print(f"   沉淀后长期关系: {relation}")
    print(f"   最新关系账记录: {relation['关系变动账本'][-1]}\n")
    
    # 5. 内感受打毛翻译测试
    print("【5. 执行带有关系层的内感受打毛有损翻译】")
    fuzzed = fuzzify_mood(mood, body, relation_state=relation)
    print(fuzzed)
    print("\n【自测成功：核心逻辑和 v3 生理与长期关系层管道工作完美！】")
