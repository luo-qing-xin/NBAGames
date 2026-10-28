# NBA 单场数据采集

输入一个 **10 位 NBA 比赛 ID**，自动查询该场比赛的 Stats、Live、五人阵容及相关球员当前档案。原始 JSON 按来源保存，同时生成机器可读清单与中文缺项说明。

## 开始使用

需要 Python 3.10+ 和 uv。在项目目录运行：

```bash
uv sync --extra dev
uv run nba-game 0022401196
```

也可以使用同一入口的模块形式：

```bash
uv run python -m nba_game 0022401196
```

比赛 ID 保留前导零。无需手填赛季、球队、球员或阵容 ID。一次命令获取一个快照；比赛进行中可重复运行更新，不包含后台持续轮询。

## 获取范围

|类别|接口／内容|
|---|---|
|比赛概要与传统统计|BoxScoreSummaryV3、BoxScoreTraditionalV3；保留场馆、裁判、名单、比分等原始字段|
|逐事件|Stats PlayByPlayV3 与 Live PlayByPlay，分别保存|
|高级统计|BoxScoreAdvancedV3、FourFactorsV3、MiscV3、ScoringV3、UsageV3|
|追踪与防守|BoxScorePlayerTrackV3、HustleV2、MatchupsV3、DefensiveV2|
|投篮与轮换|ShotChartDetail（FGA）、GameRotation|
|扣篮|DunkScoreLeaders，限目标比赛；部分年份可能返回空结果或错误|
|阵容|双方 TeamDashLineups，五人阵容、Base、Totals；再按实际 GROUP_ID 请求 ShotChartLineupDetail（FGA）|
|Live 技术统计|Live BoxScore；每场都尝试获取，不以 Stats 失败为前提|
|人员档案|对传统统计、概要未激活名单、Live 名单中的球员 ID 去重，查询 CommonPlayerInfo|

程序保存完整 JSON 响应，不依赖 DataFrame 解析器裁剪字段。额外结果集（例如投篮联盟均值）也保留在原接口文件内，但不会被当作本场投篮。Stats 和 Live 的动作字段、编号、枚举和坐标分别保留，不做无依据的跨源合并。JSON 中缺字段、null、空串和 0 保持区别；非标准 NaN/Infinity 转为 null。

“完整”仅指以上约定接口范围内的获取和校验完成，不代表 nba_api 的所有端点或每个字段都可用。CommonPlayerInfo 是**获取时的当前档案**，不保证反映历史比赛时的球队、号码或状态。

以下内容不在默认范围：赛季／生涯／排名背景、Synergy 战术汇总、赛季型 PlayerDashPt 数据、视频下载、赔率、非公开逐帧球员与篮球轨迹。BoxScorePlayerTrack 提供单场汇总，不能替代逐帧轨迹；已退役的旧版本接口也不重复调用。

## 输出目录

默认输出根目录是项目的 `data/games`：

```text
data/games/0022401196/
├── raw/
│   ├── stats/
│   │   ├── box_score_summary_v3.json
│   │   ├── …其他固定接口.json
│   │   ├── team_dash_lineups/<球队ID>.json
│   │   └── shot_chart_lineup_detail/<球队ID>/<阵容ID>.json
│   ├── live/
│   │   ├── live_box_score.json
│   │   └── live_play_by_play.json
│   └── players/<球员ID>.json
├── manifest.json
└── summary.md
```

`manifest.json` 使用 schema_version 2。每个资源记录来源、接口、请求参数、状态、尝试次数、时间、记录数、相对文件路径、SHA-256 和脱敏错误；动态资源键包含球队／阵容／球员 ID。`summary.md` 说明已获取内容、缺项、原因和建议，链接到原始文件。球员档案、Stats、Live 使用同一采集与缓存流程。

状态包括 `success`（非空）、`empty`（结构合法但无记录）、`failed`（请求或校验失败）、`skipped`（依赖缺失或暂停后未请求）。空结果单独计数，不计入非空成功数。失败刷新保留旧文件并标记 `retained_previous_file`，不把旧数据冒充本次请求成功。

完成状态为 `complete` 或 `partial`；被中断时为 `interrupted`。存在请求失败、未执行依赖、名单不完整或关键一致性错误时返回退出码 1；范围内完成返回 0；命令行参数错误返回 2。成功返回 HTTP 200 本身不构成获取成功，HTML 页面、错误身份和结构不完整都会被识别。

