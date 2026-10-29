<p align="center">
  <img src="docs/assets/nba-game-banner.png" alt="NBA GAME · 单场数据采集与归档" width="100%">
</p>

<p align="center">
  <strong>输入一个 10 位比赛 ID。归档一场 NBA 比赛可获取的完整原始数据。</strong>
</p>

<p align="center">
  <a href="https://github.com/luo-qing-xin/NBAGames/actions/workflows/ci.yml"><img src="https://github.com/luo-qing-xin/NBAGames/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <a href="#2-环境要求"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.10+"></a>
  <a href="#1-项目介绍"><img src="https://img.shields.io/badge/version-0.2.0-0E7490?style=flat-square" alt="version 0.2.0"></a>
  <a href="#1-项目介绍"><img src="https://img.shields.io/badge/data-NBA%20Stats%20%2B%20Live%20CDN-C9082C?style=flat-square" alt="NBA Stats + Live CDN"></a>
  <a href="#2-环境要求"><img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-444444?style=flat-square&amp;logo=linux&amp;logoColor=white" alt="macOS, Linux, Windows"></a>
</p>

<p align="center">
  <strong>简体中文</strong> &nbsp;|&nbsp; <a href="README.en.md">English</a>
</p>

<p align="center">
  <a href="#1-项目介绍">项目介绍</a> &nbsp;·&nbsp;
  <a href="#2-环境要求">环境要求</a> &nbsp;·&nbsp;
  <a href="#3-快速开始">快速开始</a> &nbsp;·&nbsp;
  <a href="#4-使用示例">使用示例</a>
  <br>
  <a href="#5-输出说明">输出说明</a> &nbsp;·&nbsp;
  <a href="#6-常见问题">常见问题</a> &nbsp;·&nbsp;
  <a href="#7-开发与测试">开发与测试</a> &nbsp;·&nbsp;
  <a href="#8-必要说明">必要说明</a>
</p>

---

## 1. 项目介绍

`nba-game` 是一个 Python 命令行工具：输入 10 位 NBA 比赛 ID，从 NBA Stats 和 Live CDN 获取比赛统计、逐回合事件、投篮、五人阵容及球员当前档案，按来源保存原始 JSON，并生成中文摘要和可追溯的采集清单。

项目在本地运行，不启动 Web 服务，不监听端口，无需数据库或 API Key。每次执行采集一个比赛快照；具体可获取的数据取决于 NBA 接口、比赛状态及对应赛季的支持情况。

## 2. 环境要求

| 项目 | 要求 |
|---|---|
| 操作系统 | macOS、Linux 或 Windows（PowerShell） |
| Python | 3.10+；仓库默认使用 **3.12**，可由 uv 安装 |
| 工具 | Git、uv；首次使用 uv 的步骤见下文 |
| 安装网络 | 能访问 GitHub、Python 下载源和 PyPI |
| 采集网络 | 能访问 `stats.nba.com` 和 `cdn.nba.com`，必要时配置代理 |
| 文件权限 | 项目及输出目录可写，并为依赖、Python 缓存和采集数据预留空间 |

不需要 Node.js、GPU 或额外的后台服务。运行依赖由 `pyproject.toml` 声明、`uv.lock` 锁定，不必逐个手动安装。

## 3. 快速开始

### 3.1 安装 uv

macOS / Linux：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows PowerShell：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装后重新打开终端，检查 Git 和 uv：

```bash
git --version
uv --version
```

若尚未安装 Git，请先安装后继续；也可从仓库页面下载 ZIP 并解压，随后在解压目录执行下文安装命令。

### 3.2 获取项目并安装依赖

```bash
git clone https://github.com/luo-qing-xin/NBAGames.git
cd NBAGames
uv python install 3.12
uv sync --locked
uv run nba-game --help
```

`uv sync` 会创建 `.venv` 并安装项目及运行依赖。看到命令帮助即表示入口可用；无需手动激活虚拟环境，也无需创建配置文件。

**下文所有命令均在项目根目录执行。** macOS/Linux 和 PowerShell 可使用相同的 `uv run` 命令。

### 3.3 检查数据源连接

使用示例比赛 ID 检查两个数据源，此命令不会写入或修改比赛存档：

```bash
uv run nba-game 0022401196 --check-network
```

正常时会分别显示：

```text
NBA Stats：可用（JSON 与比赛 ID 校验通过）
NBA Live CDN：可用（JSON 与比赛 ID 校验通过）
网络检查完成，未修改任何比赛存档。
```

