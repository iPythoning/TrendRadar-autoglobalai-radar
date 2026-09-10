#!/usr/bin/env python3
# coding=utf-8
"""
内容型监控 — 中国汽车行业动态结构化提取（多语言待审清单）

从 TrendRadar 当天抓取的热榜 + RSS 标题中，粗筛多品类行业信号（新车上市/销量/价格/
政策/关税/召回），用 AI 结构化提取，并翻译成 en/ru/ar/es，输出多语言待审清单。

用途：喂给 chinesecarnames（https://chinesecarnames.com）补库 + 内容订阅的**待审**数据源。
原则：只出待审清单，不自动写库——中文名/出口名仍需人工核实后才入 chinesecarnames。

输出：output/content-watch/YYYY-MM-DD.json（含多语言 translations 字段）
用法：
    uv run python scripts/extract_content_watch.py            # 提取今天
    uv run python scripts/extract_content_watch.py --days 3   # 最近 3 天
    uv run python scripts/extract_content_watch.py --dry-run  # 只粗筛，不调 AI
    uv run python scripts/extract_content_watch.py --no-translate  # 跳过翻译

环境（AI 提取用，缺失则退化为纯关键词粗筛清单）：
    AI_API_KEY / OMNI_API_KEY / OMNI_CLOUD_KEY
    AI_API_BASE / OMNI_BASE_URL / OMNI_CLOUD_URL
    AI_MODEL（默认 openai/auto/best-chat，omni 强模型；auto/fast 免费但指令遵循弱）
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from trendradar.ai.client import AIClient
from trendradar.context import AppContext
from trendradar.core import load_config
from trendradar.storage import get_storage_manager
from trendradar.utils.time import get_configured_time


# =====================================================================
# 内容类型定义（多品类行业信号）
# =====================================================================
# 每个内容类型：触发词（标题粗筛）+ 排除词 + 品牌线索（确认是汽车行业）
CONTENT_TYPES = {
    "new_launch": {
        "triggers": ["上市", "发布", "亮相", "预售", "首发", "面世", "开启预订", "开启预定",
                     "launch", "debut", "unveil", "reveal", "on sale", "pre-sale", "presale"],
        "exclude": ["财报", "业绩", "政策", "公告", "处罚", "召回", "融资", "上市标准", "上市规则",
                    "IPO", "股价", "股票", "分红", "董事会", "高管", "人事", "任命", "组织架构",
                    "芯片", "半导体", "火箭", "卫星", "游戏", "手机", "家电", "电池", "发布会口误",
                    "年终奖", "楼市", "GDP", "标准", "细则", "负面清单", "平台", "App", "小程序"],
    },
    "sales": {
        "triggers": ["销量", "销售", "交付", "交付量", "top", "榜首", "第一", "冠军", "销量榜",
                     "sales", "delivery", "deliveries", "best-selling", "top selling", "sales figure"],
        "exclude": ["财报", "业绩", "召回", "处罚", "诉讼", "裁员", "罢工"],
    },
    "price": {
        "triggers": ["降价", "涨价", "价格调整", "优惠", "折扣", "官降", "促销", "降价榜",
                     "price cut", "price drop", "discount", "price reduction", "price war"],
        "exclude": ["财报", "业绩", "召回", "处罚", "诉讼"],
    },
    "policy": {
        "triggers": ["政策", "关税", "补贴", "新规", "法规", "标准", "排放", "准入", "认证",
                     "公告", "通知", "办法", "条例", "进口关税", "反补贴", "反倾销",
                     "tariff", "policy", "regulation", "subsidy", "incentive", "emission",
                     "homologation", "certification", "anti-subsidy", "anti-dumping", "duty"],
        "exclude": ["财报", "股价", "召回"],
    },
    "recall": {
        "triggers": ["召回", "recall", "安全缺陷", "缺陷调查", "safety defect"],
        "exclude": ["财报", "股价"],
    },
    "export": {
        "triggers": ["出口", "出海", "海外市场", "进入", "登陆", "远销", "海外上市", "海外发布",
                     "export", "overseas", "entry into", "enters", "launches in", "ships to"],
        "exclude": ["财报", "股价", "召回"],
    },
}

# 品牌线索（中文 + 英文，确认是汽车行业）
BRAND_HINTS = [
    "比亚迪", "BYD", "腾势", "仰望", "方程豹", "埃安", "AION", "阿维塔", "AVATR",
    "长安", "Changan", "深蓝", "Deepal", "启源", "哈弗", "Haval", "坦克", "Tank",
    "欧拉", "ORA", "魏牌", "Wey", "长城", "GWM", "吉利", "Geely", "银河", "Galaxy",
    "几何", "Geometry", "领克", "Lynk", "极氪", "Zeekr", "奇瑞", "Chery", "星途",
    "Exeed", "捷途", "Jetour", "风云", "Fulwin", "五菱", "Wuling", "宝骏", "Baojun",
    "名爵", "MG", "荣威", "Roewe", "大通", "Maxus", "上汽", "SAIC", "智己", "IM",
    "飞凡", "Rising", "东风", "Dongfeng", "岚图", "Voyah", "猛士", "M-Hero",
    "风神", "Aeolus", "风行", "Forthing", "奕派", "纳米", "Nammi", "红旗", "Hongqi",
    "奔腾", "Bestune", "一汽", "FAW", "江淮", "JAC", "钇为", "蔚来", "NIO", "小鹏",
    "Xpeng", "理想", "Li Auto", "哪吒", "Neta", "零跑", "Leapmotor", "问界", "AITO",
    "极越", "Jiyue", "广汽", "GAC", "传祺", "Trumpchi", "昊铂", "Hyper", "合创",
    "smart", "极狐", "Arcfox", "北京汽车", "BAIC", "凯翼", "Kaiyi", "大运", "金康",
    "赛力斯", "Seres", "小米", "Xiaomi", "集度", "创维", "Skywell", "福汽", "启辰",
    "享界", "Stelato", "智界", "Luxeed", "乐道", "Onvo", "萤火虫", "Firefly",
    "捷豹路虎", "JLR", "启境", "Aistaland", "特斯拉", "Tesla", "大众", "Toyota",
    "丰田", "本田", "Honda", "日产", "Nissan", "现代", "Hyundai", "起亚", "Kia",
]

# 目标语言（复用 TrendRadar 翻译链路）
TARGET_LANGS = ["en", "ru", "ar", "es"]

EXTRACT_PROMPT = """你是中国汽车行业分析助手。下面是一些标题，可能包含行业动态信号（新车上市/销量/价格/政策/关税/召回/出海等）。

