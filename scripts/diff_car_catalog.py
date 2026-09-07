#!/usr/bin/env python3
# coding=utf-8
"""
车型库 diff — 新车上市检测（方案 D）

对比「汽车之家/懂车帝配置库」的两次快照，找出新增车系 = 新车上市。

用途：产出 chinesecarnames 补库的**结构化待审清单**。比 RSS 新闻更权威、更全
（不漏任何一款国内上市的车，无论是否有海外关注度）。

输入：两份 car-api-cache.json 格式的快照（93 品牌 × N 车系）：
  [{ "brandId": "...", "brandName": "比亚迪", "series": [{"seriesId":"...","seriesName":"海豹06"}] }]

用法：
    uv run python scripts/diff_car_catalog.py --old baseline.json --new latest.json
    uv run python scripts/diff_car_catalog.py --old baseline.json --new latest.json --out new-launches.json

输出 JSON：
  {
    "baseline_brands": N, "baseline_series": N,
    "latest_brands": N, "latest_series": N,
    "new_brands": [{...}],
    "new_series": [{brand_zh, brandId, seriesId, seriesName, brandName}],
  }

规则：
  - 车系唯一键 = seriesId（主站 car_models 的 primary key），其次 brandName+seriesName
  - 新增品牌 = latest 有 baseline 无的 brandId
  - 新增车系 = latest 有 baseline 无的 seriesId（含 brandId 变化导致的）
"""

import argparse
import json
import sys
from typing import Any, Dict, List


def load(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} 不是预期的品牌数组格式")
    return data


def series_key(brand: Dict[str, Any], series: Dict[str, Any]) -> tuple:
    return (str(series.get("seriesId", "")), str(brand.get("brandName", "")), str(series.get("seriesName", "")))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--old", required=True, help="基线快照（旧）car-api-cache.json")
    p.add_argument("--new", required=True, help="最新快照 car-api-cache.json")
    p.add_argument("--out", default=None, help="输出 JSON 路径（默认打印到 stdout）")
    args = p.parse_args()

    old = load(args.old)
    new = load(args.new)

    old_brand_ids = {str(b["brandId"]) for b in old}
    new_brand_ids = {str(b["brandId"]) for b in new}

    old_series_ids = {
        str(s.get("seriesId", ""))
        for b in old
        for s in b.get("series", [])
        if s.get("seriesId")
    }
    new_series_ids = {
        str(s.get("seriesId", ""))
        for b in new
        for s in b.get("series", [])
        if s.get("seriesId")
    }

    new_brands = [b for b in new if str(b["brandId"]) not in old_brand_ids]
    new_series = []
    for b in new:
        for s in b.get("series", []):
            if not s.get("seriesId"):
                continue
            if str(s["seriesId"]) not in old_series_ids:
                new_series.append({
                    "brand_zh": b.get("brandName", ""),
                    "brandId": b.get("brandId", ""),
                    "seriesId": s.get("seriesId", ""),
                    "series_zh": s.get("seriesName", ""),
                })

    result = {
        "baseline_brands": len(old),
        "baseline_series": len(old_series_ids),
        "latest_brands": len(new),
        "latest_series": len(new_series_ids),
        "new_brands": new_brands,
        "new_series": new_series,
    }

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"[车型库 diff] 新增品牌 {len(new_brands)}，新增车系 {len(new_series)}，已写入 {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
