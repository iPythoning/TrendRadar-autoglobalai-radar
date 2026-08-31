# coding=utf-8
"""
动态关键词优化器

基于最新抓取的新闻标题，自动发现新的品牌、车型、市场、政策/贸易信号，
输出候选关键词建议到 config/suggest_keywords.txt，供人工确认后写入 frequency_words.txt。

设计目标：
- 利用「国内信息差」—— 中国市场的最新热点中，海外买家尚未关注到的品牌/车型/信号
- 不直接修改 frequency_words.txt，避免污染主词表
- 每日运行一次，输出 TOP N 候选词
"""

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from trendradar.ai.client import AIClient


# 已知的品牌/车型/市场/信号词典（用于过滤和辅助识别）
KNOWN_BRANDS = {
    "比亚迪", "BYD", "奇瑞", "Chery", "吉利", "Geely", "长安", "Changan",
    "广汽", "GAC", "上汽", "SAIC", "长城", "Great Wall", "北汽", "BAIC",
    "东风", "Dongfeng", "蔚来", "NIO", "小鹏", "XPeng", "理想", "Li Auto",
    "零跑", "Leapmotor", "哪吒", "Neta", "极氪", "ZEEKR", "领克", "Lynk",
    "深蓝", "Deepal", "阿维塔", "Avatr", "埃安", "Aion", "问界", "AITO",
    "传祺", "Trumpchi", "哈弗", "Haval", "坦克", "Tank", "欧拉", "ORA",
    "名爵", "MG", "大通", "Maxus", "五菱", "Wuling", "宝骏", "Baojun",
    "宇通", "Yutong", "金龙", "King Long", "中通", "Zhongtong", "重汽",
    "Sinotruk", "福田", "Foton", "江淮", "JAC", "解放", "FAW",
}

KNOWN_MARKETS = {
    "俄罗斯", "中亚", "哈萨克斯坦", "乌兹别克斯坦", "伊朗", "中东",
    "阿联酋", "迪拜", "沙特", "巴西", "墨西哥", "智利", "阿根廷",
    "拉美", "非洲", "埃及", "东南亚", "泰国", "越南", "马来西亚",
    "欧洲", "欧盟", "德国", "英国", "土耳其",
}

KNOWN_SIGNALS = {
    "出口", "销量", "降价", "涨价", "关税", "海运费", "滚装船",
    "动力电池", "磷酸铁锂", "智能驾驶", "自动驾驶", "充电桩",
    "出口许可证", "原产地", "反倾销", "补贴", "购置税",
}

# 车型常见后缀模式（用于从标题中提取车型）
MODEL_SUFFIX_PATTERN = re.compile(
    r"([\u4e00-\u9fa5]{2,6}|[A-Z][a-zA-Z0-9\s]{1,10})"
    r"(?:\s*(?:\d{1,2}|Pro|Plus|Max|Ultra|L|EV|PHEV|DM-i|DM-p|GT|RS|SUV|轿车|版))?"
)


def load_frequency_words(path: str = "config/frequency_words.txt") -> Set[str]:
    """加载已有频率词表"""
    words: Set[str] = set()
    file_path = Path(path)
    if not file_path.exists():
        return words

    for line in file_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("["):
            continue
        # 处理 "=> 别名" 语法
        if "=>" in stripped:
            stripped = stripped.split("=>")[0].strip()
        # 处理正则 /.../
        if stripped.startswith("/") and stripped.endswith("/"):
            stripped = stripped[1:-1]
        words.add(stripped)
    return words


def extract_candidate_terms(titles: List[str]) -> Dict[str, List[str]]:
    """
    从标题中抽取候选关键词
    返回 {category: [terms]}
    """
    candidates: Dict[str, List[str]] = {
        "brand": [],
        "model": [],
        "market": [],
        "signal": [],
    }

    for title in titles:
        # 品牌
        for brand in KNOWN_BRANDS:
            if brand in title:
                candidates["brand"].append(brand)

        # 市场
        for market in KNOWN_MARKETS:
            if market in title:
                candidates["market"].append(market)

        # 信号词
        for signal in KNOWN_SIGNALS:
            if signal in title:
                candidates["signal"].append(signal)

        # 车型：尝试匹配 "品牌 + 系列名/数字" 模式
        # 简单启发式：BYD 汉、奇瑞瑞虎 8、吉利星越 L 等
        for brand in KNOWN_BRANDS:
            if brand not in title:
                continue
            # 找品牌后的 2-6 个字符
            idx = title.find(brand)
            tail = title[idx + len(brand):idx + len(brand) + 8]
            m = re.match(r"[\s·]*(\w+|\u4e00-\u9fa5{1,6})", tail)
            if m:
                model = f"{brand}{m.group(1)}"
                candidates["model"].append(model)

    return candidates


