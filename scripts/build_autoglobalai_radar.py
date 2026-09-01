#!/usr/bin/env python3
# coding=utf-8
"""
AutoGlobalAI 多语言行业雷达站点生成器

输入：TrendRadar 抓取并存储的热榜/RSS 数据（本地 SQLite）
输出：6 语言静态站点，输出到 output/site/<lang>/，可直接部署到 Cloudflare Pages

用法：
    uv run python scripts/build_autoglobalai_radar.py
"""

import json
import os
import re
import sys
import concurrent.futures
from collections import defaultdict
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 把仓库根目录加入路径，确保能 import trendradar
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from trendradar.ai.client import AIClient
from trendradar.context import AppContext
from trendradar.core import load_config
from trendradar.storage import get_storage_manager


# ═══════════════════════════════════════════════════════════════
# 配置常量
# ═══════════════════════════════════════════════════════════════

LANGUAGES: List[Dict[str, str]] = [
    {"code": "en",    "name": "English",    "dir": "ltr", "locale": "en-US"},
    {"code": "ru",    "name": "Русский",    "dir": "ltr", "locale": "ru-RU"},
    {"code": "ar",    "name": "العربية",    "dir": "rtl", "locale": "ar-SA"},
    {"code": "es",    "name": "Español",    "dir": "ltr", "locale": "es-ES"},
    {"code": "fa",    "name": "فارسی",      "dir": "rtl", "locale": "fa-IR"},
    {"code": "pt",    "name": "Português",  "dir": "ltr", "locale": "pt-BR"},
]

