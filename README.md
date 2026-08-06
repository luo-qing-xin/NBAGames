# NBA 原始比赛数据抓取器

这个项目可以抓取和保存 NBA 官方原始逐回合数据，也提供独立命令抓取比赛球员、未激活名单和个人档案。输入一个 10 位 NBA 比赛 ID 后，逐回合命令优先调用 `nba_api.stats.endpoints.playbyplayv3.PlayByPlayV3`；若 Stats 服务被限流、拦截或暂时不可用，会自动改抓 NBA 官方 Live CDN 的同场 play-by-play JSON。

逐回合命令不进行数据清洗、字段标准化、事件识别、球员角色解析、统计分析或视频剪辑。接口中的空值、异常格式、未知字段和 `description` 文本会保留；唯一的 JSON 兼容处理是把非有限浮点值表示为标准 JSON 的 `null`。球员命令另外生成明确标注来源的整合视图，原始响应仍会单独保留。

## 环境与安装

需要 Python 3.10 或更高版本。项目优先并固定兼容 `nba_api==1.11.4`。

建议使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

如需运行测试：

```bash
python -m pip install -e '.[dev]'
python -m pytest
```

测试全部使用模拟响应，不会访问 NBA Stats API。

## 运行方法

比赛 ID 必须恰好由 10 位数字组成，例如 `0022300001`：

```bash
python -m nba_pbp 0022300001
python -m nba_pbp 0022300001 --output-dir ./data
python -m nba_pbp 0022300001 --format json
python -m nba_pbp 0022300001 --format csv
python -m nba_pbp 0022300001 --format both
python -m nba_pbp 0022300001 --force
python -m nba_pbp 0042500405 --proxy http://localhost:11888 --timeout 15 --force
```

默认格式是 `both`，默认输出根目录是 `data`，单次请求超时为 15 秒。`--output-dir` 指定的也是根目录，因此逐回合命令使用 `--output-dir ./archive` 时会写入 `./archive/0022300001/pbp/`，球员命令则写入 `./archive/0022300001/players/`。

`--proxy` 接受带协议、主机和端口的 HTTP、HTTPS 或 SOCKS URL。若未指定，传输层会读取 `HTTPS_PROXY`、`ALL_PROXY` 等标准代理环境变量；显式的 `--proxy` 优先。代理 URL 可能包含凭据，但程序不会把 URL 或凭据写入输出文件和错误信息。

如果比赛 ID 不符合 `^\d{10}$`，程序会显示中文错误、返回非零退出码，并且不会发送网络请求。

## 输出文件

默认运行会在 `data/<game_id>/pbp/` 中生成：

```text
api_response_raw.json
play_by_play_raw.json
play_by_play_raw.csv
```

- `api_response_raw.json` 是最重要的完整原始响应存档，保留 API 返回的层级、结果内容、字段名称和所有数据。
- `play_by_play_raw.json` 是保持原事件顺序和完整字段的逐回合记录数组，不包含索引或业务派生字段。
- `play_by_play_raw.csv` 是同一逐回合表的人工查看版本，使用 `utf-8-sig` 编码。

`--format json` 生成完整响应 JSON 和逐回合 JSON；`--format csv` 生成完整响应 JSON 和逐回合 CSV；`--format both` 生成以上三个文件。程序不再单独生成 available-video 或抓取 metadata 文件，但 NBA 原始响应中的 `videoAvailable` 字段仍保留在 `api_response_raw.json` 中。

JSON 适合作为保留类型和层级的原始存档。CSV 便于用表格软件查看，但空值显示为空单元格，未知的嵌套对象或数组会在单个单元格中使用紧凑 JSON 表示。请始终把 `api_response_raw.json` 视为权威原始存档。

## 球员信息、未激活名单和个人档案

独立球员命令会依次调用 `BoxScoreTraditionalV3`、`BoxScoreSummaryV3`，然后对参赛名单与未激活名单中的每个 `personId` 调用 `CommonPlayerInfo`：

```bash
python -m nba_pbp.players 0042500405
python -m nba_pbp.players 0042500405 --output-dir ./data
python -m nba_pbp.players 0042500405 --proxy http://localhost:11888 --timeout 15
python -m nba_pbp.players 0042500405 --force
```

支持的网络、代理、超时和输出根目录约定与逐回合命令相同。程序会在相邻的球员档案请求之间加入短暂间隔，并对可重试错误进行有限重试，以降低触发 NBA Stats 限流的概率。

结果写入 `data/<game_id>/players/`：

```text
box_score_traditional_v3_raw.json
box_score_summary_v3_raw.json
common_player_info_raw.json
game_players.json
game_players.csv
```