def ai_suggest_keywords(
    titles: List[str],
    existing_words: Set[str],
    ai_config: Dict[str, Any],
    top_n: int = 20,
) -> List[Dict[str, str]]:
    """
    使用 LLM 从标题中发现新的关键词建议
    """
    if not titles:
        return []

    client = AIClient(ai_config)
    if not client.api_key:
        print("[关键词优化] 未配置 AI API Key，跳过 AI 建议")
        return []

    sample = titles[:50]
    content = "\n".join(f"- {t}" for t in sample)
    existing = ", ".join(list(existing_words)[:200])

    prompt = f"""你是一个中国汽车出口市场情报分析师。请从以下中文新闻标题中，发现新的品牌、车型、市场、政策/贸易信号关键词。

现有已知关键词（无需重复）：{existing}

新闻标题：
{content}

要求：
1. 只输出真正与汽车出口相关的新词
2. 每个候选词给出：term（中文）、category（brand/model/market/signal）、reason（为什么值得监控）
3. 优先选择海外买家可能不熟悉但中国市场正在热炒的「信息差」词汇
4. 输出严格 JSON 数组，不要任何解释

输出格式：
[{{"term": "...", "category": "...", "reason": "..."}}]
"""

    try:
        response = client.chat([
            {"role": "system", "content": "你是一个专业的汽车出口市场情报分析师。只输出 JSON 数组。"},
            {"role": "user", "content": prompt},
        ])
        # 清理可能的 markdown fence
        cleaned = response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("\n", 1)[0]
        cleaned = cleaned.strip()

        suggestions = json.loads(cleaned)
        if isinstance(suggestions, list):
            # 去重
            seen = set()
            unique = []
            for s in suggestions:
                term = s.get("term", "").strip()
                if term and term not in existing_words and term not in seen:
                    seen.add(term)
                    unique.append(s)
            return unique[:top_n]
    except Exception as e:
        print(f"[关键词优化] AI 建议失败: {e}")

    return []


def generate_suggestions(
    titles: List[str],
    output_path: str = "config/suggest_keywords.txt",
    ai_config: Optional[Dict[str, Any]] = None,
) -> None:
    """
    生成候选关键词建议文件
    """
    existing = load_frequency_words()
    candidates = extract_candidate_terms(titles)

    lines = [
        "# ═══════════════════════════════════════════════════════════════",
        f"#  动态关键词建议 · 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "#  来源：最新抓取的中文汽车出口新闻标题",
        "#  用法：人工审核后，将合适的词复制到 config/frequency_words.txt",
        "# ═══════════════════════════════════════════════════════════════",
        "",
    ]

    # 规则统计候选
    for category, items in candidates.items():
        if not items:
            continue
        counter = Counter(items)
        lines.append(f"\n# [{category.upper()}] 高频候选（出现次数）")
        for term, count in counter.most_common(30):
            if term not in existing:
                lines.append(f"{term}  # 出现 {count} 次")

    # AI 建议
    ai_suggestions: List[Dict[str, str]] = []
    if ai_config:
        ai_suggestions = ai_suggest_keywords(titles, existing, ai_config)

    if ai_suggestions:
        lines.append("\n# [AI 发现] 信息差候选词")
        for s in ai_suggestions:
            lines.append(
                f"{s.get('term', '')}  # category={s.get('category', '')}, reason={s.get('reason', '')}"
            )

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"[关键词优化] 已生成建议文件：{output_path}")


if __name__ == "__main__":
    # 简单测试
    test_titles = [
        "比亚迪海鸥出口巴西销量暴涨",
        "奇瑞瑞虎8在俄罗斯受欢迎",
        "长城山海炮进军中东市场",
        "新能源车出口中亚增长迅速",
        "霍尔果斯口岸汽车出口量大增",
    ]
    generate_suggestions(test_titles)
