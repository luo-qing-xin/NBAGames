# NBA 单场原始数据抓取器

输入一个 NBA 比赛 ID，一条命令采集全部基础、扩展比赛数据，以及参赛和未激活球员的当前个人档案。统一命令只输出**完整原始 JSON 和抓取状态清单**，不生成 CSV、扁平表、派生统计或视频。

## 使用 uv 安装

需要 [uv](https://docs.astral.sh/uv/)。在项目根目录执行：

```bash
uv venv --python 3.12
uv sync --locked --extra dev
```

`.python-version` 固定 Python 3.12；`uv.lock` 固定依赖，使用 `nba_api==1.11.6`、`curl_cffi==0.15.0`。如果系统没有 Python 3.12，uv 可按其配置自动下载安装。无需手动激活虚拟环境，后续直接使用 `uv run`。

## 一条命令抓取全部数据

```bash
uv run python src/fetch_game.py 0022300001
```

比赛 ID 必须恰好为 10 位 ASCII 数字，前导零不可省略。默认单次请求超时 **30 秒**，默认输出到项目根目录的 `data/output/<比赛ID>/`。

```bash
# HTTP 或 SOCKS 代理；端口以本机实际配置为准
uv run python src/fetch_game.py 0022300001 --proxy http://localhost:11888
uv run python src/fetch_game.py 0022300001 --proxy socks5h://localhost:11889

# 切换节点后先检查 Stats 与 CDN，检查不会创建或修改比赛存档
uv run python src/fetch_game.py 0022300001 --proxy http://localhost:11888 --check-network

# 自定义输出根目录，其下自动追加比赛 ID
uv run python src/fetch_game.py 0022300001 --output-dir ./archive --timeout 60

# 忽略缓存，重新抓取所有比赛数据和球员档案
uv run python src/fetch_game.py 0022300001 --force
```

也可使用等价入口：

```bash
uv run python -m nba_pbp.game 0022300001
uv run nba-game 0022300001
```

未指定 `--proxy` 时，传输层读取 `HTTPS_PROXY`、`ALL_PROXY` 等标准代理环境变量；无代理环境配置时读取操作系统代理（包括 macOS 系统设置中的 HTTP/HTTPS 代理）。自动选择遵守 `NO_PROXY` 和系统绕过规则。显式参数优先，代理 URL 和凭据不写入日志或状态清单。系统代理需要保持运行；PAC 自动配置脚本不会由此工具执行。

在 macOS 上，仅开启系统代理而不导出环境变量时，旧版脚本可能仍然直连 Stats。当前版本已补上系统代理发现，可直接运行默认命令；也可用 `--proxy` 显式指定代理验证路线。`manifest.json` 的 `proxy_configured` 会包含自动发现的 Stats 代理。

## 默认采集清单

每次运行都处理以下 13 类比赛接口，无需额外开关：

| 内容 | nba_api 接口 | `raw/` 中的文件 |
| --- | --- | --- |
| 比赛状态、场馆、裁判、分节比分、未激活名单等 | `BoxScoreSummaryV3` | `box_score_summary_v3.json` |
| 球员与球队基础技术统计 | `BoxScoreTraditionalV3` | `box_score_traditional_v3.json` |
| 完整逐回合事件 | `PlayByPlayV3` | `play_by_play_v3.json` |
| 效率、节奏等高级指标 | `BoxScoreAdvancedV3` | `box_score_advanced_v3.json` |
| 四要素 | `BoxScoreFourFactorsV3` | `box_score_four_factors_v3.json` |
| 内线、快攻等其他统计 | `BoxScoreMiscV3` | `box_score_misc_v3.json` |
| 得分构成 | `BoxScoreScoringV3` | `box_score_scoring_v3.json` |
| 使用率 | `BoxScoreUsageV3` | `box_score_usage_v3.json` |
| 投篮位置、命中与未命中 | `ShotChartDetail` | `shot_chart_detail.json` |
| 球员上下场区间 | `GameRotation` | `game_rotation.json` |
| 跑动、触球、传球等比赛汇总 | `BoxScorePlayerTrackV3` | `box_score_player_track_v3.json` |
| 拼抢与掩护等 | `BoxScoreHustleV2` | `box_score_hustle_v2.json` |
| 球员对位汇总 | `BoxScoreMatchupsV3` | `box_score_matchups_v3.json` |

此外，将 Traditional 中所有球员（包含未出场球员）与 Summary 中未激活球员的 `personId` 去重，逐人调用 `CommonPlayerInfo`。每份响应保存为 `profiles/<personId>.json`，包括接口返回的全部结果集。

**个人档案是抓取时的当前资料，并非比赛发生时的历史档案。** 查询时间记录在清单的 `fetched_at` 中。比赛所属球队和本场状态以比赛原始响应为准。

全场技术统计不限制节次和时间范围。投篮接口使用 `TeamID=0`、`PlayerID=0`、`ContextMeasure=FGA`，按比赛 ID 设置赛季与比赛类型，避免只抓命中投篮或当前赛季数据。历史赛季和特殊比赛的数据覆盖以 NBA 实际返回为准。Tracking 是速度、距离、触球等汇总，不是连续位置轨迹。

## 输出结构与状态清单

```text
data/output/0022300001/
├── raw/
│   ├── box_score_summary_v3.json
│   ├── box_score_traditional_v3.json
│   ├── play_by_play_v3.json
│   ├── ...其余比赛接口原始响应
│   ├── live_box_score.json       # 仅在启用备用源后存在
│   └── live_play_by_play.json    # 仅在启用备用源后存在
├── profiles/
│   ├── 1628378.json
│   └── ...其他球员原始响应
└── manifest.json
```

raw/profile 文件保留接口完整 JSON 对象，包括未知字段、嵌套内容和全部结果集，不改变字段名称、原事件顺序或描述文本。仅统一 JSON 编码和缩进，将非有限浮点数转为标准 JSON 的 `null`；不保证与 HTTP 正文逐字节相同。

`manifest.json` 是程序生成的状态清单，记录比赛状态、运行时间、依赖版本，以及各资源的请求参数、来源、抓取时间、文件、SHA-256、请求次数和缓存命中情况。另含球员 ID、名单覆盖完整性、成功数和缺项列表。时间均为带时区的 UTC 时间。

资源状态为 `success`（有数据）、`empty`（合法空响应）、`failed`（未成功获取）。空投篮或空轮换等有效响应仍会保存。顶层状态为 `complete`、`partial`、运行中的 `running` 或用户中断后的 `interrupted`。

## 网络、备用源与部分失败

请求串行执行，开始时间至少间隔 1 秒。连接错误、超时、HTTP 429、5xx 和无效 JSON 最多尝试两次，采用指数退避和随机抖动。403 和 HTML 拦截页不在同源重复请求。

若两个不同的 Stats 接口连续返回 HTML，本次运行暂停后续 Stats 网络请求（含球员档案），继续读取有效缓存并处理官方 CDN 备用源。中间有 Stats JSON 成功响应时重新计数，单个接口失败或重复调用同一个失败接口不会触发暂停。未发出的请求在清单中仍为 `failed`，另标注 `skipped=true`、`attempts=0`，不会冒充抓取成功。下次运行自动重新检查 Stats，并补抓缺项。

Stats 逐回合失败时额外请求 NBA Live CDN；Summary 或 Traditional 失败时额外请求 Live BoxScore。备用响应独立保存，并标注 `nba_live_cdn` 来源。

**备用源不代表原 Stats 接口成功，也不能补齐所有高级统计或未激活名单。** 原接口缺项仍保留在清单中。名单部分可用时先抓已知球员档案，并标记 `roster_complete=false`。

单个接口或档案失败不阻止其他资源；成功文件逐项原子保存。不会将 HTTP 错误页或不匹配的比赛／球员响应保存为成功结果。

退出码：全部完成 `0`，部分失败或名单覆盖不完整 `1`，参数错误 `2`。请同时查看合法空结果；请求成功不等于上游提供了所有字段。

## 缓存与重新运行

- 已结束比赛：校验响应结构、比赛／球员 ID 和已有文件摘要，只补抓失败、缺失、损坏或被改动的资源。
- 未开赛、进行中或状态未知：每次刷新比赛资源。第一次观察到结束时，继续刷新其余全部比赛资源，之后才复用结束后的缓存。
- 球员档案独立缓存，不随比赛状态自动刷新；需要最新档案时使用 `--force`。
- 清单丢失或损坏时，可从有效原始响应重建；无法证明属于结束后快照的文件会重新获取。清单和摘要都丢失后，无法检测保持结构和身份不变的人工修改，必要时使用 `--force`。
- 强制刷新失败会保留原成功文件，并在清单注明；下一次正常运行仍会重试。判断本次结果以当前清单为准。
- 单个文件采用同目录临时文件和原子替换。中断后重跑即可补抓。请勿让多个进程同时使用同一比赛输出目录。

旧命令的 `data/<比赛ID>/pbp/` 和 `players/` 文件不会自动迁移，也不作为新命令的缓存。

## 常见问题

- **HTTP 200 但正文为 HTML**：可能是 NBA 接口临时异常或访问限制，不能仅凭 HTML 判定 IP 被封。[上游曾报告同样现象并自行恢复](https://github.com/swar/nba_api/issues/696)。错误提示会注明 HTTP 状态及是否为 `AkamaiNetStorage` 页面。先使用原命令追加 `--check-network`，通过相同代理分别验证 Stats 与 CDN 的 JSON 和比赛 ID，不写入存档。再检查代理软件中 `stats.nba.com` 的路由并尝试不同网络或节点；同样的 HTML 持续出现时应稍后重试。CDN 或 NBA 官网可用不代表 Stats 可用，也不能靠延长超时或反复重试恢复数据。网络恢复后重新运行原命令即可补抓，无需 `--force`。
- **403、持续超时**：当前请求可能受访问限制。检查 `stats.nba.com` 的代理路由，尝试不同网络或节点；更长的超时不能解决明确的拒绝响应。
- **429**：等待后重跑，避免并行采集多个比赛。
- **ID 错误**：确认使用 10 位 NBA GameID 并保留前导零。
- **未开赛或历史数据为空**：原始响应和清单会区分合法空数据与请求失败。
- **档案缺失**：检查名单完整性和对应请求的失败原因，再次运行补抓。

## 测试

```bash
uv run --extra dev pytest
```

自动测试禁止访问网络，覆盖接口调度、投篮参数、原始字段保留、球员去重、缓存补抓、状态刷新、备用源、原子写入和错误处理。真实 NBA 请求用统一命令单独验证，结果以实际 `manifest.json` 为准。

也可从 Stats 的真实比赛池做可复现的随机联网测试：

```bash
uv run python scripts/validate_stats_sample.py --seed 20261028 --timeout 60
```

默认从 2023–24、2024–25、2025–26 三个赛季的已完成常规赛中各随机抽取一场，每个比赛 ID 只进入候选池一次。抽样在抓取前固定，不会替换失败样本。比赛保存到 `data/output/<比赛ID>/`，候选池、随机种子和检查报告保存到 `data/validation/stats-random-sample/`。可用 `--seasons`、`--output-dir`、`--report-dir`、`--proxy` 和 `--force` 调整运行。

联网检查要求 13 个 Stats 资源均有数据、球员档案身份与摘要正确、关键统计字段有值、Summary／Traditional／PBP 的最终比分一致，以及 ShotChart 出手数等于 Traditional 的运动战出手总数。不会把 CDN 替代、合法空表或有缺项的结果算作全部通过；每场报告会列出缓存命中数。GameRotation 曾出现服务端 500 或超时，即使其他 Stats 接口正常也可能失败；保留失败状态，稍后正常重跑可只补抓缺项。[上游状态说明](https://github.com/swar/nba_api/blob/master/docs/nba_api/stats/endpoint_guide.md)

## 保留的独立命令

原有命令保持原行为和输出路径，默认超时仍为 15 秒：

```bash
uv run python -m nba_pbp 0022300001
uv run python -m nba_pbp 0022300001 --format both --force
uv run python -m nba_pbp.players 0022300001
```

这两类命令默认写入 `data/<比赛ID>/pbp/`、`data/<比赛ID>/players/`，仍可生成 JSON/CSV 表格和球员整合视图；新的统一命令仅保存原始 JSON。
