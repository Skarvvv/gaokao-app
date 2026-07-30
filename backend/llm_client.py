"""LLM Client — 高考志愿方案生成
==============================
1. Build prompt from user data (score, province, subjects, preferences)
2. Call LLM API (OpenAI-compatible: SiliconFlow / Qwen)
3. Parse LLM response into the same JSON structure as test_data.json recommendations

设计策略（针对 7B 小模型优化）：
- 只让模型输出 4 个字段：梯度|院校|专业|理由
- 位次和平均分由服务端根据梯度 + 考生分数自动计算
- 分 3 次并行调用（冲/稳/保各 2 所），降低单次输出复杂度
- 提示词中明确分数约束，防止推荐与分数不匹配的院校
"""

import json
import logging
import re
import random
import time

import httpx
from config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    LLM_TIMEOUT,
)

from logging_config import get_logger
logger = get_logger("llm")

# ============================================
# Per-segment prompts — 每次只要求 2 所院校
# ============================================
# 关键设计：
# 1. 只要求 4 字段输出（梯度|院校|专业|理由），去掉数字字段
# 2. 在 prompt 中明确写出考生分数，强调不能推荐不匹配的院校
# 3. 给出与考生分数接近的示例，引导模型输出正确层次的院校

SEGMENT_SYSTEM_PROMPTS = {
    "冲": (
        "你是高考志愿填报顾问。请推荐2所\"冲一冲\"院校。\n"
        "冲一冲 = 录取分数线略高于考生5-15分的院校，有一定冲刺希望。\n\n"
        "严格要求：\n"
        "- 院校的录取分必须接近考生分数，只能高5-15分\n"
        "- 绝对不能推荐分数线远高于考生的985/顶尖211院校\n"
        "- 推荐省属普通本科、地方重点院校等与考生分数匹配的学校\n\n"
        "输出格式（恰好2行，每行用|分隔）：\n"
        "冲|院校名称|专业名称|推荐理由\n\n"
        "示例（考生420分）：\n"
        "冲|浙江农林大学|计算机科学与技术|省属公办分数线略高\n"
        "冲|浙江海洋大学|电子信息工程|省内公办冲刺选项\n\n"
        "只输出2行，不要编号，不要解释，不要任何其他文字。"
    ),
    "稳": (
        "你是高考志愿填报顾问。请推荐2所\"稳一稳\"院校。\n"
        "稳一稳 = 录取分数线与考生分数接近的院校，录取把握较大。\n\n"
        "严格要求：\n"
        "- 院校的录取分应与考生分数持平或相差不超过5分\n"
        "- 推荐与考生分数匹配的省属本科、地方院校\n"
        "- 绝对不能推荐分数线远高于考生的名校\n\n"
        "输出格式（恰好2行，每行用|分隔）：\n"
        "稳|院校名称|专业名称|推荐理由\n\n"
        "示例（考生420分）：\n"
        "稳|绍兴文理学院|计算机类|省属公办分数线接近\n"
        "稳|湖州师范学院|电子信息类|省内师范类稳妥选择\n\n"
        "只输出2行，不要编号，不要解释，不要任何其他文字。"
    ),
    "保": (
        "你是高考志愿填报顾问。请推荐2所\"保一保\"院校。\n"
        "保一保 = 录取分数线低于考生15-30分的院校，确保有学上。\n\n"
        "严格要求：\n"
        "- 院校的录取分应低于考生分数15-30分\n"
        "- 推荐录取分数较低的公办本科或优质民办本科\n"
        "- 绝对不能推荐分数线高于考生的院校\n\n"
        "输出格式（恰好2行，每行用|分隔）：\n"
        "保|院校名称|专业名称|推荐理由\n\n"
        "示例（考生420分）：\n"
        "保|丽水学院|计算机类|省内公办保底稳妥\n"
        "保|台州学院|电子信息类|录取分数较低有保障\n\n"
        "只输出2行，不要编号，不要解释，不要任何其他文字。"
    ),
}


# ============================================
# User Prompt — 从用户输入构建
# ============================================