- 前两个 raw 文件分别是 Box Score 和比赛摘要的完整原始响应。
- `common_player_info_raw.json` 是按 `personId` 保存多次 CommonPlayerInfo 原始响应的容器，同时记录最近一次失败原因。
- `game_players.json` 为每名球员保存嵌套的 `boxScore`、`inactive`、`profile`、`headlineStats` 和 `availableSeasons`，并标记 `played`、`available_not_played` 或 `inactive`。
- `game_players.csv` 是同一结果的扁平表格视图，各来源字段带前缀，避免当前个人档案覆盖本场比赛的球队、号码或位置。

有效原始响应会作为缓存重复使用。若单个 CommonPlayerInfo 请求失败，命令会保存其他成功响应和带失败状态的整合表、输出失败的球员 ID，并返回非零退出码；再次运行只补抓缺失或失败的球员。`--force` 会忽略所有球员信息缓存并重新抓取。CommonPlayerInfo 描述的是查询时的当前档案，本场球队和比赛状态应以 Box Score 与 Summary 字段为准。

## 缓存与可靠保存

程序不会只因为目录存在就认定缓存成功。它会严格解析 `api_response_raw.json`，检查游戏 ID、完整响应结构以及非空 actions。合法但被人工修改过的完整响应无法与 NBA 原始响应区分；如需明确重新抓取，请使用 `--force`。

有效缓存存在时，程序输出“正在使用缓存”并且不重新请求。若缓存只有 JSON 或 CSV 其中一种表格格式，程序会直接从 `api_response_raw.json` 补齐另一种格式，不联网。只有指定 `--force` 才会忽略有效缓存并重新抓取。

逐回合和球员数据分别在同一比赛下的 `pbp/` 与 `players/` 子目录中独立保存和复用缓存。旧版直接存放在 `data/<game_id>/` 下的平铺文件不会被迁移、删除或作为新目录的缓存读取，首次使用新目录时会重新抓取。

所有结果先写入对应数据目录的临时文件，验证完成后才替换正式文件，`api_response_raw.json` 最后提交。写入失败会恢复先前成功的数据；若进程在替换期间异常终止，下次运行会尝试自动恢复未完成事务。成功保存或命中缓存后，`pbp/` 中旧版的 available-video 和 metadata 文件会自动删除。

## 网络传输、备用源和常见错误

NBA Stats API 可能限流、超时、受地区或网络环境限制，也可能对普通 Python HTTP 客户端静默丢弃响应。程序使用 `curl_cffi` 模拟 Chrome 的 TLS/HTTP 指纹，并按 Stats、NBA Live CDN 的顺序尝试两个官方来源。

每个来源对连接失败、超时、HTTP 429、HTTP 5xx 和无效 JSON 最多尝试 2 次，并使用带随机抖动的指数退避。HTTP 403 或“HTTP 200 但正文是 HTML”的 NBA 拦截页不会在同一来源重复请求，而会立即切换来源。两个来源均失败时，错误会分别概括 Stats 和 CDN 的原因，并提示配置或切换代理节点。

常见处理方法：

- “比赛 ID 必须恰好由 10 位数字组成”：检查是否遗漏前导零或混入空格、字母。
- HTTP 429：等待一段时间后再运行，避免短时间抓取过多比赛。
- 超时、HTTP 5xx 或无效 JSON：稍后重试，并确认当前网络可访问 `stats.nba.com` 和 `cdn.nba.com`。
- HTTP 403、HTML 拦截页或持续连接失败：当前出口 IP 可能受地区或 Akamai 风控限制。启动代理并传入 `--proxy`；若仍失败，应切换代理节点，而不是继续增大 timeout。
- MarsLink 示例：HTTP 代理通常可写成 `--proxy http://localhost:11888`，SOCKS 代理可写成 `--proxy socks5h://localhost:11889`；请以本机实际监听端口为准。
- 响应中没有逐回合记录：确认比赛已经开始或结束，并确认比赛 ID 对应真实比赛。
- 本地缓存疑似过期但仍然有效：使用 `--force` 明确重新抓取。

普通模式只显示简短失败原因，不输出完整 HTML 错误页或冗长堆栈。请求失败不会创建看起来成功的空数据文件。

## 完整示例

```bash
python -m nba_pbp 0022300001 --output-dir ./data --format both
```

成功后输出类似：

```text
抓取完成：data/0022300001/pbp
```

随后再次运行同一命令会验证文件并使用缓存：

```text
正在使用缓存：data/0022300001/pbp
```
