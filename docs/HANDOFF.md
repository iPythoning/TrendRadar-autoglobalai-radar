# AutoGlobalAI 多语言情报雷达 — 交接文档

## 项目目标
部署 `radar.autoglobalai.com`，把中文汽车出口信号翻译成 6 种目标语言（EN/RU/AR/ES/FA/PT），输出静态多语言站点，为 AutoGlobalAI 主站引流并沉淀 SEO/GEO 资产。

## 关键链接
- **GitHub**: https://github.com/iPythoning/TrendRadar-autoglobalai-radar
- **站点**: https://radar.autoglobalai.com
- **CF Pages 项目**: `autoglobalai-radar`
- **主站**: https://www.autoglobalai.com
- **上游**: https://github.com/sansan0/TrendRadar

## 已实现
- [x] 基于 TrendRadar 抓取中文热榜 + RSS
- [x] `config/frequency_words.txt` 静态汽车出口关键词词表
- [x] `trendradar/keywords_optimizer.py` 动态关键词发现（每日生成 `config/suggest_keywords.txt`）
- [x] `scripts/build_autoglobalai_radar.py` 生成 6 语言静态站点
  - 含 hreflang、canonical、JSON-LD、sitemap.xml、robots.txt
  - RTL 支持（ar、fa）
  - AutoGlobalAI 品牌导航与 CTA
- [x] `.github/workflows/crawler.yml` 每小时抓取 + 构建 + 部署到 Cloudflare Pages
- [x] Cloudflare Pages 项目 `autoglobalai-radar` 已创建
- [x] 自定义域名 `radar.autoglobalai.com` + CNAME 已配置

## 代码结构
```
config/frequency_words.txt          # 静态关键词词表
config/suggest_keywords.txt         # 动态候选词（每日自动生成，勿提交）
scripts/build_autoglobalai_radar.py # 6 语言站点生成器
trendradar/keywords_optimizer.py    # 动态关键词优化器
trendradar/ai/client.py             # 扩展支持 OMNI_API_KEY / OMNI_BASE_URL
trendradar/__main__.py              # 集成关键词优化器到主流程
.github/workflows/crawler.yml       # 抓取+构建+部署流水线
```

## 本地运行
```bash
# 1. 抓取热榜/RSS
uv run python -m trendradar

# 2. 生成多语言站点
RADAR_SITE_HOST=https://radar.autoglobalai.com uv run python scripts/build_autoglobalai_radar.py

# 翻译失败时跳过翻译
RADAR_SKIP_TRANSLATION=true uv run python scripts/build_autoglobalai_radar.py
```

## GitHub Secrets/Vars
### Secrets
- `CLOUDFLARE_API_TOKEN` — Cloudflare API Token（Cloudflare Pages:Edit + Zone:Edit）
- `CLOUDFLARE_ACCOUNT_ID` — `1649a7519a5895b9120c661e7063ad7a`
- `CLOUDFLARE_PROJECT_NAME` — `autoglobalai-radar`
- `OMNI_API_KEY` / `AI_API_KEY` — omni.paibao.ai API Key
- `OMNI_BASE_URL` — `https://omni.paibao.ai/v1`

### Variables
- `RADAR_SITE_HOST` — `https://radar.autoglobalai.com`
- `CI_RUNNER` — 可选，设置为 `["ubuntu-latest"]` 或自建 runner

## 注意事项
- `output/` 已加入 `.gitignore`，不提交数据库和生成文件。
- `OMNI_API_KEY` 优先于 `AI_API_KEY`。
- 翻译服务偶发 502/超时，站点生成器会回退到中文关键词，保证构建不中断。
- 当前条目标题仍为中文（源语言），仅关键词与页面 UI 本地化。

## 待改进
- [ ] 异步/批量优化翻译速度与稳定性
- [ ] 翻译条目标题并做质量校验
- [ ] 增加 AI 摘要与趋势解读区块
- [ ] 接入主站 `/news`/`/blog` 最新文章交叉链接
- [ ] 根据 `config/suggest_keywords.txt` 定期回注优质动态词到 `frequency_words.txt`

## 最近更新
- 2026-08-31: 多语言站点生成器、CF Pages 部署、自定义域名配置完成。

## 交接人
- 仓库: iPythoning/TrendRadar-autoglobalai-radar
- 最后会话: 2026-08-31