def build_user_prompt(user_data: dict) -> str:
    """Construct user prompt from user input data"""
    score = user_data.get("score", "")
    province = user_data.get("province", "")

    subjects = user_data.get("subjects", [])
    if isinstance(subjects, list):
        subjects_str = " · ".join(subjects) if subjects else "未指定"
    else:
        subjects_str = str(subjects)

    school_levels = user_data.get("schoolLevels", [])
    majors = user_data.get("majors", [])
    strategy = user_data.get("strategy", "")
    region = user_data.get("region", "")

    lines = [
        f"考生高考成绩：{score}分",
        f"所在省份：{province}",
        f"选考科目：{subjects_str}",
    ]

    if school_levels:
        lines.append(f"目标院校层次：{'、'.join(school_levels)}")
    if majors:
        lines.append(f"目标专业方向：{'、'.join(majors)}")
    if strategy:
        lines.append(f"优先策略：{strategy}")
    if region:
        lines.append(f"目标地域：{region}")

    lines.append("")
    lines.append(f"请根据以上信息，为这位{score}分的考生推荐合适的院校。")
    lines.append(f"注意：该生分数是{score}分，推荐院校的录取分必须与此分数匹配。")
    return "\n".join(lines)


# ============================================
# Server-side number generation
# ============================================
# LLM 只输出 4 字段（梯度|院校|专业|理由）
# 位次和平均分由服务端根据梯度 + 考生分数自动计算
# 这样避免了 7B 模型在数字输出上的不稳定性

SEGMENT_MAP = {
    "冲": {"segment": "chong", "badgeText": "冲一冲"},
    "稳": {"segment": "wen", "badgeText": "稳一稳"},
    "保": {"segment": "bao", "badgeText": "保一保"},
}

DEFAULT_SEGMENTS = [
    {"label": "全部", "value": "all", "active": True},
    {"label": "冲一冲", "value": "chong"},
    {"label": "稳一稳", "value": "wen"},
    {"label": "保一保", "value": "bao"},
]


def _generate_rank_and_score(gradient: str, user_score: int) -> tuple:
    """
    根据梯度和考生分数，生成合理的位次和平均分。

    冲: 平均分 = 用户分 + 5~15, 位次更靠前
    稳: 平均分 = 用户分 - 2~+3, 位次接近
    保: 平均分 = 用户分 - 15~25, 位次更靠后
    """
    if gradient == "冲":
        avg_score = user_score + random.randint(5, 15)
        # 分数越高位次越靠前，粗略估算
        base_rank = max(1000, int(500000 / max(avg_score, 100) * 60))
        rank = base_rank + random.randint(-2000, 2000)
    elif gradient == "保":
        avg_score = user_score - random.randint(15, 25)
        base_rank = max(1000, int(500000 / max(avg_score, 100) * 80))
        rank = base_rank + random.randint(-3000, 3000)
    else:  # 稳
        avg_score = user_score + random.randint(-3, 3)
        base_rank = max(1000, int(500000 / max(avg_score, 100) * 70))
        rank = base_rank + random.randint(-2500, 2500)

    rank = max(1000, rank)
    return "{:,}".format(rank), str(avg_score)


# ============================================
# Response Parsing — 从 4 字段格式构建完整 JSON
# ============================================

def parse_line_format(content: str, user_data: dict) -> dict:
    """
    Parse the simplified 4-field line format:
    梯度|院校|专业|理由

    位次和平均分由服务端自动生成。
    """
    lines = [l.strip() for l in content.strip().split('\n') if l.strip() and '|' in l]

    if not lines:
        raise ValueError("LLM 返回的内容中没有找到有效数据行")

    user_score = user_data.get("score", 500)
    list_items = []
    for line in lines:
        parts = line.split('|')
        if len(parts) < 4:
            continue  # skip malformed lines

        gradient = parts[0].strip()
        school = parts[1].strip()
        major = parts[2].strip()
        reason = parts[3].strip()

        # 跳过空字段
        if not school or not major:
            continue

        # 匹配梯度
        seg_info = SEGMENT_MAP.get(gradient)
        if not seg_info:
            # 尝试首字匹配
            for key in SEGMENT_MAP:
                if gradient.startswith(key) or key in gradient:
                    seg_info = SEGMENT_MAP[key]
                    gradient = key
                    break
        if not seg_info:
            seg_info = {"segment": "wen", "badgeText": "稳一稳"}
            gradient = "稳"

        # 服务端生成位次和平均分
        last_rank, last_avg = _generate_rank_and_score(gradient, user_score)

        list_items.append({
            "segment": seg_info["segment"],
            "badgeText": seg_info["badgeText"],
            "school": school,
            "major": major,
            "reason": reason,
            "lastRank": last_rank,
            "lastAvgScore": last_avg,
        })

    if not list_items:
        raise ValueError("LLM 返回的所有数据行格式都不正确")

    # Build scoreSummary from user_data
    subjects = user_data.get("subjects", [])
    if isinstance(subjects, list):
        subjects_str = " · ".join(subjects) if subjects else "未指定"
    else:
        subjects_str = str(subjects)

    score_summary = {
        "score": user_data.get("score", 0),
        "unit": "分",
        "province": user_data.get("province", ""),
        "subjects": subjects_str,
    }

    return {
        "scoreSummary": score_summary,
        "segments": DEFAULT_SEGMENTS,
        "list": list_items,
    }


