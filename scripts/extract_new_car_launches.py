#!/usr/bin/env python3
# coding=utf-8
"""
新车上市监控 — 结构化提取待审清单

从 TrendRadar 当天抓取的热榜 + RSS 标题中，粗筛「新车上市/发布/亮相/预售」信号，
用 AI 结构化提取 {品牌中文名, 车系中文名, 上市时间, 动力类型, 来源}，输出 JSON 待审清单。

用途：喂给 chinesecarnames（https://chinesecarnames.com）补库的**待审**数据源。
原则：只出待审清单，不自动写库——中文名/出口名仍需人工核实后才入 chinesecarnames。

输出：output/new-car-launches/YYYY-MM-DD.json
用法：
    uv run python scripts/extract_new_car_launches.py            # 提取今天
    uv run python scripts/extract_new_car_launches.py --days 3   # 最近 3 天
    uv run python scripts/extract_new_car_launches.py --dry-run  # 只粗筛，不调 AI

环境（可选，AI 提取用，缺失则退化为纯关键词粗筛清单）：
    AI_API_KEY / OMNI_API_KEY / OMNI_CLOUD_KEY
    AI_API_BASE / OMNI_BASE_URL / OMNI_CLOUD_URL
    AI_MODEL
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# 把仓库根加入路径，确保能 import trendradar
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from trendradar.ai.client import AIClient
from trendradar.context import AppContext
from trendradar.core import load_config
from trendradar.storage import get_storage_manager
from trendradar.utils.time import get_configured_time


# =====================================================================
# 新车上市信号关键词（标题粗筛）
# =====================================================================
# 触发词：上市/发布/亮相/预售/首发/上市预售（标题含这些 + 疑似车型名）
LAUNCH_TRIGGERS = [
    "上市", "发布", "亮相", "预售", "首发", "面世", "开启预订", "开启预定",
    "launch", "debut", "unveil", "reveal", "on sale", "pre-sale", "presale",
]

# 明确非车型的排除（避免「某政策发布」「某财报发布」误命中）
LAUNCH_EXCLUDE = [
    "财报", "业绩", "政策", "公告", "处罚", "召回", "融资", "上市标准", "上市规则",
    "IPO", "股价", "股票", "分红", "董事会", "高管", "人事", "任命", "组织架构",
    "芯片", "半导体", "火箭", "卫星", "游戏", "手机", "家电", "电池", "发布会口误",
    "年终奖", "楼市", "GDP", "标准", "细则", "负面清单", "平台", "App", "小程序",
]

# 品牌线索（中文 + 英文，用于确认标题确实涉及车型，而非泛泛「新车上市」）
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
]

# 非新车上市、但标题里带品牌+触发词也可能误中，需要更严格的「上市信号」判定
LAUNCH_PATTERN = re.compile(
    r"(新款|全新|新一代|改款|换代|年度改款|新增|202\d{1}|2026|2025|2027)?"
    r".{0,6}(上市|发布|亮相|预售|首发|开启预订)"
)

EXTRACT_PROMPT = """你是中国汽车行业分析助手。下面是一些标题，其中可能包含「新车上市/发布/亮相/预售」信号。

请对每个标题判断：它是否涉及【具体某个车型】的上市/发布/亮相/预售（而非品牌、政策、财报、召回等）。

对每个符合条件的标题，提取结构化信息，输出 JSON 数组（无符合则输出 []）：

[
  {
    "brand_zh": "品牌中文名（如 比亚迪/吉利/奇瑞；纯英文品牌则填英文）",
    "series_zh": "车系中文名（如 海豹06/星舰7/风云A8；无中文名填英文系列名）",
    "launch_date": "上市/发布日期 YYYY-MM-DD（标题未明示则填 null）",
    "powertrain": "EV/PHEV/EREV/ICE/未知（标题未明示填 未知）",
    "body_type": "SUV/sedan/hatchback/MPV/pickup/未知",
    "source_title": "原标题",
    "source_url": "原标题 URL（无则空字符串）"
  }
]