# 本地化固定文案
I18N: Dict[str, Dict[str, str]] = {
    "site_name": {
        "en": "AutoGlobalAI Industry Radar",
        "ru": "Отраслевой радар AutoGlobalAI",
        "ar": "رادار صناعة AutoGlobalAI",
        "es": "Radar Industrial AutoGlobalAI",
        "fa": "رادار صنعت AutoGlobalAI",
        "pt": "Radar Industrial AutoGlobalAI",
    },
    "site_subtitle": {
        "en": "Daily intelligence on Chinese auto export signals",
        "ru": "Ежедневная аналитика сигналов китайского автомобильного экспорта",
        "ar": "ذكاء يومي حول إشارات تصدير السيارات الصينية",
        "es": "Inteligencia diaria sobre señales de exportación de autos chinos",
        "fa": "اطلاعات روزانه درباره سیگنال‌های صادرات خودروی چینی",
        "pt": "Inteligência diária sobre sinais de exportação de carros chineses",
    },
    "cta_title": {
        "en": "Looking for sourcing intelligence and verified suppliers?",
        "ru": "Ищете данные по поставкам и проверенных поставщиков?",
        "ar": "هل تبحث عن معلومات التوريد والموردين الموثوقين؟",
        "es": "¿Buscas inteligencia de abastecimiento y proveedores verificados?",
        "fa": "به دنبال اطلاعات تأمین و تأمین‌کنندگان تأییدشده هستید؟",
        "pt": "Procurando inteligência de sourcing e fornecedores verificados?",
    },
    "cta_button": {
        "en": "Visit AutoGlobalAI",
        "ru": "Посетить AutoGlobalAI",
        "ar": "زيارة AutoGlobalAI",
        "es": "Visitar AutoGlobalAI",
        "fa": "مشاهده AutoGlobalAI",
        "pt": "Visitar AutoGlobalAI",
    },
    "cta_body": {
        "en": "Track real-time pricing, factory capacity, MOQ and export-ready stock across Chinese auto brands.",
        "ru": "Отслеживайте цены, производственные мощности, минимальные партии и экспортные запасы китайских автомобильных брендов в реальном времени.",
        "ar": "تتبع الأسعار لحظية والقدرة الإنتاجية للمصانع وحدات الطلب الأدنى والمخزون الجاهز للتصدير عبر العلامات التجارية الصينية.",
        "es": "Rastrea precios en tiempo real, capacidad de fábrica, MOQ e inventario listo para exportar de marcas de autos chinos.",
        "fa": "قیمت‌ها، ظرفیت کارخانه، حداقل سفارش و موجودی آماده صادرات برندهای خودروی چینی را در لحظه رصد کنید.",
        "pt": "Acompanhe preços em tempo real, capacidade de fábrica, MOQ e estoque pronto para exportação de marcas chinesas.",
    },
    "footer_copyright": {
        "en": "© AutoGlobalAI. Intelligence for global automotive sourcing.",
        "ru": "© AutoGlobalAI. Интеллект для глобального автомобильного снабжения.",
        "ar": "© AutoGlobalAI. ذكاء لتوريد السيارات العالمي.",
        "es": "© AutoGlobalAI. Inteligencia para el abastecimiento automotriz global.",
        "fa": "© AutoGlobalAI. اطلاعات برای تأمین جهانی خودرو.",
        "pt": "© AutoGlobalAI. Inteligência para sourcing automotivo global.",
    },
    "generated_at": {
        "en": "Generated at",
        "ru": "Сгенерировано в",
        "ar": "تم الإنشاء في",
        "es": "Generado a las",
        "fa": "تولید شده در",
        "pt": "Gerado em",
    },
    "keyword_ranking": {
        "en": "Keyword Radar",
        "ru": "Радар по ключевым словам",
        "ar": "رادار الكلمات المفتاحية",
        "es": "Radar de palabras clave",
        "fa": "رادار کلمات کلیدی",
        "pt": "Radar de palavras-chave",
    },
    "sources": {
        "en": "sources",
        "ru": "источников",
        "ar": "مصدر",
        "es": "fuentes",
        "fa": "منبع",
        "pt": "fontes",
    },
    "mentions": {
        "en": "mentions",
        "ru": "упоминаний",
        "ar": "إشارة",
        "es": "menciones",
        "fa": "اشاره",
        "pt": "menções",
    },
    "no_data": {
        "en": "No matching signals today. Check back soon.",
        "ru": "Сегодня совпадающих сигналов нет. Загляните позже.",
        "ar": "لا توجد إشارات مطابقة اليوم. أعد التحقق قريبًا.",
        "es": "No hay señales coincidentes hoy. Vuelve pronto.",
        "fa": "امروز سیگنال مطابقی وجود ندارد. به زودی برگردید.",
        "pt": "Nenhum sinal correspondente hoje. Volte em breve.",
    },
    "subscribe_title": {
        "en": "Get the daily radar in your inbox",
        "ru": "Получайте ежедневный радар на почту",
        "ar": "احصل على الرادار اليومي في بريدك",
        "es": "Recibe el radar diario en tu correo",
        "fa": "رادار روزانه را در ایمیل خود دریافت کنید",
        "pt": "Receba o radar diário no seu e-mail",
    },
    "subscribe_body": {
        "en": "One email per day with the top Chinese auto export signals. No spam, unsubscribe anytime.",
        "ru": "Одно письмо в день с главными сигналами автомобильного экспорта Китая. Без спама, отписка в любой момент.",
        "ar": "رسالة واحدة يوميًا بأهم إشارات تصدير السيارات الصينية. بدون بريد مزعج، ويمكنك إلغاء الاشتراك في أي وقت.",
        "es": "Un correo al día con las principales señales de exportación de autos chinos. Sin spam, cancela cuando quieras.",
        "fa": "یک ایمیل در روز با مهم‌ترین سیگنال‌های صادرات خودروی چین. بدون هرزنامه، لغو اشتراک در هر زمان.",
        "pt": "Um e-mail por dia com os principais sinais de exportação de automóveis chineses. Sem spam, cancele quando quiser.",
    },
    "subscribe_placeholder": {
        "en": "Work email",
        "ru": "Рабочая почта",
        "ar": "البريد الإلكتروني للعمل",
        "es": "Correo de trabajo",
        "fa": "ایمیل کاری",
        "pt": "E-mail de trabalho",
    },
    "subscribe_button": {
        "en": "Subscribe",
        "ru": "Подписаться",
        "ar": "اشترك",
        "es": "Suscribirse",
        "fa": "اشتراک",
        "pt": "Assinar",
    },
    "subscribe_success": {
        "en": "Subscribed. You'll get the next daily radar.",
        "ru": "Готово. Вы получите следующий ежедневный радар.",
        "ar": "تم الاشتراك. ستصلك النسخة اليومية القادمة.",
        "es": "Listo. Recibirás el próximo radar diario.",
        "fa": "ثبت شد. رادار روزانه بعدی را دریافت خواهید کرد.",
        "pt": "Inscrito. Você receberá o próximo radar diário.",
    },
    "subscribe_error": {
        "en": "Something went wrong. Please try again later.",
        "ru": "Что-то пошло не так. Попробуйте позже.",
        "ar": "حدث خطأ ما. حاول مرة أخرى لاحقًا.",
        "es": "Algo salió mal. Inténtalo de nuevo más tarde.",
        "fa": "مشکلی پیش آمد. لطفاً بعداً دوباره تلاش کنید.",
        "pt": "Algo deu errado. Tente novamente mais tarde.",
    },
}

AUTO_EXPORT_KEYWORDS: List[str] = []