任务：对每个标题，判断是否涉及【中国汽车行业】的实质性动态（新车上市、销量数据、价格变动、政策法规、关税调整、召回、出口/出海），并提取结构化信息。

严格只输出一个 JSON 数组，不要任何解释、前言、markdown 代码块或分析文字。数组每个元素格式：

{"content_type":"new_launch|sales|price|policy|tariff|recall|export","brand_zh":"品牌中文名（无则 null）","series_zh":"车系中文名（无则 null）","title_zh":"标题（中文，保留原意）","date":"YYYY-MM-DD 或 null","key_metric":"关键数值（如销量数字/价格/关税税率，无则 null）","region":"相关地区（如 欧洲/中东/东南亚/俄罗斯/中国，无则 null）","source_title":"原标题","source_url":"原标题 URL"}

规则：
- content_type 只能是 new_launch/sales/price/policy/tariff/recall/export 之一。
- 没有实质行业动态的标题不输出。
- 不要编造标题里没有的信息。无符合则输出 []。

标题列表（每行一条）：
{items}

现在直接输出 JSON 数组："""

TRANSLATE_PROMPT = """把下面的中国汽车行业动态标题翻译成 {langs}。
规则：
- 每个标题作为一个整体翻译，不要拆字。
- 保留品牌/车型名（BYD、奇瑞、哈弗等）可识别。
- 标题要读起来像母语新闻标题，不要逐字直译。
- 输出单个 JSON 对象，键为语言代码，值为与输入等长的字符串数组。
- 不要解释，不要 markdown。