两个数据源均可用时继续采集。若不可用，先看[代理示例](#42-使用代理)或[常见问题](#6-常见问题)。Live 可用不代表 Stats 可用；检查通过也不能保证后续每个接口均有数据。

### 3.4 采集第一场比赛

```bash
uv run nba-game 0022401196
```

程序串行请求多个接口，并保持请求间隔，一场比赛可能耗时数分钟。结果自动写入 `data/games/0022401196/`。

### 3.5 确认运行结果

- 控制台显示“抓取完成”且退出码为 `0`：本次采集范围内完成。
- 显示“部分数据未完成”或退出码为 `1`：已保存成功结果，请查看摘要中的缺项和处理建议。
- 首先打开 `data/games/0022401196/summary.md`；需要逐项核查时再看同目录的 `manifest.json`。

如需检查退出码，请紧接采集命令执行：

```bash
# macOS / Linux
echo $?
```

```powershell
# Windows PowerShell
$LASTEXITCODE
```

部分失败时无需删除输出目录。解决网络问题或等待上游恢复后，重新执行原采集命令即可补抓。

## 4. 使用示例

### 4.1 更换比赛

在 NBA 官网打开目标比赛页面，从 URL 中找到 10 位数字比赛 ID，替换命令中的示例值。ID 必须保留前导零，赛季和比赛类型由程序自动推导。

```bash
uv run nba-game 0022300001
```

比赛 ID 应作为字符串保存；在 Python、CSV 或表格中将它转为整数会丢失前导零。

### 4.2 使用代理

先启动自己的代理软件，将下方地址和端口换成实际值。网络检查与正式采集使用同一个代理：

```bash
uv run nba-game 0022401196 --proxy http://127.0.0.1:7890 --check-network
uv run nba-game 0022401196 --proxy http://127.0.0.1:7890
```

`--proxy` 支持带主机及端口的 HTTP、HTTPS 和 SOCKS URL，例如 `socks5h://127.0.0.1:7890`。程序不执行 PAC 脚本。

不传 `--proxy` 时，会自动读取代理环境变量或系统代理。也可在当前终端设置 `HTTPS_PROXY`：

```bash
# macOS / Linux
export HTTPS_PROXY=http://127.0.0.1:7890
```

```powershell
# Windows PowerShell
$env:HTTPS_PROXY = "http://127.0.0.1:7890"
```

设置后运行普通采集命令即可。自动代理选择会考虑 `NO_PROXY`；显式传入的 `--proxy` 优先。**项目不读取 `.env` 文件**，请直接传参或在终端设置环境变量。

### 4.3 调整输出位置和超时

```bash
uv run nba-game 0022401196 --output-dir ./nba-data --timeout 60
```

结果位于 `./nba-data/0022401196/`。`--output-dir` 是输出根目录，程序会自动追加比赛 ID；相对路径按当前工作目录解析。

`--timeout` 是单次请求的超时秒数，不是整场采集的总时限。

### 4.4 强制刷新

```bash
uv run nba-game 0022401196 --force
```

此命令忽略已有缓存，重新抓取全部比赛数据和球员档案。普通的失败补抓通常只需重跑原命令，不必加 `--force`。

### 4.5 参数速查

| 参数 | 默认值 | 说明 |
|---|---|---|
| `game_id` | 必填 | 恰好 10 位数字，保留前导零 |
| `--output-dir` | 项目的 `data/games` | 输出根目录，其下自动追加比赛 ID |
| `--proxy` | 自动读取环境或系统代理 | 包含协议、主机和端口的代理 URL |
| `--timeout` | `30` | 单次请求超时秒数，必须为有限正数 |
| `--force` | 不启用 | 忽略缓存，重新抓取 |
| `--check-network` | 不启用 | 仅检查两个数据源，不修改存档 |
| `-h` / `--help` | — | 显示帮助并退出 |

也支持模块入口：`uv run python -m nba_game --help`。

## 5. 输出说明

目录按数据来源组织，仅在对应资源成功保存后才有相应文件：

```text
data/games/0022401196/
├── summary.md           # 中文摘要、缺项和处理建议
├── manifest.json        # 整体与逐资源状态、请求参数、校验信息
└── raw/
    ├── stats/           # NBA Stats 比赛数据，含球队/阵容子目录
    ├── live/            # Live BoxScore 与 Play-by-Play
    └── players/         # 按球员 ID 保存的当前档案
```

`summary.md` 适合快速了解采集情况；`manifest.json` 用于程序读取、复核来源及定位失败资源；`raw/` 保留原始响应，不将 Stats 与 Live 的字段强行合并，也不直接导出 CSV。

可用以下命令读取清单（macOS/Linux 和 PowerShell 均可执行）：

```bash
uv run python -c "import json; from pathlib import Path; p = Path('data/games/0022401196/manifest.json'); m = json.loads(p.read_text(encoding='utf-8')); print(m['game_id'], m['status']); print(m['summary'])"
```

读取原始数据时，将路径换为 `raw/` 下实际存在的 JSON 文件，使用同样的 `json.loads()` 方法即可。

| 状态或退出码 | 含义 |
|---|---|
| `complete` / 退出码 `0` | 本次采集范围内完成，允许存在合法空结果 |
| `partial` / 退出码 `1` | 部分数据、名单覆盖或一致性校验未完成；查看摘要 |
| 退出码 `1` | 也可能是中断或本地文件错误，结合控制台提示判断 |
| 退出码 `2` | 命令行参数错误，例如比赛 ID 不足 10 位 |

资源状态包括成功（`success`）、合法空结果（`empty`）、失败（`failed`）和跳过（`skipped`）。无扣篮或某阵容无投篮等情况可能合法返回空结果，不代表程序出错。

`complete` 表示采集范围完成，**不代表比赛已经结束**。清单中的 `game_status` 为 `1`（未开始）、`2`（进行中）或 `3`（已结束）；暂时无法确定时也可能为 `null`。

## 6. 常见问题

### 找不到 uv 命令

安装后先重新打开终端。macOS/Linux 默认安装路径未加入 `PATH` 时，可在当前会话执行后重试：

```bash
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

Windows 请检查用户 `PATH` 中是否包含 uv 安装目录，然后重新打开 PowerShell。

### 依赖或 Python 下载失败

检查安装网络和终端中的代理配置，再重跑 `uv python install 3.12` 或 `uv sync --locked`；已下载的缓存会被复用。

如果 uv 提示缓存目录不可写，可将缓存改到项目内的可写目录：

```bash
uv --cache-dir ./.uv-cache sync --locked
uv --cache-dir ./.uv-cache run nba-game --help
```

后续 uv 命令同样加上 `--cache-dir ./.uv-cache`。若安装失败源于 Python 版本，确认使用的是仓库默认的 3.12。

### NBA 接口超时、返回 HTML 或 HTTP 错误

先用同一比赛 ID 和同一代理执行 `--check-network`，按结果排查：

| 现象 | 处理方式 |
|---|---|
| 超时或连接失败 | 检查网络、DNS 和代理软件；必要时切换节点，或使用 `--timeout 60` |
| Stats 返回 HTML / 403 | 检查 `stats.nba.com` 的代理路由，切换节点或稍后重试 |
| HTTP 429 | 等待后重跑，避免多个实例并发请求 |
| HTTP 5xx | 上游接口可能暂时异常，稍后重跑；增加超时无法修复 500 |
| 只有 Live 可用 | Stats 仍需单独排查，不能用 CDN 成功推断 Stats 正常 |

两个不同的 Stats 接口连续返回 HTML 时，本轮会暂停后续 Stats 请求并标记为跳过，仍继续处理 Live 数据。网络恢复后重跑原命令即可重新探测和补抓，无需 `--force`。

### 部分失败但已经生成很多文件

保留现有文件，查看 `summary.md` 的缺项和建议。网络或上游恢复后重跑同一命令；部分历史赛季不支持的资源可能持续为空或失败，应以实际清单为准。

### 无法写入文件或找不到输出

确认输出目录可写；可用 `--output-dir ./nba-data` 指向当前目录，或指定可写的绝对路径。从 wheel 等构建包安装时，默认输出位置按包安装路径计算，建议显式传入 `--output-dir`。

项目不监听端口；代理连接失败时，应核对代理软件的实际端口、协议和运行状态。

## 7. 开发与测试

仅运行工具无需安装开发依赖。需要修改代码或验证本地逻辑时，在项目根目录执行：

```bash
uv sync --locked --extra dev
uv run --no-sync pytest -q
```

测试使用模拟传输，不访问 NBA 网络。测试通过表示覆盖到的本地逻辑正常，不能证明 NBA 上游当前可用。

## 8. 必要说明

- **缓存与续跑**：默认复用已结束比赛中校验通过的成功缓存，失败、跳过和空结果下次会重新请求。逐资源保存进度，中断后重跑原命令即可继续。
- **进行中比赛**：不会后台轮询；需要新快照时手动重跑。`complete` 也可能出现在比赛进行中。
- **球员档案**：表示查询时的当前信息，不是比赛发生时的历史档案；档案也会缓存，需要更新时用 `--force`。
- **旧归档导入**：未使用 `--force` 时，自动从输出根目录旁的 `output/<game_id>` 导入校验通过的旧版原始文件。默认对应 `data/output/<game_id>`；保留旧文件，正常采集仍会继续，不是独立离线迁移命令。
- **并发限制**：没有跨进程文件锁，不要对同一比赛、同一输出目录同时运行多个实例；多场采集建议串行，避免触发上游限流。
- **数据范围**：只访问公开接口，保存本次可获取的原始数据；不提供比赛视频、逐帧轨迹或历史球员档案还原。
- **许可与归属**：仓库目前未包含 `LICENSE` 文件，再分发、修改或商用前请确认作者授权。NBA 数据及标识归其权利人所有，使用时请遵守相关服务条款并合理控制请求频率。