规则：
- 只提取【车型】上市信号，品牌/子品牌整体战略、单款配置、颜色、价格调整不算。
- 概念车、未量产的车也提取，但 powertrain/body_type 填「未知」。
- 中文名优先，保留数字/字母后缀（如「海豹06 DM-i」「风云A8」）。
- 不要编造标题里没有的信息。

标题列表（每行一条）：
{items}
"""


def norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip())


def rough_filter(title: str) -> bool:
    """关键词粗筛：命中触发词 + 品牌线索 + 排除词，且不是纯公司/政策类。"""
    t = title or ""
    if not any(k.lower() in t.lower() for k in LAUNCH_TRIGGERS):
        return False
    if any(k.lower() in t.lower() for k in LAUNCH_EXCLUDE):
        return False
    if not any(b.lower() in t.lower() for b in BRAND_HINTS):
        return False
    return True


def collect_titles(ctx: AppContext, days: int) -> List[Dict[str, str]]:
    """从 TrendRadar 存储收集最近 N 天热榜 + RSS 标题（去重）。"""
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
                        seen[t] = {
                            "title": t,
                            "url": item.url or "",
                            "source": data.id_to_name.get(source_id, source_id),
                        }
        rss = sm.get_rss_data(day)
        if rss and rss.items:
            for feed_id, entries in rss.items.items():
                for e in entries:
                    t = norm_title(e.title)
                    if t and t not in seen:
                        seen[t] = {
                            "title": t,
                            "url": e.url or "",
                            "source": rss.id_to_name.get(feed_id, feed_id),
                        }
    return list(seen.values())


def ai_extract(client: AIClient, items: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """用 AI 结构化提取车型信息。失败返回 []。"""
    if not items:
        return []
    lines = "\n".join(f"{i+1}. {it['title']} | {it['url']}" for i, it in enumerate(items))
    prompt = EXTRACT_PROMPT.format(items=lines)
    try:
        raw = client.chat(
            [
                {"role": "system", "content": "你是中国汽车行业分析助手，只输出 JSON，不输出任何解释。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=4000,
        )
    except Exception as e:
        print(f"[新车监控] AI 提取失败: {e}")
        return []

    # 提取 JSON（容忍模型多输出 markdown 代码块/前缀）
    m = re.search(r"\[[\s\S]*\]", raw)
    if not m:
        print(f"[新车监控] AI 未返回 JSON 数组，原始片段: {raw[:200]}")
        return []
    try:
        parsed = json.loads(m.group(0))
        if not isinstance(parsed, list):
            return []
        return [p for p in parsed if isinstance(p, dict) and p.get("series_zh")]
    except json.JSONDecodeError as e:
        print(f"[新车监控] JSON 解析失败: {e}")
        return []


def main() -> None:
    args = sys.argv[1:]
    days = 1
    dry_run = "--dry-run" in args
    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            try:
                days = max(1, int(args[i + 1]))
            except ValueError:
                pass

    config = load_config()
    ctx = AppContext(config)

    all_titles = collect_titles(ctx, days)
    print(f"[新车监控] 最近 {days} 天共 {len(all_titles)} 条去重标题")

    candidates = [it for it in all_titles if rough_filter(it["title"])]
    print(f"[新车监控] 粗筛命中 {len(candidates)} 条疑似新车上市信号")

    result: Dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "days": days,
        "total_titles": len(all_titles),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "launches": [],
        "ai_extracted": False,
    }

    if not dry_run and candidates:
        ai_config = ctx.config.get("AI", {})
        client = AIClient(ai_config)
        ok, err = client.validate_config()
        if ok:
            launches = ai_extract(client, candidates)
            result["launches"] = launches
            result["ai_extracted"] = True
            print(f"[新车监控] AI 提取出 {len(launches)} 条车型上市记录")
        else:
            print(f"[新车监控] AI 未配置（{err}），仅输出粗筛清单")

    # 输出待审清单
    now = get_configured_time(ctx.timezone)
    date_str = now.strftime("%Y-%m-%d")
    out_dir = Path(ctx.config.get("OUTPUT_DIR", "output")) / "new-car-launches"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{date_str}.json"
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[新车监控] 待审清单已写入 {out_file}")


if __name__ == "__main__":
    main()