输入（JSON 数组）：
{items}

只输出 JSON："""


def norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip())


def classify(title: str) -> Optional[str]:
    """粗筛：命中某品类的触发词 + 品牌线索 + 排除词。返回内容类型或 None。"""
    t = title.lower()
    for ctype, cfg in CONTENT_TYPES.items():
        if not any(k.lower() in t for k in cfg["triggers"]):
            continue
        if any(k.lower() in t for k in cfg["exclude"]):
            continue
        if not any(b.lower() in t for b in BRAND_HINTS):
            continue
        return ctype
    return None


def collect_titles(ctx: AppContext, days: int) -> List[Dict[str, str]]:
    sm = get_storage_manager(
        backend_type=ctx.config.get("STORAGE", {}).get("BACKEND", "local"),
        data_dir=ctx.config.get("OUTPUT_DIR", "output"),
        timezone=ctx.config.get("TIMEZONE", "Asia/Shanghai"),
    )
    seen: Dict[str, Dict[str, str]] = {}
    now = get_configured_time(ctx.timezone)
    for offset in range(days):
        day = (now - timedelta(days=offset)).strftime("%Y-%m-%d")
        data = sm.get_today_all_data(day)
        if data and data.items:
            for source_id, items in data.items.items():
                for item in items:
                    t = norm_title(item.title)
                    if t and t not in seen:
                        seen[t] = {"title": t, "url": item.url or "",
                                   "source": data.id_to_name.get(source_id, source_id)}
        rss = sm.get_rss_data(day)
        if rss and rss.items:
            for feed_id, entries in rss.items.items():
                for e in entries:
                    t = norm_title(e.title)
                    if t and t not in seen:
                        seen[t] = {"title": t, "url": e.url or "",
                                   "source": rss.id_to_name.get(feed_id, feed_id)}
    return list(seen.values())


def parse_json_array(raw: str) -> List[Dict[str, Any]]:
    """提取 JSON 数组（容忍 markdown 围栏/前后语/截断）。"""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("[")
    if start < 0:
        return []
    json_str = raw[start:]
    m = re.search(r"\[[\s\S]*\]", json_str)
    if m:
        try:
            parsed = json.loads(m.group(0))
            if isinstance(parsed, list):
                return [p for p in parsed if isinstance(p, dict)]
        except json.JSONDecodeError:
            pass
    # 截断兜底：丢弃不完整尾部对象
    positions = [i for i in range(len(json_str)) if json_str.startswith("},", i)]
    for pos in reversed(positions):
        candidate = json_str[: pos + 1] + "]"
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, list):
                return [p for p in parsed if isinstance(p, dict)]
        except json.JSONDecodeError:
            continue
    return []


def ai_extract(client: AIClient, items: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    if not items:
        return []
    lines = "\n".join(f"{i+1}. {it['title']} | {it['url']}" for i, it in enumerate(items))
    prompt = EXTRACT_PROMPT.replace("{items}", lines)
    try:
        # ⚠️ omni 网关对 temperature=0.0 返回安全拦截，必须用 1.0
        raw = client.chat(
            [
                {"role": "system", "content": "你是中国汽车行业分析助手。你只输出一个合法的 JSON 数组，绝不输出解释、前言、代码块标记或任何非 JSON 文本。"},
                {"role": "user", "content": prompt},
            ],
            temperature=1.0,
            max_tokens=8000,
        )
    except Exception as e:
        print(f"[内容监控] AI 提取失败: {e}")
        return []
    return parse_json_array(raw)


def ai_translate(client: AIClient, titles: List[str]) -> Dict[str, List[str]]:
    """复用 TrendRadar 翻译链路：把中文标题翻译成 en/ru/ar/es。"""
    if not titles:
        return {lang: [] for lang in TARGET_LANGS}
    langs = ", ".join(TARGET_LANGS)
    prompt = TRANSLATE_PROMPT.replace("{langs}", langs).replace("{items}", json.dumps(titles, ensure_ascii=False))
    try:
        raw = client.chat(
            [
                {"role": "system", "content": "你是专业的汽车行业翻译。只输出合法 JSON，不解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=1.0,
            max_tokens=6000,
        )
    except Exception as e:
        print(f"[内容监控] 翻译失败: {e}")
        return {lang: [] for lang in TARGET_LANGS}
    # 提取 JSON 对象
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    if start < 0:
        return {lang: [] for lang in TARGET_LANGS}
    json_str = raw[start:]
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError:
        # 截断兜底：找最后一个完整 ",\n" 边界
        last = json_str.rfind("\",")
        if last > 0:
            json_str = json_str[: last + 1] + "}"
            try:
                parsed = json.loads(json_str)
            except json.JSONDecodeError:
                return {lang: [] for lang in TARGET_LANGS}
        else:
            return {lang: [] for lang in TARGET_LANGS}
    if not isinstance(parsed, dict):
        return {lang: [] for lang in TARGET_LANGS}
    out = {}
    for lang in TARGET_LANGS:
        val = parsed.get(lang)
        if isinstance(val, list) and len(val) == len(titles):
            out[lang] = [str(v) for v in val]
        else:
            out[lang] = titles[:]  # 回退到中文原文
    return out


def main() -> None:
    args = sys.argv[1:]
    days = 1
    dry_run = "--dry-run" in args
    no_translate = "--no-translate" in args
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            try:
                days = max(1, int(args[i + 1]))
            except ValueError:
                pass

    config = load_config()
    ctx = AppContext(config)

    all_titles = collect_titles(ctx, days)
    print(f"[内容监控] 最近 {days} 天共 {len(all_titles)} 条去重标题")

    # 粗筛：多品类
    by_type: Dict[str, List[Dict[str, str]]] = {}
    for it in all_titles:
        ctype = classify(it["title"])
        if ctype:
            by_type.setdefault(ctype, []).append({**it, "content_type": ctype})
    candidates = [it for lst in by_type.values() for it in lst]
    print(f"[内容监控] 粗筛命中 {len(candidates)} 条（分品类: { {k: len(v) for k, v in by_type.items()} }）")

    result: Dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "days": days,
        "total_titles": len(all_titles),
        "candidate_count": len(candidates),
        "by_type": {k: len(v) for k, v in by_type.items()},
        "candidates": candidates,
        "launches": [],
        "translations": {},
        "ai_extracted": False,
    }

    if not dry_run and candidates:
        ai_config = ctx.config.get("AI", {})
        ai_config = dict(ai_config)
        ai_config["MODEL"] = os.environ.get("CONTENT_WATCH_MODEL", os.environ.get("NEW_CAR_MODEL", "openai/auto/best-chat"))
        client = AIClient(ai_config)
        ok, err = client.validate_config()
        if ok:
            launches = ai_extract(client, candidates)
            result["launches"] = launches
            result["ai_extracted"] = True
            print(f"[内容监控] AI 提取出 {len(launches)} 条结构化记录")
            for la in launches:
                print(f"  - [{la.get('content_type','')}] {la.get('brand_zh') or ''} {la.get('series_zh') or ''} | {la.get('title_zh','')[:50]}")
            # 多语言翻译
            if not no_translate and launches:
                titles_zh = [la.get("title_zh") or la.get("source_title", "") for la in launches]
                print(f"[内容监控] 翻译 {len(titles_zh)} 条到 {TARGET_LANGS} ...")
                result["translations"] = ai_translate(client, titles_zh)
                for lang in TARGET_LANGS:
                    print(f"  - {lang}: {len(result['translations'].get(lang, []))} 条")
        else:
            print(f"[内容监控] AI 未配置（{err}），仅输出粗筛清单")

    now = get_configured_time(ctx.timezone)
    date_str = now.strftime("%Y-%m-%d")
    out_dir = Path(ctx.config.get("OUTPUT_DIR", "output")) / "content-watch"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{date_str}.json"
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[内容监控] 待审清单已写入 {out_file}")


if __name__ == "__main__":
    main()
