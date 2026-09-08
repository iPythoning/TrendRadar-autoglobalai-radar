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
- [x] **新车上市监控（第二期）**：`scripts/extract_new_car_launches.py`（粗筛→AI 结构化提取→待审清单 `output/new-car-launches/YYYY-MM-DD.json`），已接入 crawler.yml 构建后
- [x] **车型库 diff（方案 D）**：`scripts/diff_car_catalog.py`（对比汽车之家/懂车帝库两次快照，新增车系=新车），待数据库到位即用
- [x] 新增汽车 RSS 源：CarNewsChina、CnEVPost、IT之家（新车上市信号源，补全 carnewschina 单源局限）
- [x] Cloudflare Pages 项目 `autoglobalai-radar` 已创建
- [x] 自定义域名 `radar.autoglobalai.com` + CNAME 已配置

## 代码结构
```
config/frequency_words.txt          # 静态关键词词表
config/suggest_keywords.txt         # 动态候选词（每日自动生成，勿提交）
scripts/build_autoglobalai_radar.py # 6 语言站点生成器
scripts/extract_new_car_launches.py # 新车上市监控：RSS/热榜→AI 结构化提取→待审清单
scripts/diff_car_catalog.py         # 车型库 diff：两版本库对比，新增车系=新车
config/config.yaml                  # 新增 carnewschina/cnevpost/ithome RSS 源
trendradar/keywords_optimizer.py    # 动态关键词优化器
trendradar/ai/client.py             # 扩展支持 OMNI_API_KEY / OMNI_BASE_URL
trendradar/__main__.py              # 集成关键词优化器到主流程
.github/workflows/crawler.yml       # 抓取+构建+新车提取+部署流水线
```

## 新车上市监控链路（第二期）

**目的**：监控中国新增车型 → 产出结构化待审清单 → 供 chinesecarnames 补库（人工核实出口名后入）。

**信号源（RSS，都已 200 可用）**：
- `carnewschina.com/feed/` — 海外视角中国车新闻（含燃油车/传统厂）
- `cnevpost.com/feed/` — 中国新能源车垂直，新车预售/上市信号密度最高
- `ithome.com/rss/` — 长尾（小米/华为造车等跨界）

**流程**：crawler.yml 每小时 → 抓 RSS/热榜 → `extract_new_car_launches.py --days 3` 粗筛「上市/发布/亮相/预售」+品牌线索 → AIClient 结构化提取 {品牌中文名,车系中文名,上市时间,动力,车体,来源} → 输出 `output/new-car-launches/YYYY-MM-DD.json`。**只出待审清单，不自动写库**（出口名需人工核实）。

**⚠️ omni 网关的三个关键坑（已修复，勿重蹈）**：
1. `temperature=0.0` 会触发 omni 网关返回 `{"User Safety": "safe"}` 安全拦截（非真实模型输出），必须用 `temperature=1.0`。
2. 模型名必须用 `openai/auto/best-chat`（指令遵循强），**不能用 `openai/auto/fast`**（免费但返回纯文本而非 JSON）。脚本已强制 `NEW_CAR_MODEL`（默认 best-chat），不受 CI 的 `AI_MODEL` 环境变量影响。
3. AI 输出可能被 max_tokens 截断（无闭合 `]`），解析需逐对象回退：丢弃不完整尾部，保留完整对象。

**实测效果**（2026-09-08 CI）：429 条标题 → 粗筛 21 条 → AI 提取 17 条（小米 Sky Nomad/澎程N70、岚图梦想家9、比亚迪海狮08、奇瑞捷豹路虎 Freelander 8、吉利银河 TT、智己 LS6、广汽华为 Aistaland GX7 等，中文名均正确）。


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

## 部署状态
- **手动部署**：已完成。首次站点通过 `wrangler pages deploy` 从本地部署到 `autoglobalai-radar` 项目，自定义域名 `radar.autoglobalai.com` 已解析并返回 HTTP 200。
- **自动部署（GitHub Actions）**：流水线 `crawler.yml`、Secrets/Vars、xserver self-hosted runner 均已配置，但 GitHub Actions 目前未向该仓库的 runner 派发任何 job（workflow 一直停留在 queued）。疑似账户/仓库级 GitHub Actions 调度问题，正在排查。

## 手动更新站点（临时）
```bash
cd /tmp/trendradar-autoglobalai/repo
uv run python -m trendradar                          # 抓取
RADAR_SITE_HOST=https://radar.autoglobalai.com uv run python scripts/build_autoglobalai_radar.py
cd output/site
CF_API_TOKEN=<token> CLOUDFLARE_ACCOUNT_ID=1649a7519a5895b9120c661e7063ad7a \
  wrangler pages deploy . --project-name=autoglobalai-radar --branch=main
```

## 注意事项
- `output/` 已加入 `.gitignore`，不提交数据库和生成文件。
- `OMNI_API_KEY` 优先于 `AI_API_KEY`。
- 翻译服务偶发 502/超时，站点生成器会回退到中文关键词，保证构建不中断。
- 当前条目标题仍为中文（源语言），仅关键词与页面 UI 本地化。

## 待改进
- [ ] 解决 GitHub Actions 不向该仓库 self-hosted runner 派单的问题，恢复自动部署
- [ ] 异步/批量优化翻译速度与稳定性
- [ ] 翻译条目标题并做质量校验
- [ ] 增加 AI 摘要与趋势解读区块
- [ ] 接入主站 `/news`/`/blog` 最新文章交叉链接
- [ ] 根据 `config/suggest_keywords.txt` 定期回注优质动态词到 `frequency_words.txt`

## 最近更新
- 2026-09-07: 第二期新车上市监控：新增 `extract_new_car_launches.py`（RSS/热榜→AI 结构化提取→待审清单）+ `diff_car_catalog.py`（车型库 diff，待数据库）+ 三个汽车 RSS 源（carnewschina/cnevpost/ithome），接入 crawler.yml。
- 2026-08-31: 多语言站点生成器、CF Pages 部署、自定义域名配置完成；首次手动部署上线。

## 交接人
- 仓库: iPythoning/TrendRadar-autoglobalai-radar
- 最后会话: 2026-08-31