## 参数、缓存与网络

```bash
# 修改根目录，其下自动追加比赛 ID
uv run nba-game 0022401196 --output-dir ./my-data

# 使用指定代理
uv run nba-game 0022401196 --proxy http://127.0.0.1:11888

# 强制刷新全部接口及人员档案
uv run nba-game 0022401196 --force --timeout 60

# 只读检查 Stats 与 Live，不写入比赛存档
uv run nba-game 0022401196 --check-network
```

默认超时为单次请求 30 秒。代理优先使用 `--proxy`，否则读取环境变量或系统 HTTP/HTTPS 代理，并遵循绕过规则；不执行 PAC 脚本。不会在报告中保存代理凭据。

请求串行执行，开始时间至少间隔 1 秒。网络错误、超时、429、5xx、无效 JSON 最多尝试 2 次；400、403、HTML 和结构校验失败不会盲目重复请求。两个不同 Stats 接口连续返回 HTML 时暂停本轮后续 Stats 请求，Live 仍继续；下次运行会重新探测。HTTP 500 或 HTML 只记录观察到的错误，不直接判定为 IP 封禁。

终场有效非空缓存可复用；未终场比赛刷新比赛资源；第一次确认终场时刷新其余比赛数据。人员当前档案独立缓存，可用 `--force` 更新。失败、跳过与空结果下次运行重新尝试。每个资源完成后原子保存进度，中断后重跑同一命令即可补抓。

检查包括比赛／球员身份、阵容参数回显和 GP=1、阵容投篮的比赛／球队／阵容身份、终场跨源比分、ShotChart 出手数与传统统计，以及高级统计等关键字段的可用性。跨源修订可能造成差异，会列为校验失败；可在源数据稳定后使用 `--force` 刷新复查。合法空结果也可能因与其他数据矛盾而触发一致性失败。

## 旧数据与目录迁移

包名已从 `nba_pbp` 改为 `nba_game`。`nba-pbp`、旧球员独立命令和 `src/fetch_game.py` 不再提供；统一使用 `nba-game`。更新环境后旧入口会随旧包卸载。

默认首次运行时，从 `data/output/<比赛ID>` 校验并复制旧版原始文件到 `data/games/<比赛ID>`。自定义输出根目录时，旧目录位置按其同级的 `output/<比赛ID>` 查找。新目录中已有有效文件优先；`--force` 直接重新获取，不导入旧缓存。

导入保留来源、原获取时间及迁移信息，不删除旧目录；错误身份、损坏或校验值不符的缓存重新获取。更早的 `data/<比赛ID>/pbp`、`players` 等加工导出目录原样保留，不自动混入原始响应。现有忽略规则保持不变。

## 代码结构

```text
src/nba_game/
├── cli.py、__main__.py       # 同一命令流程
├── collector.py             # 上下文、依赖展开、断点恢复
├── models.py                # 资源、比赛上下文、响应类型
├── sources/stats.py         # Stats 接口清单与显式参数
├── sources/live.py          # Live 数据源
├── transport.py             # 会话、代理、限速、重试、错误分类
├── storage.py               # 原子存储、缓存、旧数据导入
├── validation.py            # 原始响应及跨接口校验
├── reporting.py             # 中文结果说明
└── arguments.py、errors.py、serialization.py、diagnostics.py
```

新增接口先加入清单及参数／校验逻辑，再声明依赖；不需要新增一套 CLI、HTTP 或存储实现。固定接口、球队阵容请求、逐阵容投篮和球员档案分别动态统计，不写死资源总数。

## 测试

离线测试禁止访问网络：

```bash
uv run --extra dev pytest -q
```

真实抽样验证：

```bash
uv run python scripts/validate_stats_sample.py
```

默认从 2023–24、2024–25、2025–26 的已完赛常规赛中各均匀抽取一场，固定种子 20261028，先去重、再抽样、最后开始采集，失败样本不替换。保存候选比赛池、池校验值、选择结果、清单和校验报告。默认使用独立目录 `data/validation/unified-game-sample`，其中 `games/` 保存比赛存档；不会使用生产目录的已有比赛缓存。

可通过 `--seasons`、`--seed`、`--output-dir`、`--report-dir`、`--timeout`、`--proxy`、`--force` 调整验证设置。验证脚本返回非零可能表示上游数据缺项，应同时查看 `report.md`、`report.json` 和单场 `summary.md`，不能据此将离线程序测试误报为失败或通过。