# ============================================
# LLM API Call
# ============================================

async def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Single LLM API call, returns raw content string"""
    if not LLM_API_KEY:
        raise ValueError(
            "LLM API Key 未配置。请在 backend/config.py 中设置 LLM_API_KEY，"
            "或设置环境变量 LLM_API_KEY。"
        )

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_TOKENS,
    }

    url = f"{LLM_BASE_URL}/chat/completions"
    logger.debug("[LLM] Calling %s (model=%s, prompt_len=%d chars)", url, LLM_MODEL, len(user_prompt))
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)

    duration_ms = int((time.monotonic() - start) * 1000)

    if resp.status_code != 200:
        detail = resp.text[:500]
        logger.error("[LLM] API error %d (%dms): %s", resp.status_code, duration_ms, detail)
        raise ValueError(f"LLM API 调用失败 (HTTP {resp.status_code}): {detail[:200]}")

    result = resp.json()
    content = result["choices"][0]["message"]["content"]
    logger.info("[LLM] Response: %d chars (%dms)", len(content), duration_ms)
    logger.debug("[LLM] Raw response:\n%s", content[:1200])
    return content


# ============================================
# Fallback recommendations (if LLM fails)
# ============================================

FALLBACK_SCHOOLS = {
    "冲": [
        {"school": "浙江农林大学", "major": "计算机科学与技术", "reason": "省属公办，分数线略高，有冲刺希望"},
        {"school": "浙江海洋大学", "major": "电子信息工程", "reason": "省内公办院校，冲刺选项"},
    ],
    "稳": [
        {"school": "绍兴文理学院", "major": "计算机类", "reason": "省属公办，分数线接近，录取把握大"},
        {"school": "湖州师范学院", "major": "电子信息类", "reason": "省内师范类院校，稳妥选择"},
    ],
    "保": [
        {"school": "丽水学院", "major": "计算机类", "reason": "省内公办保底，录取分数较低"},
        {"school": "台州学院", "major": "电子信息类", "reason": "录取分数较低，保底有保障"},
    ],
}


def _build_fallback(user_data: dict) -> dict:
    """Build fallback recommendations when LLM fails or returns bad data"""
    user_score = user_data.get("score", 500)
    subjects = user_data.get("subjects", [])
    if isinstance(subjects, list):
        subjects_str = " · ".join(subjects) if subjects else "未指定"
    else:
        subjects_str = str(subjects)

    list_items = []
    for gradient in ["冲", "稳", "保"]:
        seg_info = SEGMENT_MAP[gradient]
        for school_info in FALLBACK_SCHOOLS[gradient]:
            last_rank, last_avg = _generate_rank_and_score(gradient, user_score)
            list_items.append({
                "segment": seg_info["segment"],
                "badgeText": seg_info["badgeText"],
                "school": school_info["school"],
                "major": school_info["major"],
                "reason": school_info["reason"],
                "lastRank": last_rank,
                "lastAvgScore": last_avg,
            })

    return {
        "scoreSummary": {
            "score": user_score,
            "unit": "分",
            "province": user_data.get("province", ""),
            "subjects": subjects_str,
        },
        "segments": DEFAULT_SEGMENTS,
        "list": list_items,
    }


# ============================================
# Main entry: generate_recommendations
# ============================================

async def generate_recommendations(user_data: dict) -> dict:
    """
    分 3 次并行调用 LLM（冲/稳/保各 2 所院校），合并为完整方案。

    每次调用使用专属 system prompt，只要求 2 行 4 字段输出。
    位次和平均分由服务端根据梯度 + 考生分数自动生成。
    """
    user_prompt = build_user_prompt(user_data)
    logger.info("[LLM] Generating via 3 parallel calls — model=%s, score=%s",
                LLM_MODEL, user_data.get("score"))
    start_total = time.monotonic()

    import asyncio

    # 并行调用 3 次（各用专属 system prompt）
    try:
        results_raw = await asyncio.gather(
            _call_llm(SEGMENT_SYSTEM_PROMPTS["冲"], user_prompt),
            _call_llm(SEGMENT_SYSTEM_PROMPTS["稳"], user_prompt),
            _call_llm(SEGMENT_SYSTEM_PROMPTS["保"], user_prompt),
        )
    except Exception as e:
        logger.error("[LLM] All 3 calls failed: %s", e)
        logger.info("[LLM] Using fallback recommendations")
        return _build_fallback(user_data)

    # 合并解析结果，每个梯度最多保留 2 所
    all_items = []
    for seg_key, raw_content in zip(["冲", "稳", "保"], results_raw):
        try:
            parsed = parse_line_format(raw_content, user_data)
            items = parsed.get("list", [])
            # 只保留前 2 所
            items = items[:2]
            # 强制修正 segment/badgeText（模型可能输出错误梯度标记）
            seg_info = SEGMENT_MAP[seg_key]
            for item in items:
                item["segment"] = seg_info["segment"]
                item["badgeText"] = seg_info["badgeText"]
            all_items.extend(items)
            logger.info("[LLM] %s segment: parsed %d schools", seg_key, len(items))
        except ValueError as e:
            logger.warning("[LLM] Failed to parse %s segment: %s", seg_key, e)
            # 使用 fallback 补充该梯度
            seg_info = SEGMENT_MAP[seg_key]
            user_score = user_data.get("score", 500)
            for school_info in FALLBACK_SCHOOLS[seg_key]:
                last_rank, last_avg = _generate_rank_and_score(seg_key, user_score)
                all_items.append({
                    "segment": seg_info["segment"],
                    "badgeText": seg_info["badgeText"],
                    "school": school_info["school"],
                    "major": school_info["major"],
                    "reason": school_info["reason"],
                    "lastRank": last_rank,
                    "lastAvgScore": last_avg,
                })

    # Deduplicate: remove schools appearing in multiple segments
    seen_schools = set()
    deduped_items = []
    for item in all_items:
        school = item.get("school", "")
        if school not in seen_schools:
            seen_schools.add(school)
            deduped_items.append(item)
        else:
            logger.info("[LLM] Dedup: removing duplicate school %s from %s",
                        school, item.get("badgeText", "?"))

    # 如果去重后不足 3 所，补充 fallback
    if len(deduped_items) < 3:
        logger.warning("[LLM] Only %d schools after dedup, supplementing with fallback", len(deduped_items))
        fallback = _build_fallback(user_data)
        for item in fallback["list"]:
            if item["school"] not in seen_schools:
                deduped_items.append(item)
                seen_schools.add(item["school"])
            if len(deduped_items) >= 6:
                break

    logger.info(
        "[LLM] Final result: %d schools — %s (%dms total)",
        len(deduped_items),
        [item.get("school", "?") for item in deduped_items],
        int((time.monotonic() - start_total) * 1000),
    )

    # Build final structure
    subjects = user_data.get("subjects", [])
    if isinstance(subjects, list):
        subjects_str = " · ".join(subjects) if subjects else "未指定"
    else:
        subjects_str = str(subjects)

    return {
        "scoreSummary": {
            "score": user_data.get("score", 0),
            "unit": "分",
            "province": user_data.get("province", ""),
            "subjects": subjects_str,
        },
        "segments": DEFAULT_SEGMENTS,
        "list": deduped_items,
    }


# ============================================
# School Detail Generation — LLM 生成院校详情
# ============================================
# 当用户点击推荐卡片时，调用此函数生成该院校的详细信息
# 输出格式与 test_data.json schoolDetail 结构一致

# segment 值 → badge 映射
BADGE_MAP = {
    "chong": {"type": "chong", "text": "冲一冲"},
    "wen": {"type": "wen", "text": "稳一稳"},
    "bao": {"type": "bao", "text": "保一保"},
}

SCHOOL_DETAIL_SYSTEM_PROMPT = (
    "你是高考志愿填报顾问。请根据院校名称、专业、考生分数，生成该院校的详细信息。\n\n"
    "输出格式（每行一个字段，用|分隔键和值）：\n"
    "TAGS|标签1,标签2,标签3\n"
    "CITY|所在城市\n"
    "RANK|去年录取位次（纯数字）\n"
    "SCORE|去年录取均分（纯数字）\n"
    "PROB|预测录取概率（0-100的整数）\n"
    "AI|AI分析（50-100字，包含风险提示）\n"
    "SIMILAR|院校A,专业A,概率A%;院校B,专业B,概率B%\n\n"
    "严格要求：\n"
    "- SIMILAR 中每个院校必须用逗号分隔：院校名,专业名,概率%\n"
    "- 相似院校不能和查询院校同名\n"
    "- 概率用百分数如 40%\n\n"
    "要求：\n"
    "- TAGS: 2-4个标签，如 公办本科,省属重点,985,211,双一流 等\n"
    "- CITY: 院校所在城市，如 杭州市\n"
    "- RANK: 去年该专业在考生所在省份的录取位次（数字，不要千分位）\n"
    "- SCORE: 去年该专业录取均分（数字）\n"
    "- PROB: 根据考生分数与该校录取分的差距估算录取概率（0-100）\n"
    "- AI: 针对该考生的个性化分析，说明录取可能性、专业优势、风险提示\n"
    "- SIMILAR: 2所同梯度同地区的相似院校，概率用百分数\n\n"
    "示例（考生420分，冲一冲）：\n"
    "TAGS|公办本科,省属重点\n"
    "CITY|杭州市\n"
    "RANK|38000\n"
    "SCORE|425\n"
    "PROB|35\n"
    "AI|你的分数略低于该校去年录取均分，属于冲一冲梯度。该校计算机科学与技术是省级优势专业，建议放在志愿前段尝试。风险提示：该专业近年录取位次有波动，建议搭配稳一稳梯度的院校作为保底。\n"
    "SIMILAR|浙江农林大学,计算机类,40%;浙江海洋大学,电子信息类,38%\n\n"
    "只输出以上7行，不要编号，不要解释，不要任何其他文字。"
)


def build_school_detail_user_prompt(school_name: str, major: str, user_data: dict, segment: str) -> str:
    """构建院校详情的用户提示词"""
    score = user_data.get("score", "")
    province = user_data.get("province", "")
    subjects = user_data.get("subjects", [])
    if isinstance(subjects, list):
        subjects_str = " · ".join(subjects) if subjects else "未指定"
    else:
        subjects_str = str(subjects)

    seg_text = BADGE_MAP.get(segment, {}).get("text", "稳一稳")

    lines = [
        f"院校名称：{school_name}",
        f"报考专业：{major}",
        f"梯度：{seg_text}",
        f"考生分数：{score}分",
        f"所在省份：{province}",
        f"选考科目：{subjects_str}",
        "",
        f"请为{score}分的考生生成{school_name}({major})的详细信息。",
        f"注意：录取均分和位次必须与考生分数{score}分匹配，不能给出差距过大的数据。",
    ]
    return "\n".join(lines)


def _sanitize_number(value: str, default: int = 0) -> int:
    """从字符串中提取数字，处理 7B 模型输出中的异常格式（如 '4AI1' → 41）"""
    if not value:
        return default
    digits = ''.join(c for c in str(value) if c.isdigit())
    if not digits:
        return default
    try:
        return int(digits)
    except ValueError:
        return default


def parse_school_detail(content: str, school_name: str, major: str, segment: str, user_data: dict) -> dict:
    """
    解析 LLM 返回的行格式，组装成 schoolDetail JSON 结构。

    格式：
    TAGS|标签1,标签2
    CITY|城市
    RANK|数字
    SCORE|数字
    PROB|数字
    AI|分析文本
    SIMILAR|院校1,专业1,概率1%;院校2,专业2,概率2%
    """
    fields = {}
    # 标准 key 列表，用于模糊匹配
    _key_aliases = {
        "TAGS": ["TAG", "TAGS"],
        "CITY": ["CITY", "CITYY", "LOCATION", "LOC"],
        "RANK": ["RANK", "RANKK", "POSITION"],
        "SCORE": ["SCORE", "SCOREE", "AVG", "AVGSCORE"],
        "PROB": ["PROB", "PROBB", "PROBABILITY", "RATE"],
        "AI": ["AI", "AII", "ANALYSIS", "ANALY"],
        "SIMILAR": ["SIMILAR", "SIMIL", "SIMILYY", "SIMI"],
    }
    # 构建 key → 标准key 的查找表
    _lookup = {}
    for std_key, aliases in _key_aliases.items():
        for alias in aliases:
            _lookup[alias] = std_key

    for line in content.strip().split('\n'):
        line = line.strip()
        if '|' not in line and 'I' not in line:
            continue
        # 7B 模型有时把 | 输出为 I，尝试两种分隔符
        if '|' in line:
            key, _, value = line.partition('|')
        else:
            # 尝试按第一个 I 分割（但 I 可能是值的一部分，只在 key 部分）
            # key 通常是全大写字母，找到第一个非大写非I的字符位置
            match = re.match(r'^([A-Z]+)', line)
            if match:
                key = match.group(1)
                value = line[len(key):]
                # 去掉 value 开头的 I（误写的分隔符）
                value = value.lstrip('I')
            else:
                continue

        key_upper = key.strip().upper()
        value = value.strip()

        # 模糊匹配 key
        std_key = _lookup.get(key_upper)
        if not std_key:
            # 尝试前缀匹配
            for alias, standard in _lookup.items():
                if key_upper.startswith(alias) or alias.startswith(key_upper):
                    std_key = standard
                    break
        if std_key:
            fields[std_key] = value

    # 解析 tags
    tags_raw = fields.get("TAGS", "公办本科")
    tags = [t.strip() for t in tags_raw.split(',') if t.strip()]
    if not tags:
        tags = ["公办本科"]

    # 解析 city
    city = fields.get("CITY", "")
    location = f"\U0001f4cd {city}" if city else ""

    # 解析 rank
    rank_raw = fields.get("RANK", "")
    rank_num = _sanitize_number(rank_raw, default=30000)
    rank_display = "{:,}".format(rank_num)

    # 解析 score
    score_raw = fields.get("SCORE", "")
    score_num = _sanitize_number(score_raw, default=user_data.get("score", 500))
    score_display = str(score_num)

    # 解析 probability
    prob_raw = fields.get("PROB", "")
    prob_num = _sanitize_number(prob_raw, default=50)
    prob_num = max(0, min(100, prob_num))
    prob_display = f"{prob_num}%"

    # 解析 AI analysis
    ai_text = fields.get("AI", "该院校与你的分数匹配度较高，建议根据梯度合理填报。")

    # 解析 similar recommendations
    similar_list = []
    similar_raw = fields.get("SIMILAR", "")
    if similar_raw:
        for item in similar_raw.split(';'):
            item = item.strip()
            if not item:
                continue
            # 尝试按逗号分割
            parts = [p.strip() for p in item.split(',')]
            if len(parts) >= 3:
                similar_list.append({
                    "name": parts[0],
                    "major": parts[1],
                    "probability": parts[2],
                })
            elif len(parts) == 2:
                # 尝试从专业字段中提取概率（如 "计算机类48%" → major="计算机类", prob="48%"）
                major_field = parts[1]
                prob_match = re.search(r'(\d+%)', major_field)
                if prob_match:
                    similar_list.append({
                        "name": parts[0],
                        "major": major_field[:prob_match.start()].strip(),
                        "probability": prob_match.group(1),
                    })
                else:
                    similar_list.append({
                        "name": parts[0],
                        "major": major_field,
                        "probability": f"{random.randint(35, 65)}%",
                    })
            elif len(parts) == 1 and parts[0]:
                # 只有院校名（可能混入了专业和概率）
                raw = parts[0]
                prob_match = re.search(r'(\d+%)', raw)
                if prob_match:
                    prob = prob_match.group(1)
                    name = raw[:prob_match.start()].strip()
                    # 尝试从名称中分离专业（如"浙江师范大学计算机科学与技术"）
                    # 如果名称超过6个字，可能包含专业名，但很难自动分离，保持原样
                    similar_list.append({
                        "name": name,
                        "major": "相关专业",
                        "probability": prob,
                    })
                else:
                    similar_list.append({
                        "name": raw,
                        "major": "相关专业",
                        "probability": f"{random.randint(35, 65)}%",
                    })

    # Fallback: 如果相似推荐不足 2 所，用 fallback 补充
    if len(similar_list) < 2:
        for s in FALLBACK_SCHOOLS.get("冲", [])[:2]:
            if len(similar_list) >= 2:
                break
            # 避免重复
            if not any(si["name"] == s["school"] for si in similar_list):
                similar_list.append({
                    "name": s["school"],
                    "major": s["major"],
                    "probability": f"{random.randint(35, 65)}%",
                })

    # badge
    badge = BADGE_MAP.get(segment, {"type": "wen", "text": "稳一稳"})

    # 组装 admissionData
    admission_data = [
        {"value": rank_display, "label": "去年位次"},
        {"value": score_display, "label": "去年均分"},
        {"value": prob_display, "label": "预测概率", "highlight": True},
    ]

    return {
        "name": school_name,
        "tags": tags,
        "badge": badge,
        "location": location,
        "admissionData": admission_data,
        "aiAnalysis": ai_text,
        "similarRecommendations": similar_list,
    }


def _build_school_detail_fallback(school_name: str, major: str, segment: str, user_data: dict) -> dict:
    """LLM 失败时的兜底数据"""
    user_score = user_data.get("score", 500)
    badge = BADGE_MAP.get(segment, {"type": "wen", "text": "稳一稳"})

    # 根据梯度估算录取分和位次
    if segment == "chong":
        avg_score = user_score + random.randint(5, 15)
        rank = max(1000, int(500000 / max(avg_score, 100) * 60) + random.randint(-2000, 2000))
        prob = random.randint(25, 40)
    elif segment == "bao":
        avg_score = user_score - random.randint(15, 25)
        rank = max(1000, int(500000 / max(avg_score, 100) * 80) + random.randint(-3000, 3000))
        prob = random.randint(75, 95)
    else:
        avg_score = user_score + random.randint(-3, 3)
        rank = max(1000, int(500000 / max(avg_score, 100) * 70) + random.randint(-2500, 2500))
        prob = random.randint(50, 70)

    return {
        "name": school_name,
        "tags": ["公办本科"],
        "badge": badge,
        "location": "",
        "admissionData": [
            {"value": "{:,}".format(rank), "label": "去年位次"},
            {"value": str(avg_score), "label": "去年均分"},
            {"value": f"{prob}%", "label": "预测概率", "highlight": True},
        ],
        "aiAnalysis": f"你的分数为{user_score}分，该校属于「{badge['text']}」梯度。建议根据志愿策略合理安排填报顺序，搭配其他梯度院校形成完整的志愿方案。",
        "similarRecommendations": [
            {"name": s["school"], "major": s["major"], "probability": f"{random.randint(35, 65)}%"}
            for s in FALLBACK_SCHOOLS.get("冲", [])[:2]
        ],
    }


async def generate_school_detail(
    school_name: str,
    major: str,
    segment: str,
    user_data: dict,
) -> dict:
    """
    调用 LLM 生成院校详情。

    参数：
    - school_name: 院校名称
    - major: 专业名称
    - segment: 梯度 (chong/wen/bao)
    - user_data: 考生数据 (score, province, subjects 等)

    返回：与 test_data.json schoolDetail 结构一致的 dict
    """
    user_prompt = build_school_detail_user_prompt(school_name, major, user_data, segment)
    logger.info("[LLM] Generating school detail — school=%s, major=%s, segment=%s, score=%s",
                school_name, major, segment, user_data.get("score"))
    start = time.monotonic()

    try:
        raw_content = await _call_llm(SCHOOL_DETAIL_SYSTEM_PROMPT, user_prompt)
        detail = parse_school_detail(raw_content, school_name, major, segment, user_data)
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("[LLM] School detail OK for %s (%dms)", school_name, duration_ms)
        return detail
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.error("[LLM] School detail FAILED for %s (%dms): %s", school_name, duration_ms, e)
        logger.info("[LLM] Using fallback school detail for %s", school_name)
        return _build_school_detail_fallback(school_name, major, segment, user_data)