def load_frequency_groups(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """加载 frequency_words.txt，保留 TrendRadar 原生词组语义。

    返回 (groups, global_filter)：
    - groups: [{"name", "required": [...], "normal": [...], "filter": [...]}]
      `+词` = 必须全部命中（AND）；`!词` = 命中即排除；其余 = 任一命中（OR）
    - global_filter: [GLOBAL_FILTER] 区的词，标题命中即整条排除
    """
    groups: List[Dict[str, Any]] = []
    global_filter: List[str] = []
    if not path.exists():
        return groups, global_filter
    current: Dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            name = stripped[1:-1].strip()
            if name == "GLOBAL_FILTER":
                current = None
            else:
                current = {"name": name, "required": [], "normal": [], "filter": []}
                groups.append(current)
            continue
        if "=>" in stripped:
            stripped = stripped.split("=>")[0].strip()
        if stripped.startswith("/") and stripped.endswith("/"):
            stripped = stripped[1:-1]
        if not stripped:
            continue
        # 过滤纯单字母噪声词（不过滤中文单字，如 +车）
        if len(stripped.lstrip("+!")) == 1 and stripped.lstrip("+!").isalpha() and stripped.lstrip("+!").isascii():
            continue
        if current is None:
            # [GLOBAL_FILTER] 区：不进词组，作为全局排除词
            global_filter.append(stripped.lstrip("+!"))
            continue
        if stripped.startswith("+"):
            current["required"].append(stripped[1:])
        elif stripped.startswith("!"):
            current["filter"].append(stripped[1:])
        else:
            current["normal"].append(stripped)
    return groups, global_filter


def extract_items(ctx: AppContext) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    从 TrendRadar 存储中提取当天热榜与 RSS 条目
    """
    sm = get_storage_manager(
        backend_type=ctx.config.get("STORAGE", {}).get("BACKEND", "local"),
        data_dir=ctx.config.get("OUTPUT_DIR", "output"),
        timezone=ctx.config.get("TIMEZONE", "Asia/Shanghai"),
    )

    hotlist_items: List[Dict[str, Any]] = []
    rss_items: List[Dict[str, Any]] = []

    today_data = sm.get_today_all_data()
    if today_data and today_data.items:
        for source_id, items_list in today_data.items.items():
            source_name = today_data.id_to_name.get(source_id, source_id)
            for item in items_list:
                hotlist_items.append({
                    "title": item.title,
                    "source_name": source_name,
                    "source_id": source_id,
                    "url": item.url or "",
                    "rank": item.rank,
                    "last_time": item.last_time,
                    "count": item.count,
                })

    from trendradar.utils.time import get_configured_time
    now = get_configured_time(ctx.timezone)
    date_str = now.strftime("%Y-%m-%d")
    rss_data = sm.get_rss_data(date_str)
    if rss_data and rss_data.items:
        for feed_id, entries in rss_data.items.items():
            feed_name = rss_data.id_to_name.get(feed_id, feed_id)
            for entry in entries:
                rss_items.append({
                    "title": entry.title,
                    "source_name": feed_name,
                    "source_id": feed_id,
                    "url": entry.url,
                    "published_at": entry.published_at,
                    "summary": entry.summary,
                })

    return hotlist_items, rss_items


def group_items_by_keyword(
    items: List[Dict[str, Any]],
    groups: List[Dict[str, Any]],
    global_filter: List[str],
    max_items_per_group: int = 20,
) -> Dict[str, List[Dict[str, Any]]]:
    """按词组语义对条目分组（required AND + normal OR + filter 排除 + 全局排除）"""
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    seen_titles: set = set()

    for item in items:
        title = item["title"]
        # 全局排除（标题党/无关内容）
        if any(f and f in title for f in global_filter):
            continue
        matched: List[str] = []
        for group in groups:
            # 组内排除词
            if any(f and f in title for f in group["filter"]):
                continue
            # required 全部命中才算候选
            if group["required"] and not all(r and r in title for r in group["required"]):
                continue
            for kw in group["normal"]:
                if kw and kw in title:
                    matched.append(kw)
        if not matched:
            continue

        # 每个关键词都算一次命中
        for kw in matched:
            key = (kw, title)
            if key not in seen_titles:
                seen_titles.add(key)
                out[kw].append(item)

    # 排序：按 count 降序，然后 rank 升序
    for kw in out:
        out[kw].sort(key=lambda x: (-x.get("count", 1), x.get("rank", 999)))
        out[kw] = out[kw][:max_items_per_group]

    # 按组大小排序
    return dict(sorted(out.items(), key=lambda x: (-len(x[1]), x[0])))


def build_translation_payload(
    keyword_groups: Dict[str, List[Dict[str, Any]]],
    max_keywords: int = 30,
    max_titles: int = 50,
) -> Tuple[List[str], Dict[str, Any]]:
    """
    构造需要翻译的文本列表（关键词 + 新闻标题，用于 6 语言雷达）
    """
    texts: List[str] = []
    meta: Dict[str, Any] = {"keywords": {}, "titles": {}}

    for kw in list(keyword_groups.keys())[:max_keywords]:
        meta["keywords"][kw] = len(texts)
        texts.append(kw)

    # 唯一标题：按词组顺序（大组优先、组内已按热度排序）取前 max_titles 条
    seen: set = set()
    for items in keyword_groups.values():
        for item in items:
            t = item["title"]
            if t in seen:
                continue
            seen.add(t)
            if len(meta["titles"]) >= max_titles:
                break
            meta["titles"][t] = len(texts)
            texts.append(t)
        if len(meta["titles"]) >= max_titles:
            break

    return texts, meta


def translate_to_all_languages(
    texts: List[str],
    ai_config: Dict[str, Any],
    target_langs: List[str],
) -> Dict[str, List[str]]:
    """
    使用 omni.paibao.ai 将关键词一次性翻译为 6 种语言
    返回 {lang_code: [translated_texts]}
    """
    if not texts:
        return {lang["code"]: [] for lang in LANGUAGES}

    # 调低单次超时，避免 CI 卡住
    config = dict(ai_config)
    config["TIMEOUT"] = min(config.get("TIMEOUT", 120), 90)
    client = AIClient(config)
    if not client.api_key:
        print("[翻译] 未配置 AI API Key，无法翻译")
        return {lang["code"]: [] for lang in LANGUAGES}

    lang_list = ", ".join(target_langs)
    prompt = f"""Translate each Chinese text (automotive industry keyword or news headline) into {lang_list}.
Rules:
- Treat each text as a single unit; do not split into individual characters.
- Keep brand/model names (BYD, Chery, Haval, 比亚迪, 奇瑞) recognizable.
- Preserve automotive terms in their commonly accepted local form.
- Headlines must read as natural native news headlines, not word-by-word translation.
- Output a single JSON object with language codes as keys and arrays of translated strings in the same order as the input.
- Each array must contain exactly {len(texts)} strings. No explanations.

Example input: ["比亚迪出口", "俄罗斯市场"]
Example output:
{{"en": ["BYD exports", "Russian market"], "ru": ["экспорт BYD", "российский рынок"], ...}}

Input:
{json.dumps(texts, ensure_ascii=False, indent=2)}

Output JSON only:"""

    for attempt in range(client.num_retries + 1):
        try:
            response = client.chat([
                {"role": "system", "content": "You are a professional automotive industry translator. Output valid JSON only."},
                {"role": "user", "content": prompt},
            ])
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("\n", 1)[0]
            cleaned = cleaned.strip()

            translations = json.loads(cleaned)
            if not isinstance(translations, dict):
                raise ValueError("Response is not a JSON object")

            for lang in LANGUAGES:
                code = lang["code"]
                if code not in translations or not isinstance(translations[code], list):
                    translations[code] = texts[:]
                    continue
                # 长度不一致时回退到原文
                if len(translations[code]) != len(texts):
                    print(f"[翻译] 警告: {code} 翻译数量不匹配 ({len(translations[code])} vs {len(texts)})，回退")
                    translations[code] = texts[:]

            return translations
        except Exception as e:
            print(f"[翻译] 第 {attempt + 1} 次失败: {e}")
            if attempt == client.num_retries:
                raise

    return {lang["code"]: [] for lang in LANGUAGES}


def build_translated_groups(
    keyword_groups: Dict[str, List[Dict[str, Any]]],
    translations: Dict[str, List[str]],
    meta: Dict[str, Any],
) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """
    翻译关键词标题 + 新闻标题（title_t），原文保留在 title
    """
    lang_groups: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    def translated_title(texts: List[str], title: str) -> str:
        idx = meta.get("titles", {}).get(title)
        if idx is None or idx >= len(texts):
            return title
        return texts[idx] or title

    for lang in LANGUAGES:
        code = lang["code"]
        translated_texts = translations.get(code, [])
        if not translated_texts:
            lang_groups[code] = keyword_groups
            continue

        lang_groups[code] = {}
        for kw, items in keyword_groups.items():
            kw_index = meta["keywords"].get(kw)
            if kw_index is None or kw_index >= len(translated_texts):
                translated_kw = kw
            else:
                translated_kw = translated_texts[kw_index]
            lang_groups[code][translated_kw] = [
                {**item, "title_t": translated_title(translated_texts, item["title"])}
                for item in items
            ]

    return lang_groups


def html_escape(s: str) -> str:
    """HTML 转义"""
    return (s
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def build_page(
    lang: Dict[str, str],
    groups: Dict[str, List[Dict[str, Any]]],
    all_langs: List[Dict[str, str]],
    canonical_url: str,
    site_host: str,
    generated_at: str,
) -> str:
    """
    生成单个语言的 HTML 页面
    """
    code = lang["code"]
    direction = lang["dir"]
    locale = lang["locale"]
    site_name = I18N["site_name"][code]
    site_subtitle = I18N["site_subtitle"][code]

    # hreflang 链路
    hreflang_links = []
    for l in all_langs:
        href = f"{site_host}/{l['code']}/"
        if l["code"] == "en":
            hreflang_links.append(f'<link rel="alternate" hreflang="x-default" href="{html_escape(href)}" />')
        hreflang_links.append(f'<link rel="alternate" hreflang="{l["locale"]}" href="{html_escape(href)}" />')

    # JSON-LD
    jsonld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": site_name,
        "url": canonical_url,
        "inLanguage": locale,
        "description": site_subtitle,
        "publisher": {
            "@type": "Organization",
            "name": "AutoGlobalAI",
            "url": "https://www.autoglobalai.com",
            "logo": "https://www.autoglobalai.com/logo.png",
        },
    }

    # 语言切换器
    lang_switcher_items = []
    for l in all_langs:
        active = " active" if l["code"] == code else ""
        label = l["name"]
        lang_switcher_items.append(
            f'<a class="lang-link{active}" href="{site_host}/{l["code"]}/" hreflang="{l["locale"]}">{html_escape(label)}</a>'
        )
    lang_switcher = " · ".join(lang_switcher_items)

    # CTA
    cta_title = I18N["cta_title"][code]
    cta_body = I18N["cta_body"][code]
    cta_button = I18N["cta_button"][code]

    # 内容区
    keyword_ranking_title = I18N["keyword_ranking"][code]
    sources_label = I18N["sources"][code]
    mentions_label = I18N["mentions"][code]

    sections_html = []
    if not groups:
        sections_html.append(f'<p class="no-data">{html_escape(I18N["no_data"][code])}</p>')
    else:
        for keyword, items in list(groups.items())[:30]:
            item_rows = []
            for item in items[:10]:
                title = html_escape(item.get("title_t") or item["title"])
                original = html_escape(item["title"])
                source = html_escape(item.get("source_name", ""))
                rank = item.get("rank", 0)
                url = html_escape(item.get("url", ""))
                rank_badge = f'<span class="rank">#{rank}</span>' if rank else ""
                if url:
                    item_rows.append(
                        f'<li>{rank_badge}<a href="{url}" target="_blank" rel="noopener noreferrer" title="{original}">{title}</a> <span class="source">{source}</span></li>'
                    )
                else:
                    item_rows.append(
                        f'<li>{rank_badge}<span class="title" title="{original}">{title}</span> <span class="source">{source}</span></li>'
                    )

            count = len(items)
            sections_html.append(
                f"""<section class="keyword-section">
                    <h2>{html_escape(keyword)}</h2>
                    <p class="meta">{count} {mentions_label}</p>
                    <ol>{''.join(item_rows)}</ol>
                </section>"""
            )

    # 订阅区
    sub_title = I18N["subscribe_title"][code]
    sub_body = I18N["subscribe_body"][code]
    sub_placeholder = I18N["subscribe_placeholder"][code]
    sub_button = I18N["subscribe_button"][code]
    sub_success = I18N["subscribe_success"][code]
    sub_error = I18N["subscribe_error"][code]

    subscribe_html = f"""
        <section class="subscribe">
            <h2>{html_escape(sub_title)}</h2>
            <p>{html_escape(sub_body)}</p>
            <form id="radar-sub-form" novalidate>
                <input type="email" name="email" required placeholder="{html_escape(sub_placeholder)}" aria-label="Email">
                <input type="hidden" name="lang" value="{code}">
                <button type="submit">{html_escape(sub_button)}</button>
            </form>
            <p id="radar-sub-msg" class="sub-msg" role="status" aria-live="polite"></p>
        </section>
        <script>
        (function() {{
            var form = document.getElementById('radar-sub-form');
            var msg = document.getElementById('radar-sub-msg');
            if (!form) return;
            form.addEventListener('submit', function(e) {{
                e.preventDefault();
                var email = form.email.value.trim();
                if (!email) return;
                msg.textContent = '…';
                msg.className = 'sub-msg';
                fetch('/api/subscribe', {{
                    method: 'POST',
                    headers: {{'content-type': 'application/json'}},
                    body: JSON.stringify({{email: email, lang: '{code}'}})
                }}).then(function(r) {{ return r.json().then(function(d) {{ return {{ok: r.ok && d.ok, d: d}}; }}); }})
                .then(function(res) {{
                    if (res.ok) {{
                        msg.textContent = {json.dumps(sub_success, ensure_ascii=False)};
                        msg.className = 'sub-msg ok';
                        form.reset();
                    }} else {{
                        msg.textContent = {json.dumps(sub_error, ensure_ascii=False)};
                        msg.className = 'sub-msg err';
                    }}
                }}).catch(function() {{
                    msg.textContent = {json.dumps(sub_error, ensure_ascii=False)};
                    msg.className = 'sub-msg err';
                }});
            }});
        }})();
        </script>"""

    content_html = "\n".join(sections_html)

    # RTL 基础 CSS
    rtl_css = """
        body[dir="rtl"] .header-inner { flex-direction: row-reverse; }
        body[dir="rtl"] .nav { text-align: left; }
        body[dir="rtl"] .keyword-section ol { padding-right: 1.2rem; padding-left: 0; }
        body[dir="rtl"] .cta-inner { text-align: right; }
    """

    html = f"""<!DOCTYPE html>
<html lang="{locale}" dir="{direction}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html_escape(site_name)} — {html_escape(site_subtitle)}</title>
    <meta name="description" content="{html_escape(site_subtitle)}">
    <link rel="canonical" href="{html_escape(canonical_url)}" />
    {'\n    '.join(hreflang_links)}
    <meta property="og:title" content="{html_escape(site_name)}" />
    <meta property="og:description" content="{html_escape(site_subtitle)}" />
    <meta property="og:url" content="{html_escape(canonical_url)}" />
    <meta property="og:site_name" content="AutoGlobalAI" />
    <meta property="og:type" content="website" />
    <link rel="sitemap" type="application/xml" href="{site_host}/sitemap.xml" />
    <script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>
    <style>
        :root {{
            --bg: #f8f9fb;
            --card: #ffffff;
            --text: #111827;
            --muted: #6b7280;
            --accent: #2563eb;
            --accent-dark: #1d4ed8;
            --border: #e5e7eb;
            --radius: 12px;
        }}
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
        .container {{ max-width: 960px; margin: 0 auto; padding: 0 1rem; }}
        header {{ background: var(--card); border-bottom: 1px solid var(--border); padding: 1rem 0; position: sticky; top: 0; z-index: 10; }}
        .header-inner {{ display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }}
        .brand {{ display: flex; align-items: center; gap: 0.75rem; text-decoration: none; color: var(--text); }}
        .brand img {{ width: 36px; height: 36px; object-fit: contain; }}
        .brand-text {{ font-weight: 700; font-size: 1.1rem; line-height: 1.2; }}
        .brand-sub {{ font-weight: 400; font-size: 0.8rem; color: var(--muted); }}
        .nav {{ text-align: right; font-size: 0.9rem; color: var(--muted); }}
        .nav a {{ color: var(--accent); text-decoration: none; }}
        .nav a.active {{ font-weight: 700; text-decoration: underline; }}
        .hero {{ background: linear-gradient(135deg, #0f172a, #1e3a8a); color: #fff; padding: 3rem 0 2.5rem; }}
        .hero h1 {{ margin: 0 0 0.5rem; font-size: 2rem; }}
        .hero p {{ margin: 0; opacity: 0.85; max-width: 600px; }}
        .cta {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: var(--radius); padding: 1.5rem; margin: 2rem 0; }}
        .cta h2 {{ margin: 0 0 0.5rem; font-size: 1.25rem; color: #1e40af; }}
        .cta p {{ margin: 0 0 1rem; color: #374151; }}
        .cta a.button {{ display: inline-block; background: var(--accent); color: #fff; padding: 0.75rem 1.5rem; border-radius: 6px; text-decoration: none; font-weight: 600; }}
        .cta a.button:hover {{ background: var(--accent-dark); }}
        .keyword-section {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.25rem; margin-bottom: 1rem; }}
        .keyword-section h2 {{ margin: 0 0 0.25rem; font-size: 1.15rem; }}
        .keyword-section .meta {{ margin: 0 0 0.75rem; font-size: 0.85rem; color: var(--muted); }}
        .keyword-section ol {{ margin: 0; padding-left: 1.2rem; }}
        .keyword-section li {{ margin-bottom: 0.5rem; }}
        .keyword-section .rank {{ display: inline-block; min-width: 2em; color: var(--muted); font-size: 0.85rem; }}
        .keyword-section .title {{ color: var(--text); }}
        .keyword-section .source {{ color: var(--muted); font-size: 0.85rem; }}
        .keyword-section a {{ color: var(--accent); text-decoration: none; }}
        .keyword-section a:hover {{ text-decoration: underline; }}
        .no-data {{ color: var(--muted); padding: 2rem 0; }}
        .subscribe {{ background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 1.5rem; margin: 2rem 0; }}
        .subscribe h2 {{ margin: 0 0 0.4rem; font-size: 1.2rem; }}
        .subscribe p {{ margin: 0 0 1rem; color: var(--muted); }}
        .subscribe form {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
        .subscribe input[type="email"] {{ flex: 1; min-width: 220px; padding: 0.7rem 0.9rem; border: 1px solid var(--border); border-radius: 6px; font-size: 1rem; }}
        .subscribe button {{ background: var(--accent); color: #fff; border: 0; padding: 0.7rem 1.4rem; border-radius: 6px; font-weight: 600; cursor: pointer; }}
        .subscribe button:hover {{ background: var(--accent-dark); }}
        .sub-msg {{ margin: 0.6rem 0 0; font-size: 0.9rem; }}
        .sub-msg.ok {{ color: #15803d; }}
        .sub-msg.err {{ color: #b91c1c; }}
        footer {{ text-align: center; color: var(--muted); font-size: 0.85rem; padding: 2rem 0; border-top: 1px solid var(--border); margin-top: 2rem; }}
        {rtl_css}
        @media (max-width: 640px) {{
            .hero h1 {{ font-size: 1.5rem; }}
            .header-inner {{ flex-direction: column; align-items: flex-start; }}
        }}
    </style>
</head>
<body dir="{direction}">
    <header>
        <div class="container header-inner">
            <a class="brand" href="{site_host}/{code}/">
                <img src="https://www.autoglobalai.com/logo.png" alt="AutoGlobalAI" onerror="this.style.display='none'">
                <div>
                    <div class="brand-text">{html_escape(site_name)}</div>
                    <div class="brand-sub">{html_escape(site_subtitle)}</div>
                </div>
            </a>
            <nav class="nav" aria-label="Language">
                {lang_switcher}
            </nav>
        </div>
    </header>

    <section class="hero">
        <div class="container">
            <h1>{html_escape(site_name)}</h1>
            <p>{html_escape(site_subtitle)}</p>
        </div>
    </section>

    <main class="container">
        <section class="cta">
            <div class="cta-inner">
                <h2>{html_escape(cta_title)}</h2>
                <p>{html_escape(cta_body)}</p>
                <a class="button" href="https://www.autoglobalai.com/?utm_source=radar&utm_medium=cta&utm_campaign=autoglobalai-radar&utm_content={code}" target="_blank" rel="noopener noreferrer">{html_escape(cta_button)}</a>
            </div>
        </section>

        <h2>{html_escape(keyword_ranking_title)}</h2>
        {content_html}
        {subscribe_html}
    </main>

    <footer>
        <div class="container">
            <p>{html_escape(I18N["footer_copyright"][code])}</p>
            <p>{html_escape(I18N["generated_at"][code])}: {generated_at}</p>
        </div>
    </footer>
</body>
</html>"""
    return html


def generate_sitemap(site_host: str, output_dir: Path) -> None:
    """生成 sitemap.xml"""
    urls = []
    now = datetime.now(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for lang in LANGUAGES:
        urls.append(f"""<url>
        <loc>{site_host}/{lang['code']}/</loc>
        <lastmod>{now}</lastmod>
        <changefreq>daily</changefreq>
        <priority>{'1.0' if lang['code'] == 'en' else '0.9'}</priority>
    </url>""")

    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

    (output_dir / "sitemap.xml").write_text(sitemap, encoding="utf-8")


SUBSCRIBE_FUNCTION_JS = r"""// Cloudflare Pages Function: POST /api/subscribe
// 邮箱写入 RADAR_SUBS KV；若配置了 RESEND_API_KEY + RESEND_AUDIENCE_ID 则同步进 Resend 受众。

function jsonResponse(obj, status) {
  return new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

export async function onRequestPost(context) {
  const { request, env } = context;
  let email = "";
  let lang = "";
  try {
    const ct = request.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      const body = await request.json();
      email = String(body.email || "").trim();
      lang = String(body.lang || "").trim().slice(0, 8);
    } else {
      const form = await request.formData();
      email = String(form.get("email") || "").trim();
      lang = String(form.get("lang") || "").trim().slice(0, 8);
    }
  } catch (e) {
    return jsonResponse({ ok: false, error: "bad_request" }, 400);
  }

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email) || email.length > 254) {
    return jsonResponse({ ok: false, error: "invalid_email" }, 422);
  }
  if (!env.RADAR_SUBS) {
    return jsonResponse({ ok: false, error: "not_configured" }, 503);
  }

  const key = email.toLowerCase();
  const record = JSON.stringify({
    email: key,
    lang: lang,
    ts: new Date().toISOString(),
    ua: (request.headers.get("user-agent") || "").slice(0, 200),
  });
  try {
    await env.RADAR_SUBS.put(key, record);
  } catch (e) {
    return jsonResponse({ ok: false, error: "storage_failed" }, 500);
  }

  if (env.RESEND_API_KEY && env.RESEND_AUDIENCE_ID) {
    try {
      await fetch(
        "https://api.resend.com/audiences/" + env.RESEND_AUDIENCE_ID + "/contacts",
        {
          method: "POST",
          headers: {
            Authorization: "Bearer " + env.RESEND_API_KEY,
            "content-type": "application/json",
          },
          body: JSON.stringify({ email: key, unsubscribed: false }),
        }
      );
    } catch (e) {
      // Resend 失败不影响留资结果
    }
  }

  return jsonResponse({ ok: true });
}

export async function onRequestOptions() {
  return new Response(null, { status: 204 });
}
"""


def write_subscribe_function(output_dir: Path) -> None:
    """把 Pages Function 写进站点产物（随 cloudflare_dist 一起部署）"""
    fn_dir = output_dir / "functions" / "api"
    fn_dir.mkdir(parents=True, exist_ok=True)
    (fn_dir / "subscribe.js").write_text(SUBSCRIBE_FUNCTION_JS, encoding="utf-8")
    print(f"[雷达站点] 已生成 functions/api/subscribe.js")


def generate_robots(site_host: str, output_dir: Path) -> None:
    """生成 robots.txt"""
    robots = f"""User-agent: *
Allow: /
Sitemap: {site_host}/sitemap.xml
"""
    (output_dir / "robots.txt").write_text(robots, encoding="utf-8")


def generate_root_redirect(output_dir: Path, default_lang: str = "en") -> None:
    """生成根目录重定向到默认语言"""
    html = f"""<!DOCTYPE html>
<html lang="{default_lang}">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="0; url=./{default_lang}/">
    <title>Redirecting...</title>
    <link rel="canonical" href="./{default_lang}/" />
</head>
<body>
    <p>Redirecting to <a href="./{default_lang}/">{default_lang} version</a>...</p>
</body>
</html>"""
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    """主入口"""
    config = load_config()
    ctx = AppContext(config)

    site_host = os.environ.get("RADAR_SITE_HOST", "https://radar.autoglobalai.com")
    default_lang = os.environ.get("RADAR_DEFAULT_LANG", "en")

    print(f"[雷达站点] 站点域名: {site_host}")

    # 加载关键词（保留 +/! 词组语义）
    freq_path = Path(ctx.config.get("FREQUENCY_WORDS_FILE", "config/frequency_words.txt"))
    if not freq_path.is_absolute():
        freq_path = REPO_ROOT / freq_path
    freq_groups, global_filter = load_frequency_groups(freq_path)
    print(f"[雷达站点] 已加载 {len(freq_groups)} 个词组，全局排除词 {len(global_filter)} 个")

    # 提取数据
    hotlist_items, rss_items = extract_items(ctx)
    all_items = hotlist_items + rss_items
    print(f"[雷达站点] 热榜 {len(hotlist_items)} 条，RSS {len(rss_items)} 条")

    if not all_items:
        print("[雷达站点] 没有数据，跳过站点生成")
        return

    # 按关键词分组（required AND + normal OR + 排除词）
    keyword_groups = group_items_by_keyword(all_items, freq_groups, global_filter, max_items_per_group=15)
    print(f"[雷达站点] 命中 {len(keyword_groups)} 个关键词")

    # 翻译关键词（可选，API 不稳定时可关闭）
    target_langs = [l["code"] for l in LANGUAGES]
    texts, meta = build_translation_payload(keyword_groups, max_keywords=30)
    print(f"[雷达站点] 待翻译关键词 {len(texts)} 条")

    ai_config = ctx.config.get("AI", {})
    translations: Dict[str, List[str]] = {}
    skip_translation = os.environ.get("RADAR_SKIP_TRANSLATION", "false").lower() == "true"
    if not skip_translation and texts:
        try:
            # 使用线程池加严格超时，避免 litellm 网络挂起导致 CI 卡死
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(translate_to_all_languages, texts, ai_config, target_langs)
                translations = future.result(timeout=120)
            print("[雷达站点] 关键词翻译完成")
        except concurrent.futures.TimeoutError:
            print("[雷达站点] 翻译超时，回退到中文关键词")
        except Exception as e:
            print(f"[雷达站点] 翻译失败，回退到中文关键词: {e}")
    else:
        print("[雷达站点] 跳过关键词翻译")

    lang_groups = build_translated_groups(keyword_groups, translations, meta)

    # 输出目录
    output_dir = Path(ctx.config.get("OUTPUT_DIR", "output")) / "site"
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(dt_timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # 生成各语言页面
    for lang in LANGUAGES:
        code = lang["code"]
        lang_dir = output_dir / code
        lang_dir.mkdir(parents=True, exist_ok=True)

        groups = lang_groups.get(code, {})
        if not groups:
            # 翻译失败时退回到原始中文
            groups = keyword_groups

        canonical_url = f"{site_host}/{code}/"
        html = build_page(
            lang=lang,
            groups=groups,
            all_langs=LANGUAGES,
            canonical_url=canonical_url,
            site_host=site_host,
            generated_at=generated_at,
        )
        (lang_dir / "index.html").write_text(html, encoding="utf-8")
        print(f"[雷达站点] 已生成 {code}/index.html")

    # 生成 SEO 文件
    generate_sitemap(site_host, output_dir)
    generate_robots(site_host, output_dir)
    generate_root_redirect(output_dir, default_lang)
    write_subscribe_function(output_dir)
    print(f"[雷达站点] 站点生成完成：{output_dir}")


if __name__ == "__main__":
    main()
