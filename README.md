<p align="center">
  <img src="docs/assets/nba-game-banner.png" alt="NBA GAME · 单场数据采集与归档" width="100%">
</p>

<p align="center">
  <strong>输入一个 10 位比赛 ID。归档一场 NBA 比赛可获取的完整原始数据。</strong>
</p>

<p align="center">
  <a href="https://github.com/luo-qing-xin/NBAGames/actions/workflows/ci.yml"><img src="https://github.com/luo-qing-xin/NBAGames/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <a href="#2-技术栈与运行环境"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.10+"></a>
  <a href="#1-项目介绍"><img src="https://img.shields.io/badge/version-0.2.0-0E7490?style=flat-square" alt="version 0.2.0"></a>
  <a href="#81-包含的接口"><img src="https://img.shields.io/badge/data-NBA%20Stats%20%2B%20Live%20CDN-C9082C?style=flat-square" alt="NBA Stats + Live CDN"></a>
  <a href="#22-运行环境要求"><img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-444444?style=flat-square&amp;logo=linux&amp;logoColor=white" alt="macOS, Linux, Windows"></a>
</p>

<p align="center">
  <a href="#1-项目介绍">项目介绍</a> &nbsp;·&nbsp;
  <a href="#2-技术栈与运行环境">技术栈</a> &nbsp;·&nbsp;
  <a href="#3-项目结构">项目结构</a> &nbsp;·&nbsp;
  <a href="#4-快速开始">快速开始</a> &nbsp;·&nbsp;
  <a href="#5-配置说明">配置说明</a> &nbsp;·&nbsp;
  <a href="#6-使用教程">使用教程</a>
  <br>
  <a href="#7-输出说明">输出说明</a> &nbsp;·&nbsp;
  <a href="#8-采集范围与边界">采集范围</a> &nbsp;·&nbsp;
  <a href="#9-缓存重跑与旧数据迁移">缓存与迁移</a> &nbsp;·&nbsp;
  <a href="#10-常见问题faq">常见问题</a> &nbsp;·&nbsp;
  <a href="#11-开发与测试">开发与测试</a> &nbsp;·&nbsp;
  <a href="#12-许可与数据声明">许可</a>
</p>

---

`nba-game` 是一个 Python 命令行工具：输入 10 位比赛 ID，自动抓取 Stats、Live、五人阵容和球员当前档案，按来源保存原始 JSON，并生成可复核的 `manifest.json` 与中文 `summary.md`。一次命令得到一个可追溯、可断点续跑的单场数据快照。

## 1. 项目介绍

### 1.1 这是什么

`nba-game` 是一个 Python 命令行工具。它会自动完成以下工作：

1. 从 10 位比赛 ID 推导赛季和比赛类型（常规赛、季后赛等）。
2. 调用 NBA Stats 与 NBA Live CDN 的多个官方接口，抓取单场比赛数据。
3. 自动展开双方球队、五人阵容和阵容投篮请求。
4. 对比赛名单中的球员去重，逐个抓取 `CommonPlayerInfo` 当前档案。
5. 按来源保存原始 JSON，并记录请求参数、状态、行数、SHA-256、获取时间等信息。
6. 生成中文摘要，明确列出成功、合法空结果、失败和跳过的资源。

项目采集结果只写入本地文件，不启动 Web 服务，不监听端口，也不需要数据库。

### 1.2 项目解决的问题

| 问题 | 本项目的处理方式 |
|---|---|
| NBA 单场数据分散在多个接口，手工拼装容易漏项 | 用一个命令按固定清单抓取，并自动展开阵容、球员等依赖资源 |
| 直接调用 `nba_api` 需要自己处理会话、代理、限速和重试 | 统一封装 HTTP 会话、浏览器指纹、代理、请求间隔和错误分类 |
| 接口部分失败时，不知道哪些成功、哪些缺失 | `manifest.json` 逐资源记录状态，`summary.md` 用中文说明缺项和排查建议 |
| 重复运行会重复下载，中断后只能从头再来 | 终场有效缓存复用、逐资源原子保存、失败/空结果下次重试 |
| 经过加工的 CSV/DataFrame 丢失原始字段，难以复核 | 保存完整原始 JSON，不裁剪字段，不做无依据的跨源合并 |
| 数据来源和请求参数无法追溯 | 记录 endpoint、parameters、source、sha256、fetched_at 等信息 |

### 1.3 主要功能与特点

- **一条命令完成单场采集**：`uv run nba-game 0022401196`。
- **原始 JSON 保真**：保留 Stats 与 Live 各自的字段、编号、枚举和坐标，不把两个来源强行合并。
- **自动发现依赖资源**：从概要和统计确定球队 ID，从阵容列表确定五人阵容 ID，从名单确定球员 ID。
- **可审计清单**：`manifest.json` 使用 `schema_version: 2`，记录每个资源的请求参数、状态、行数、文件路径、SHA-256 和获取时间。
- **中文缺项说明**：`summary.md` 汇总已获取内容、失败原因和处理建议。
- **缓存与断点续跑**：终场有效数据可复用；每个资源完成后自动写清单；中断后重跑同一命令即可继续。
- **网络鲁棒性**：请求串行、间隔至少 1 秒；对超时、429、5xx 和无效 JSON 最多尝试 2 次；识别 HTML 错误页。
- **代理支持**：支持 HTTP/HTTPS/SOCKS 代理，也支持环境变量或系统代理；不执行 PAC 脚本。
- **明确的退出码**：`0`（范围内完成）、`1`（部分失败/中断）、`2`（命令行参数错误）。
- **旧数据迁移**：首次运行时可从旧版 `data/output/<比赛ID>` 导入校验通过的原始文件。

### 1.4 适用场景

- 对单场比赛做复盘、数据新闻、教学演示或数据源可用性检查。
- 构建单场原始数据集，后续自行解析成 CSV、DataFrame 或数据库。
- 验证 Stats 与 Live 两个来源的比分、投篮数等一致性。
- 需要在网络不稳定或需要代理的环境中可重复地采集同一场比赛。
- 需要保留原始响应和采集痕迹，便于复核和二次处理。

### 1.5 项目边界（不是什么）

- **不是 Web 应用或 HTTP API**：没有前端、没有服务端、没有端口。唯一稳定的使用入口是命令行 `nba-game`。
- **不是实时跟踪服务**：一次命令抓取一个快照；比赛进行中可重复运行更新，但不会后台轮询。
- **不是完整的赛季数据仓库**：没有赛季、生涯、排名、Synergy、赔率、视频等数据。
- **不是数据清洗工具**：只保存原始 JSON 和校验信息，不做业务字段裁剪或分析建模。
- **不是视频/轨迹下载器**：不下载比赛视频，也不包含非公开的逐帧球员和篮球轨迹。

---

## 2. 技术栈与运行环境

### 2.1 技术栈

| 类别 | 技术/依赖 | 说明 |
|---|---|---|
| 编程语言 | Python `>=3.10` | 仓库的 `.python-version` 固定为 `3.12`，uv 会优先使用该版本 |
| 命令行 | 标准库 `argparse` | 入口为 `nba-game`，也支持 `python -m nba_game` |
| NBA Stats | `nba_api==1.11.6` | 提供 Stats 端点类和请求参数构造 |
| NBA Live | `nba_api` 的 Live 模块 + `cdn.nba.com` | 直接读取官方 Live JSON |
| HTTP 会话 | `curl_cffi==0.15.0` | 模拟浏览器 TLS 指纹，负责实际请求 |
| 代理/重试 | `requests>=2.31,<3` + 自定义 `Transport` | 环境/系统代理探测、限速、重试、错误分类 |
| JSON 处理 | 标准库 `json` | 严格序列化，非标准 `NaN`/`Infinity` 转为 `null` |
| 包管理 | `uv` + `uv.lock` | 锁定依赖；构建后端为 `setuptools>=68` |
| 测试 | `pytest>=8,<10`（`dev` extra） | 离线单元测试，不访问网络 |
| 数据存储 | 本地文件系统 | 不使用数据库、消息队列或对象存储 |
| 前端/运行时 | 无 | 不需要 Node.js、CUDA、GPU、Redis 或浏览器 |

`nba_api` 会带入 `pandas`、`numpy` 等传递依赖；`curl_cffi` 会带入 `cffi`、`certifi`、`rich` 等。完整版本以 `uv.lock` 为准。

### 2.2 运行环境要求

| 项目 | 要求 | 说明 |
|---|---|---|
| 操作系统 | macOS、Linux、Windows | 本文命令以 macOS/Linux 为主，Windows 差异单独标注 |
| Python | `>=3.10`，推荐 `3.12` | 使用 uv 时通常无需手动安装 Python |
| uv | 建议使用最新稳定版 | 本文实测版本为 `0.11.8` |
| 网络 | 能访问 PyPI、`stats.nba.com`、`cdn.nba.com` | 首次安装需要 PyPI；采集需要两个 NBA 数据域名 |
| 磁盘 | 约 105 MB 环境 + 每场数 MB 数据 | 另需 Python 与 uv 缓存空间；示例比赛归档约 2 MB |
| 权限 | 输出目录可写 | 程序会自动创建 `<output-dir>/<game_id>` |
| 代理 | 可选 | 在 `stats.nba.com` 不可直连时需要 |
| 其他 | 无 | 无需数据库、模型、CUDA、Node.js、API Key |

### 2.3 外部服务

| 服务 | 用途 | 是否需要账号 |
|---|---|---|
| `https://stats.nba.com/stats/*` | 比赛概要、统计、投篮、阵容、球员档案 | 否 |
| `https://cdn.nba.com/static/json/liveData/*` | Live BoxScore、Live Play-by-Play | 否 |
| PyPI（`https://pypi.org/simple`） | 安装 Python 依赖 | 否 |

这些是公开接口，但可能因地区网络、请求频率或上游故障返回 HTML、403、429、5xx 或空结果。项目会如实记录这些状态，不会把 HTML 错误页当成成功数据。

### 2.4 已验证环境

本文中的安装、测试、网络检查、单场完整采集和构建命令，已在以下环境实际执行：

- macOS（Apple Silicon）
- Python `3.12.13`
- uv `0.11.8`
- `nba_api 1.11.6`、`curl_cffi 0.15.0`、`requests 2.34.2`

Linux 与 Windows 的等价命令已按语义编写，但未在本文环境中逐条执行。

---

## 3. 项目结构

```text
NBAGames/
├── README.md
├── pyproject.toml               # 项目元数据、依赖、CLI 入口、pytest 配置
├── uv.lock                      # uv 锁文件
├── .python-version              # 固定 Python 3.12
├── .gitignore                   # 忽略 .venv、data、缓存等
├── .github/
│   └── workflows/
│       └── ci.yml               # GitHub Actions：多平台离线测试
├── .vscode/
│   └── settings.json            # VS Code 解释器与 pytest 配置
├── docs/
│   └── assets/
│       └── nba-game-banner.png  # README 顶部横幅
├── src/
│   └── nba_game/
│       ├── __init__.py
│       ├── __main__.py          # python -m nba_game 入口
│       ├── cli.py               # argparse、主流程、退出码
│       ├── arguments.py         # 比赛 ID、超时、代理参数校验
│       ├── collector.py         # 资源编排、依赖展开、缓存复用、断点清单
│       ├── models.py            # Resource、GameContext、Response、路径规则
│       ├── sources/
│       │   ├── __init__.py
│       │   ├── stats.py         # Stats 固定端点清单与请求参数
│       │   └── live.py          # Live BoxScore / Play-by-Play 资源
│       ├── transport.py         # HTTP 会话、代理、限速、重试、错误分类
│       ├── storage.py           # 原子写入、SHA-256、缓存读取、旧数据导入
│       ├── validation.py        # 响应身份/结构、阵容、跨源一致性校验
│       ├── reporting.py         # 生成中文 summary.md
│       ├── serialization.py     # 严格 JSON 序列化
│       ├── diagnostics.py       # --check-network 只读诊断
│       └── errors.py            # 异常类型
├── tests/
│   └── test_game.py             # 离线单元测试（使用 FakeTransport）
└── data/                        # 运行时生成，已被 .gitignore 忽略
    ├── games/<game_id>/         # 新版本归档
    └── output/<game_id>/        # 旧版 v1 归档（如果曾经使用旧版本）
```

各模块职责：

| 文件/目录 | 作用 |
|---|---|
| `src/nba_game/cli.py` | 解析参数、创建 `Collector`、打印汇总、把结果映射为退出码 |
| `src/nba_game/__main__.py` | 支持 `python -m nba_game`，与 `nba-game` 走同一流程 |
| `src/nba_game/arguments.py` | 校验比赛 ID 必须为 10 位数字、超时为正数、代理 URL 合法 |
| `src/nba_game/collector.py` | 采集主流程：固定资源 → Live → 球队/阵容 → 阵容投篮 → 球员档案；负责依赖、缓存和清单 |
| `src/nba_game/models.py` | 定义资源身份、比赛上下文、赛季推导、资源键和相对路径 |
| `src/nba_game/sources/stats.py` | 定义 15 个固定 Stats 资源，以及 `TeamDashLineups`、`ShotChartLineupDetail`、`CommonPlayerInfo` 的参数构造 |
| `src/nba_game/sources/live.py` | 定义 Live BoxScore 和 Live Play-by-Play |
| `src/nba_game/transport.py` | `curl_cffi` 会话、代理探测、HTML 错误识别、1 秒间隔、最多 2 次尝试、错误分类 |
| `src/nba_game/storage.py` | 临时文件 + `os.replace` 原子写入、SHA-256、缓存校验、旧 v1 数据导入 |
| `src/nba_game/validation.py` | 比赛/球员身份、结果集结构、阵容 `GP=1`、跨源比分与投篮数等校验 |
| `src/nba_game/reporting.py` | 生成 `summary.md`，包含资源表、缺项原因和建议 |
| `src/nba_game/serialization.py` | 严格 JSON：保留结构，非标准数值转为 `null` |
| `src/nba_game/diagnostics.py` | `--check-network` 的实现，不写入比赛存档 |
| `src/nba_game/errors.py` | 应用异常类型（抓取、校验、存储等） |
| `tests/test_game.py` | 离线测试：缓存、失败隔离、校验、CLI、旧数据迁移等 |
| `pyproject.toml` | 项目名称、版本、依赖、`nba-game` 入口、pytest 配置 |
| `uv.lock` | 依赖锁定；`uv sync` 的依据 |
| `.vscode/settings.json` | 将解释器指向 `.venv/bin/python`，启用 pytest |
| `.github/workflows/ci.yml` | GitHub Actions：Ubuntu/macOS/Windows + Python 3.10/3.12 离线测试 |
| `docs/assets/nba-game-banner.png` | README 顶部横幅（项目原创 PNG 素材） |

`data/`、`.venv/`、`.pytest_cache/`、`.ruff_cache/`、`src/nba_game.egg-info/` 都是运行或安装生成物，不会随仓库提交。

---

## 4. 快速开始

> 以下命令除特别说明外，都在**项目根目录**（包含 `pyproject.toml` 的目录）执行。
>
> Windows 使用 PowerShell 时，路径分隔符可用 `/` 或 `\`，带 `#` 的注释可忽略。

### 4.1 最短流程

如果机器上已经装好 uv，并且网络可以访问 PyPI 与 NBA 数据域名：

```bash
git clone https://github.com/luo-qing-xin/NBAGames.git
cd NBAGames
uv sync --extra dev
uv run nba-game 0022401196
```

如果 `stats.nba.com` 无法直连，先看 [4.6 检查网络与代理](#46-检查网络与代理可选但推荐)，再执行最后一条命令。

### 4.2 前置条件检查

在开始前确认：

- [ ] 有一个可用的终端（macOS/Linux：Terminal；Windows：PowerShell 或 Windows Terminal）。
- [ ] 已安装 `git`，或者可以从 GitHub 下载 ZIP。
- [ ] 已安装 `uv`；没有的话按 4.3 安装。
- [ ] 网络可以访问 PyPI；采集时还需要访问 `stats.nba.com` 和 `cdn.nba.com`。
- [ ] 磁盘至少预留约 300 MB（依赖环境约 105 MB，另含 Python/uv 缓存和单场数据）。
- [ ] 准备一个 10 位比赛 ID，例如 `0022401196`。

**通常不需要**手动安装 Python、Node.js、数据库、CUDA 或任何 API Key。使用 uv 时，Python 版本会由 `.python-version` 自动准备。

### 4.3 安装 uv

macOS / Linux（官方安装脚本）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

macOS 也可以用 Homebrew：

```bash
brew install uv
```

Windows PowerShell：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装后重新打开终端，确认：

```bash
uv --version
```

如果提示 `uv: command not found`，macOS/Linux 可把安装目录加入 PATH：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

并把这一行写入 `~/.zshrc` 或 `~/.bashrc` 后重新打开终端。Windows 请关闭并重新打开 PowerShell。

### 4.4 获取项目代码

```bash
git clone https://github.com/luo-qing-xin/NBAGames.git
cd NBAGames
```

确认当前目录正确：

```bash
# macOS / Linux
ls pyproject.toml

# Windows PowerShell
Get-ChildItem pyproject.toml
```

如果不用 git，也可以在 GitHub 页面下载 ZIP，解压后进入解压出的 `NBAGames` 目录。后续命令相同。

> **重要**：`uv sync`、`uv run` 都应在项目根目录执行，不要在 `src/`、`data/` 或 `.venv/` 中执行。

### 4.5 安装依赖

在项目根目录执行：

```bash
uv sync --extra dev
```

这条命令会：

1. 读取 `.python-version`，准备 Python 3.12（本机没有时会自动下载）。
2. 在项目根目录创建 `.venv/` 虚拟环境。
3. 按 `uv.lock` 安装运行依赖和 `dev` extra（`pytest`）。
4. 默认以 editable 方式安装本项目，使 `nba-game` 命令可用。

如果本机没有 Python 3.12，且网络无法访问 uv 的 Python 安装包下载源，`uv sync` 可能无法自动准备解释器。此时请先手动安装 Python 3.12，再重新执行 `uv sync --extra dev`。

如果只运行采集、不跑测试，可以用更小的安装：

```bash
uv sync
```

验证安装：

```bash
uv run python -V
uv run nba-game --help
```

预期看到 Python `3.12.x` 和以下帮助信息（节选）：

```text
usage: nba-game [-h] [--output-dir OUTPUT_DIR] [--proxy PROXY]
                [--timeout TIMEOUT] [--force] [--check-network]
                game_id

抓取单场 NBA 全部基础、扩展数据及球员当前档案，仅保存原始 JSON。
```

也可以用模块形式，效果相同：

```bash
uv run python -m nba_game --help
```

#### 可选：手动激活虚拟环境

使用 `uv run` 时**不需要**激活虚拟环境。如果希望在当前 shell 中直接运行 `nba-game` 或 `pytest`，可以激活：

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows cmd
.venv\Scripts\activate.bat
```

激活后命令前可以不加 `uv run`，例如：

```bash
nba-game --help
pytest -q
```

### 4.6 检查网络与代理（可选但推荐）

第一次采集前，建议先做只读检查：

```bash
uv run nba-game 0022401196 --check-network
```

正常输出：

```text
NBA Stats：可用（JSON 与比赛 ID 校验通过）
NBA Live CDN：可用（JSON 与比赛 ID 校验通过）
网络检查完成，未修改任何比赛存档。
```

`--check-network` 只请求 Stats 概要和 Live BoxScore 两个接口，用于验证路由和响应结构，**不会创建或修改比赛存档**。

如果 `NBA Stats` 不可用，但 `NBA Live CDN` 可用，通常是 `stats.nba.com` 的访问问题。使用代理重试：

```bash
uv run nba-game 0022401196 --proxy http://127.0.0.1:7890 --check-network
```

把 `127.0.0.1:7890` 换成你实际代理软件的主机和端口。

也可以使用环境变量。

macOS / Linux：

```bash
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
```

Windows PowerShell：

```powershell
$env:HTTPS_PROXY = "http://127.0.0.1:7890"
$env:HTTP_PROXY = "http://127.0.0.1:7890"
```

然后再运行 `uv run nba-game 0022401196 --check-network`。如果两个来源都不可用，请先检查本机网络、代理端口和代理软件状态；代理的具体配置见 [5.3 代理与环境变量](#53-代理与环境变量)。

### 4.7 第一次采集

在项目根目录执行：

```bash
uv run nba-game 0022401196
```

比赛 ID 必须是**恰好 10 位数字**，并且保留前导零。它可以从 NBA.com 的比赛页 URL、记分板或数据页中获得，例如 URL 末尾的 `0022401196`。常见前缀：

- `002`：常规赛
- `004`：季后赛
- `003`：全明星
- `001`：季前赛
- `005`：附加赛（Play-In）

（赛季和比赛类型由程序根据 ID 自动推导，无需额外传入。）

采集过程会逐条打印正在抓取的资源。由于请求串行且间隔至少 1 秒，一场已完赛比赛通常需要 **1～3 分钟**，请求数随阵容和球员数量变化，通常在 80 个左右。

示例输出（数字随比赛变化）：

```text
正在抓取：box_score_summary_v3
...
比赛接口：45/49；球员档案：37/37
合法空结果：dunk_score_leaders, shot_chart_lineup_detail:...
官方 Live 数据已保存：live_box_score, live_play_by_play
抓取完成：/path/to/NBAGames/data/games/0022401196
```

说明：

- `45/49` 表示 49 个比赛资源中 45 个返回非空数据；另外 4 个是**合法空结果**，不是失败。
- `球员档案：37/37` 表示名单中的 37 名球员都成功获取当前档案。
- `官方 Live 数据已保存` 是提示信息，不代表 Stats 失败。

默认输出到：

```text
<项目根目录>/data/games/0022401196/
```

全新 clone 中没有 `data/` 目录；首次运行会自动创建。

也可以自定义根目录（程序会自动追加比赛 ID）：

```bash
uv run nba-game 0022401196 --output-dir ./my-data
```

### 4.8 验证项目是否成功运行

#### 1. 检查退出码

```bash
# macOS / Linux
echo $?

# Windows PowerShell
echo $LASTEXITCODE
```

- `0`：范围内采集完成（允许存在合法空结果）。
- `1`：部分资源失败、名单不完整、一致性校验失败或运行被中断。成功的结果仍会保存。
- `2`：命令行参数错误，例如比赛 ID 不是 10 位数字、代理 URL 没有端口、超时时间不是正数。

#### 2. 检查输出目录

```bash
# macOS / Linux
ls data/games/0022401196

# Windows PowerShell
Get-ChildItem data\games\0022401196
```

应能看到：

```text
manifest.json
summary.md
raw/
```

#### 3. 查看中文摘要

```bash
# macOS / Linux
cat data/games/0022401196/summary.md

# Windows PowerShell
Get-Content data\games\0022401196\summary.md
```

#### 4. 用 Python 读取清单

```bash
uv run python -c "import json; m=json.load(open('data/games/0022401196/manifest.json', encoding='utf-8')); print(m['status'], m['game_status'], m['season'], m['summary']['game_resources_succeeded'], m['summary']['game_resources_expected'])"
```

示例比赛的预期输出（实际数字随比赛不同）：

```text
complete 3 2024-25 45 49
```

各字段含义：

- `complete`：本次范围内完成；`partial` 表示有缺项。
- `3`：比赛已结束（`1` 未开始、`2` 进行中）。
- `2024-25`：自动推导的赛季。
- `45 49`：非空成功的比赛资源数 / 计划采集的比赛资源数。

**成功标准**：退出码为 `0`，`manifest.json` 中 `status` 为 `complete`，`summary.md` 存在且能打开，`raw/` 下有实际 JSON 文件。即使 `complete`，也可能有个别“合法空结果”（例如某场比赛没有扣篮记录），这是正常的。

如果退出码为 `1`，先不要删除已有文件；打开 `summary.md` 查看“缺项与处理建议”，再按 [10. 常见问题](#10-常见问题faq) 排查，或直接重跑同一命令补抓。

---

## 5. 配置说明

### 5.1 配置方式

项目**没有运行配置文件**，也**不使用 `.env`**，不需要 API Key。所有运行配置都通过命令行参数传入；代理还可以通过环境变量或系统代理提供。

这意味着：

- 不需要复制或修改任何配置模板。
- 不需要设置数据库连接、模型路径或密钥。
- 需要改变输出目录、超时、代理或缓存行为时，直接改命令参数即可。
- 每次运行的参数会记录在 `manifest.json` 的 `request_options` 中（代理只记录是否配置，不记录 URL 和凭据）。

### 5.2 命令行参数

```text
usage: nba-game [-h] [--output-dir OUTPUT_DIR] [--proxy PROXY]
                [--timeout TIMEOUT] [--force] [--check-network]
                game_id
```

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `game_id` | 是 | 无 | 10 位 ASCII 数字，保留前导零，例如 `0022401196` |
| `--output-dir` | 否 | 项目根目录下的 `data/games` | 输出根目录；最终路径为 `<output-dir>/<game_id>` |
| `--proxy` | 否 | 环境变量/系统代理 | HTTP/HTTPS/SOCKS 代理 URL，必须包含主机和端口 |
| `--timeout` | 否 | `30` | **单次请求**超时秒数，必须是有限正数；不是总耗时 |
| `--force` | 否 | 关闭 | 忽略所有缓存，重新抓取全部比赛资源和球员档案；同时跳过旧数据导入 |
| `--check-network` | 否 | 关闭 | 只检查 Stats 与 Live 是否返回有效 JSON，不写入比赛存档 |
| `-h`, `--help` | 否 | 无 | 显示帮助并退出 |

示例：

```bash
# 自定义输出根目录，最终写到 ./my-data/0022401196
uv run nba-game 0022401196 --output-dir ./my-data

# 使用代理并延长单次请求超时
uv run nba-game 0022401196 --proxy http://127.0.0.1:7890 --timeout 60

# 强制刷新全部资源（包括球员当前档案）
uv run nba-game 0022401196 --force

# 只检查网络，不写入存档
uv run nba-game 0022401196 --check-network
```

参数校验规则：

- 比赛 ID：必须匹配 `^[0-9]{10}$`，不能是 9 位、11 位或带字母。
- 超时：必须是正数且有限，例如 `30`、`45.5`；`0`、负数、`NaN` 不合法。
- 代理：必须包含 scheme、主机和端口；支持 `http`、`https`、`socks4`、`socks4a`、`socks5`、`socks5h`。

### 5.3 代理与环境变量

| 名称 | 类型 | 作用 | 示例 |
|---|---|---|---|
| `--proxy` | CLI 参数 | 显式指定代理，优先级最高 | `--proxy http://127.0.0.1:7890` |
| `HTTPS_PROXY` | 环境变量 | 为 HTTPS 请求提供代理 | `http://127.0.0.1:7890` |
| `HTTP_PROXY` | 环境变量 | 为 HTTP 请求提供代理 | `http://127.0.0.1:7890` |
| `ALL_PROXY` | 环境变量 | 通用代理回退 | `socks5h://127.0.0.1:7890` |
| `NO_PROXY` | 环境变量 | 自动探测代理时绕过指定主机 | `stats.nba.com,cdn.nba.com` |
| `UV_CACHE_DIR` | 环境变量 | 改变 uv 缓存目录（用于安装排障，不是本项目参数） | `$HOME/.cache/uv-nba` |

代理行为说明：

1. 传入 `--proxy` 时，使用该代理，不再查询环境/系统代理。
2. 未传 `--proxy` 时，程序通过 `requests` 的机制读取环境变量或系统代理，并应用 `NO_PROXY` 绕过规则。
3. 不执行 PAC 脚本。
4. 代理 URL 中的用户名和密码可以使用，但不会写入 `manifest.json`；清单只记录 `proxy_configured: true/false`。
5. 如果代理软件没有启动、端口写错或只支持 HTTP 而写成了 SOCKS，`--check-network` 会明确显示不可用。

**安全提示**：不要在 README、脚本、提交记录或公开 Issue 中写真实代理密码。需要凭据时，使用环境变量或本机未提交的 shell 配置；不要把凭据放在命令历史中。

### 5.4 输出路径规则

- 最终输出目录始终是 `<output-dir>/<game_id>`。
- 相对路径相对于**当前工作目录**，不是相对于项目根目录。
- 输出目录不存在时会自动创建，无需手动 `mkdir`。
- 默认值由包文件位置计算：使用 `uv sync` 的源码检出方式时，默认是**项目根目录**下的 `data/games`。
- 如果以非 editable 方式安装（例如从构建出的 wheel 安装），默认目录可能落在安装位置而非项目根目录。此时请显式指定，例如：

```bash
uv run nba-game 0022401196 --output-dir /绝对路径/NBAGames/data/games
```

旧版数据导入时，如果使用自定义输出根目录 `<root>`，程序会在 `<root>/../output/<game_id>` 查找旧文件；默认根目录对应的旧位置是 `data/output/<game_id>`。

### 5.5 退出码

| 退出码 | 含义 | 典型场景 |
|---:|---|---|
| `0` | 范围内完成 | 所有计划资源为 `success` 或 `empty`，名单完整，校验通过 |
| `1` | 部分完成/失败/中断 | 有 `failed`/`skipped` 资源、名单不完整、校验失败、Ctrl+C |
| `2` | 参数错误 | 比赛 ID 不是 10 位数字、代理 URL 非法、超时不是正数 |

`--check-network` 使用不同的语义：两个来源都可用返回 `0`，任一不可用返回 `1`。

### 5.6 敏感信息与文件

- 项目不需要密码、Token、API Key 或数据库连接串。
- `manifest.json` 不保存代理 URL 和凭据，只保存 `proxy_configured` 布尔值。
- `.gitignore` 已忽略 `.env`、`.env.local` 等本地配置（`.env.example` 除外）、`.venv/`、`data/`；但本项目并不读取 `.env`，不要误以为放入 `.env` 就会生效。
- 如自行封装脚本，请把凭据放在环境变量或本机配置中，并避免提交。
- 采集结果版权归 NBA 及数据提供方所有；公开或商用前请确认授权和使用条款。

---

## 6. 使用教程

### 6.1 采集并查看摘要

最简使用：

```bash
uv run nba-game 0022401196
```

采集完成后查看摘要：

```bash
cat data/games/0022401196/summary.md
```

摘要包含：

- 本次状态（范围内采集完成、部分完成、已中断）。
- 比赛资源成功数、合法空结果数、球员档案成功数。
- 每个资源的状态、记录数和文件链接或失败原因。
- 缺项与处理建议。
- 一致性检查结果。
- 范围边界说明。

摘要中的状态标签：

| 标签 | 含义 |
|---|---|
| 成功 | 返回非空数据，且通过身份/结构校验 |
| 合法空结果 | 结构合法但没有记录，例如某场没有扣篮数据 |
| 失败 | 请求或校验失败；清单会标记 `retained_previous_file`（如果旧文件存在），摘要会说明旧文件位置 |
| 跳过 | 依赖缺失，或 Stats 暂停后未请求 |

示例片段（不同比赛内容不同）：

```text
|资源|状态|记录数|文件／原因|
|---|---|---:|---|
|box_score_summary_v3|成功|1|[raw/stats/box_score_summary_v3.json](raw/stats/box_score_summary_v3.json)|
|game_rotation|失败|—|NBA API 返回 HTTP 500|
|dunk_score_leaders|合法空结果|0|[raw/stats/dunk_score_leaders.json](raw/stats/dunk_score_leaders.json)|
```

### 6.2 读取原始 JSON

所有数据都在 `raw/` 下，按来源分目录：

- `raw/stats/`：NBA Stats 接口。
- `raw/live/`：NBA Live CDN 接口。
- `raw/players/`：球员当前档案。

不同接口的顶层结构不同，常见如下：

| 文件 | 顶层字段/结构 | 内容 |
|---|---|---|
| `raw/stats/box_score_summary_v3.json` | `boxScoreSummary` | 比赛概要、场馆、裁判、比分、名单等 |
| `raw/stats/box_score_traditional_v3.json` | `boxScoreTraditional` | 双方球员传统统计 |
| `raw/stats/box_score_advanced_v3.json` | `boxScoreAdvanced` | 高级统计 |
| `raw/stats/box_score_four_factors_v3.json` | `boxScoreFourFactors` | 四要素 |
| `raw/stats/box_score_misc_v3.json` | `boxScoreMisc` | 杂项统计 |
| `raw/stats/box_score_scoring_v3.json` | `boxScoreScoring` | 得分方式 |
| `raw/stats/box_score_usage_v3.json` | `boxScoreUsage` | 使用率 |
| `raw/stats/box_score_player_track_v3.json` | `boxScorePlayerTrack` | 追踪汇总 |
| `raw/stats/box_score_hustle_v2.json` | `boxScoreHustle` | 拼抢数据 |
| `raw/stats/box_score_matchups_v3.json` | `boxScoreMatchups` | 对位数据 |
| `raw/stats/box_score_defensive_v2.json` | `boxScoreDefensive` | 防守数据 |
| `raw/stats/play_by_play_v3.json` | `game.actions` | Stats 逐回合 |
| `raw/stats/shot_chart_detail.json` | `resultSets`（`Shot_Chart_Detail` 等） | 投篮明细 |
| `raw/stats/game_rotation.json` | `resultSets`（`AwayTeam`、`HomeTeam`） | 轮换 |
| `raw/stats/team_dash_lineups/<球队ID>.json` | `resultSets`（`Overall`、`Lineups`） | 球队五人阵容 |
| `raw/stats/shot_chart_lineup_detail/<球队ID>/<阵容ID>.json` | `resultSets`（`ShotChartLineupDetail`） | 单个阵容的投篮 |
| `raw/stats/dunk_score_leaders.json` | `dunks` | 本场扣篮 |
| `raw/live/live_box_score.json` | `game` | Live 技术统计 |
| `raw/live/live_play_by_play.json` | `game.actions` | Live 逐回合 |
| `raw/players/<球员ID>.json` | `resultSets`（`CommonPlayerInfo` 等） | 球员当前档案 |

一个可直接运行的解析示例（macOS/Linux）：

```bash
uv run python - <<'PY'
import json
from pathlib import Path

game_dir = Path("data/games/0022401196")
manifest = json.loads((game_dir / "manifest.json").read_text(encoding="utf-8"))
print(manifest["status"], manifest["game_status"], manifest["season"])
print("resources:", manifest["summary"]["game_resources_succeeded"], "/", manifest["summary"]["game_resources_expected"])

box = json.loads(
    (game_dir / "raw/stats/box_score_traditional_v3.json").read_text(encoding="utf-8")
)
for side in ("homeTeam", "awayTeam"):
    team = box["boxScoreTraditional"][side]
    print(team["teamTricode"], team["statistics"]["points"])
PY
```

示例比赛 `0022401196` 的预期输出：

```text
complete 3 2024-25
resources: 45 / 49
NOP 100
OKC 115
```

Windows PowerShell 不支持 `<<` heredoc。可以把上面的 Python 代码保存为 `inspect_game.py`，然后执行：

```powershell
uv run python inspect_game.py
```

也可以直接在 Python REPL 中逐行粘贴（去掉 heredoc 的起止行）。

**注意**：JSON 是接口原始结构，字段名以 NBA 返回为准；上面的顶层字段表是定位入口，不代表所有字段都存在于每场比赛。项目不会用 DataFrame 解析器裁剪字段。

### 6.3 常用操作

以下命令都在项目根目录执行：

| 目的 | 命令 |
|---|---|
| 采集一场比赛 | `uv run nba-game 0022401196` |
| 查看帮助 | `uv run nba-game --help` |
| 模块方式运行 | `uv run python -m nba_game 0022401196` |
| 输出到自定义目录 | `uv run nba-game 0022401196 --output-dir ./my-data` |
| 使用代理 | `uv run nba-game 0022401196 --proxy http://127.0.0.1:7890` |
| 延长单次超时 | `uv run nba-game 0022401196 --timeout 60` |
| 强制刷新全部数据 | `uv run nba-game 0022401196 --force` |
| 仅检查网络 | `uv run nba-game 0022401196 --check-network` |
| 中断后继续 | 重新执行同一条采集命令即可 |
| 检查 Python 版本 | `uv run python -V` |

### 6.4 比赛进行中

比赛未结束时，`gameStatus` 为 `1`（未开始）或 `2`（进行中）。此时：

- 可以重复运行同一命令，每次得到一个当前快照。
- 比赛资源会刷新，不会把进行中的缓存当作终场数据。
- 程序不会后台轮询；如需持续更新，请自行用 cron、任务计划程序或脚本按合理间隔重复调用，并注意请求频率。
- `manifest.json` 的 `status` 表示“本次采集范围内是否完成”，不等同于“比赛是否结束”；请结合 `game_status` 判断。

比赛结束后（`gameStatus` 为 `3`），有效缓存可以被后续运行复用；第一次确认终场时，程序会刷新其余比赛数据。

### 6.5 批量采集（可选）

项目没有内置批量命令，但可以在 shell 中串行循环。**不要并发运行多个实例**（原因见 [9.4 并发与文件锁](#94-并发与文件锁)）。

macOS / Linux：

```bash
for id in 0022401196 0022500094; do
  uv run nba-game "$id" || echo "未完成：$id，请查看对应 summary.md"
done
```

Windows PowerShell：

```powershell
foreach ($id in "0022401196", "0022500094") {
  uv run nba-game $id
  if ($LASTEXITCODE -ne 0) { Write-Host "未完成：$id" }
}
```

每次运行都会独立校验退出码；不要把某一场的失败当成整个循环必须停止的理由，也不要为了“补齐”而对同一场立即反复重试。

### 6.6 是否提供 API 或 Web 界面

不提供 HTTP API、Web UI 或常驻服务。稳定入口只有：

```bash
nba-game <game_id> [options]
```

`nba_game.collector.Collector` 是内部实现类，测试脚本会直接使用它，但它不是稳定的公共 API；后续版本可能调整其构造参数和返回值。需要程序化调用时，推荐把 CLI 当作子进程调用，并检查退出码。

---

## 7. 输出说明

### 7.1 目录结构

以 `0022401196` 为例：

```text
data/games/0022401196/
├── manifest.json
├── summary.md
└── raw/
    ├── stats/
    │   ├── box_score_summary_v3.json
    │   ├── box_score_traditional_v3.json
    │   ├── play_by_play_v3.json
    │   ├── ...（其余固定 Stats 文件）
    │   ├── team_dash_lineups/
    │   │   ├── 1610612740.json
    │   │   └── 1610612760.json
    │   └── shot_chart_lineup_detail/
    │       ├── 1610612740/
    │       │   └── <GROUP_ID>.json
    │       └── 1610612760/
    │           └── ...
    ├── live/
    │   ├── live_box_score.json
    │   └── live_play_by_play.json
    └── players/
        ├── 203468.json
        ├── 203482.json
        └── ...（名单中每个球员一个文件）
```

说明：

- 固定 Stats 资源共 15 个；某场接口失败时对应文件可能不存在，状态会记录在 `summary.md` 和 `manifest.json` 中。
- `team_dash_lineups/` 按球队 ID 命名，通常是 2 个文件。
- `shot_chart_lineup_detail/` 先按球队 ID 分目录，再按五人阵容 `GROUP_ID` 命名；`GROUP_ID` 形如 `-1630283-1630631-...-`，文件名直接使用该值，数量取决于该场实际使用的阵容。
- `players/` 按球员 ID 命名；只包含本场传统统计、概要未激活名单和 Live 名单中出现过的球员。
- `raw/` 下的文件名是固定的资源名，便于脚本按名称读取。

### 7.2 `manifest.json`

`manifest.json` 是机器可读的采集清单，`schema_version` 为 `2`。主要字段：

| 字段 | 说明 |
|---|---|
| `schema_version` | 清单结构版本，当前为 `2` |
| `game_id` | 比赛 ID |
| `season` / `season_type` | 自动推导的赛季和比赛类型 |
| `status` | `running`、`complete`、`partial`、`interrupted` |
| `game_status` | `1` 未开始、`2` 进行中、`3` 已结束；未知时为 `null` |
| `started_at` / `updated_at` / `finished_at` | UTC 时间戳 |
| `versions` | 本次运行使用的 `nba_api`、`curl_cffi`、`nba-game` 版本 |
| `request_options` | 超时秒数、是否配置代理（不记录代理 URL/凭据） |
| `team_ids` | 解析出的双方球队 ID |
| `resources` | 以资源键为键的逐资源记录 |
| `profiles` | 球员 ID、名单是否完整、档案说明 |
| `checks` | 一致性检查结果 |
| `summary` | 资源计数和失败/空结果列表 |

`resources` 中每个资源的常见字段：

| 字段 | 说明 |
|---|---|
| `endpoint` | 请求的接口地址 |
| `source` | `nba_stats` 或 `nba_live_cdn` |
| `parameters` | 实际请求参数 |
| `resource` | 资源名 |
| `team_id` / `group_id` | 动态资源的球队/阵容 ID |
| `status` | `success`、`empty`、`failed`、`skipped` |
| `attempts` | 实际请求次数（0 表示未请求） |
| `cache_hit` | 是否复用缓存 |
| `fetched_at` | 数据获取时间 |
| `row_count` | 记录数（合法空结果为 0） |
| `file` | 相对比赛目录的文件路径 |
| `sha256` | 文件内容哈希 |
| `game_status_at_fetch` | 获取时的比赛状态 |
| `error` | 失败/跳过原因（分类后的信息） |
| `retained_previous_file` | 刷新失败时保留的旧文件路径 |
| `migration` | 从旧版导入时的来源文件和导入时间 |

资源键的格式：

- 固定资源：`box_score_summary_v3`
- 球队阵容：`team_dash_lineups:<球队ID>`
- 阵容投篮：`shot_chart_lineup_detail:<球队ID>:<GROUP_ID>`
- 球员档案：`common_player_info:<球员ID>`

结构示例（省略了大部分资源；统计数字和球员列表来自 `0022401196` 的一次完整采集，实际以文件为准）：

```json
{
  "schema_version": 2,
  "game_id": "0022401196",
  "season": "2024-25",
  "season_type": "Regular Season",
  "status": "complete",
  "game_status": 3,
  "versions": {
    "nba_api": "1.11.6",
    "curl_cffi": "0.15.0",
    "nba-game": "0.2.0"
  },
  "request_options": {
    "timeout_seconds": 30.0,
    "proxy_configured": true
  },
  "profiles": {
    "person_ids": [
      203468, 203482, 203901, 1627749, 1627936, 1628392, 1628971, 1628983,
      1629026, 1629627, 1629652, 1630198, 1630283, 1630526, 1630527, 1630529,
      1630530, 1630598, 1630631, 1631096, 1631114, 1631119, 1631172, 1631232,
      1631255, 1631288, 1631311, 1641717, 1641722, 1641745, 1641794, 1641810,
      1642260, 1642274, 1642349, 1642382, 1642505
    ],
    "roster_complete": true,
    "note": "CommonPlayerInfo 是抓取时的当前档案，并非历史比赛时的档案。"
  },
  "resources": {
    "box_score_summary_v3": {
      "source": "nba_stats",
      "status": "success",
      "row_count": 1,
      "file": "raw/stats/box_score_summary_v3.json",
      "sha256": "<文件哈希>",
      "cache_hit": false,
      "attempts": 1,
      "fetched_at": "<ISO 8601 时间>",
      "game_status_at_fetch": 3
    }
  },
  "checks": [
    {"name": "score:box_score_summary_v3:homeTeam", "status": "passed"}
  ],
  "summary": {
    "game_resources_expected": 49,
    "game_resources_succeeded": 45,
    "game_resources_empty": 4,
    "profiles_expected": 37,
    "profiles_succeeded": 37,
    "failed_resources": [],
    "empty_resources": [
      "dunk_score_leaders",
      "shot_chart_lineup_detail:1610612760:-1629026-1630198-1642349-1642382-1642505-",
      "shot_chart_lineup_detail:1610612760:-1630198-1630598-1642349-1642382-1642505-",
      "shot_chart_lineup_detail:1610612760:-1630198-1641745-1641794-1642382-1642505-"
    ],
    "failed_checks": []
  }
}
```

### 7.3 `summary.md`

面向人的中文摘要，包含：

- 状态和资源计数。
- 每个资源的表格：状态、记录数、文件链接或失败原因。
- “缺项与处理建议”：按错误类型给出下一步。
- “一致性检查”：跨来源比分、球队、投篮数等检查结果。
- “范围边界”：明确本次包含和不包含的内容。
- 如果球员名单不完整或运行中断，会额外提示。

当某次刷新失败但旧文件仍在时，摘要会说明旧文件位置，并明确“不能视为本次成功结果”。

### 7.4 状态、完成度与退出码

**比赛状态 `game_status`：**

| 值 | 含义 |
|---:|---|
| `1` | 未开始 |
| `2` | 进行中 |
| `3` | 已结束 |
| `null` | 无法从响应确认 |

**资源状态 `resources.*.status`：**

| 值 | 含义 | 是否计入非空成功 |
|---|---|---:|
| `success` | 返回非空记录并通过校验 | 是 |
| `empty` | 结构合法但没有记录 | 否 |
| `failed` | 请求或校验失败 | 否 |
| `skipped` | 依赖缺失、Stats 暂停或中断未执行 | 否 |

**整体状态 `status`：**

| 值 | 含义 |
|---|---|
| `running` | 正在采集（清单会实时更新） |
| `complete` | 计划内资源均为 `success`/`empty`，名单完整，校验未失败 |
| `partial` | 存在失败、跳过、名单不完整、校验失败或运行错误 |
| `interrupted` | 被 Ctrl+C 中断；已完成的资源保留 |

`complete` 只表示**约定的单场范围内**完成，不代表 NBA 所有端点、所有字段都可用。合法空结果不会导致 `partial`。

---

## 8. 采集范围与边界

### 8.1 包含的接口

每场比赛会尝试以下 Stats 接口（固定 15 个）：

| 类别 | 接口 | 说明 |
|---|---|---|
| 比赛概要与传统统计 | `BoxScoreSummaryV3`、`BoxScoreTraditionalV3` | 场馆、裁判、比分、名单、球员传统统计 |
| 逐事件 | `PlayByPlayV3` | Stats 逐回合，保留 `actions` 原始字段 |
| 高级统计 | `BoxScoreAdvancedV3`、`BoxScoreFourFactorsV3`、`BoxScoreMiscV3`、`BoxScoreScoringV3`、`BoxScoreUsageV3` | 高级效率、四要素、杂项、得分方式、使用率 |
| 追踪与防守 | `BoxScorePlayerTrackV3`、`BoxScoreHustleV2`、`BoxScoreMatchupsV3`、`BoxScoreDefensiveV2` | 跑动/触球、拼抢、对位、防守 |
| 投篮与轮换 | `ShotChartDetail`（FGA）、`GameRotation` | 投篮明细、轮换 |
| 扣篮 | `DunkScoreLeaders` | 限定为当前比赛；部分赛季可能为空或不支持 |

此外还会抓取：

| 类别 | 来源/接口 | 说明 |
|---|---|---|
| Live 技术统计 | NBA Live CDN `BoxScore` | 每场都尝试，不以 Stats 失败为前提 |
| Live 逐回合 | NBA Live CDN `PlayByPlay` | 与 Stats 逐回合分开保存 |
| 球队五人阵容 | `TeamDashLineups` | 双方各一次；`GROUP_QUANTITY=5`、`Base`、`Totals` |
| 阵容投篮 | `ShotChartLineupDetail` | 按实际 `GROUP_ID` 逐阵容请求（FGA） |
| 球员当前档案 | `CommonPlayerInfo` | 对传统统计、概要未激活名单、Live 名单中的球员 ID 去重后请求 |

### 8.2 不包含的内容

默认范围**不包含**：

- 赛季、生涯、排名等背景数据。
- Synergy 战术汇总。
- 赛季型 `PlayerDashPt` 数据。
- 视频下载。
- 赔率数据。
- 非公开的逐帧球员和篮球轨迹。
- 已退役的旧版本接口。
- 自动后台轮询、定时任务或通知服务。
- CSV/DataFrame/数据库导出。

`BoxScorePlayerTrackV3` 提供的是单场汇总，不能替代逐帧轨迹。需要这些额外数据时，应另行设计采集流程，而不是假设本项目已经覆盖。

### 8.3 原始保真与校验

- 完整保存每个接口的 JSON 响应，不依赖 DataFrame 解析器裁剪字段。
- 额外结果集（例如投篮接口中的联盟均值）保留在原文件内，但不会被误当作本场投篮。
- Stats 和 Live 的动作字段、编号、枚举和坐标分别保留，不做无依据的跨源合并。
- JSON 中缺字段、`null`、空字符串和 `0` 保持区别；非标准 `NaN`/`Infinity` 转为 `null`。
- 校验包括：
  - 比赛/球员身份和参数回显。
  - 阵容的 `GP=1`、球队参数回显。
  - 阵容投篮的比赛/球队/阵容身份。
  - 终场跨源比分、球队 ID。
  - `ShotChartDetail` 出手数与传统统计 FGA。
  - 高级统计关键字段是否存在。
- 跨源修订可能造成差异；终场校验发现这类差异时，会列为校验失败并使整体变为 `partial`，而不是静默覆盖。

### 8.4 “完整”的准确含义

README 中的“完整”仅指：**上述约定接口范围内，该次采集和校验完成**。

它不代表：

- `nba_api` 的所有端点都可用。
- 每个字段在每场比赛中都存在。
- 上游不会返回空结果或错误。
- 球员档案反映比赛发生时的历史状态。

`CommonPlayerInfo` 是**获取时的当前档案**，不保证反映历史比赛时的球队、号码或状态。这是接口本身的性质，不是缓存问题。

---

## 9. 缓存、重跑与旧数据迁移

### 9.1 缓存规则

| 情况 | 行为 |
|---|---|
| 比赛已结束，缓存有效且非空 | 可复用，`cache_hit: true`，不重复请求 |
| 比赛进行中/未结束 | 刷新比赛资源，得到新的快照 |
| 第一次确认比赛终场 | 刷新其余比赛数据，使终场数据完整 |
| 资源状态为 `failed`、`skipped` 或 `empty` | 不复用，下次运行重新尝试 |
| `--force` | 忽略全部缓存，重新抓取比赛资源和球员档案 |
| 文件哈希与清单不一致 | 视为无效缓存，重新抓取 |
| 清单缺失但原始文件存在 | 尝试从原始 JSON 重建清单；必要时重新抓取 |
| 球员档案 | 独立缓存；与比赛是否终场无关，`--force` 可更新 |

缓存复用的前提是文件存在、身份/结构校验通过、SHA-256 匹配（如果清单有记录），并且比赛状态允许。程序不会把失败或空结果当成完整数据复用。

### 9.2 中断与断点续跑

- 每个资源完成后，程序会原子写入 JSON，并更新 `manifest.json`。
- 原子写入使用同目录临时文件 + `os.replace`，避免留下半截 JSON。
- 按 `Ctrl+C` 时，已完成资源保留，清单标记为 `interrupted`，退出码 `1`。
- 重新执行**同一条命令**即可继续；已成功且可复用的资源会跳过。
- 一般不需要 `--force`；只有确实要丢弃缓存、重新拉取时才使用。
- 失败刷新时，如果旧文件存在，旧文件会保留，并在清单中标记 `retained_previous_file`，不会把旧数据冒充成本次成功。

### 9.3 旧版本数据迁移

包名已从 `nba_pbp` 改为 `nba_game`。旧命令 `nba-pbp`、旧的球员独立命令和 `src/fetch_game.py` 不再提供，统一使用 `nba-game`。如果环境中还装过旧包，建议重新创建 `.venv` 或显式卸载旧包，避免旧入口残留。

旧版 v1 数据通常位于：

```text
data/output/<game_id>/
├── manifest.json
├── raw/*.json
└── profiles/*.json
```

新版本默认写入：

```text
data/games/<game_id>/
```

首次正常采集（未使用 `--force`）时，程序会：

1. 在默认位置查找 `data/output/<game_id>`；如果使用自定义输出根目录 `<root>`，则查找 `<root>/../output/<game_id>`。
2. 校验旧文件的来源、比赛 ID、结构和 SHA-256（如果旧清单有记录）。
3. 把校验通过的原始文件复制到新目录，保留原获取时间和迁移信息。
4. 不删除旧目录，便于回滚和对照。
5. 已有有效的新文件优先；`--force` 跳过导入并直接重新抓取。

以下旧目录**不会**自动混入新归档：

```text
data/<game_id>/pbp/
data/<game_id>/players/
```

这些是更早版本的加工导出目录，格式与新版本原始响应不同，需要的话请自行转换。

迁移不是独立的离线命令，它发生在正常采集流程开始时。建议迁移前备份 `data/output`，不要在迁移过程中删除旧目录。

### 9.4 并发与文件锁

项目没有实现跨进程文件锁。请不要对**同一输出目录、同一比赛**同时运行多个 `nba-game` 实例，否则可能互相覆盖清单或产生重复请求。

推荐做法：

- 多场比赛串行运行。
- 不同比赛写入不同 `<game_id>` 子目录时，可以并行，但仍受 NBA 接口频率限制，建议保守。
- 不要为了“加速”而并发轰炸 `stats.nba.com`；程序自身已经按至少 1 秒间隔串行请求。

### 9.5 请求失败与暂停策略

- **限速**：请求串行执行，相邻请求开始时间至少间隔 1 秒。
- **重试**：网络错误、超时、429、5xx 和无效 JSON 最多尝试 2 次；两次尝试之间会等待。
- **不盲目重试**：400、403、HTML 错误页和结构校验失败不会反复请求，避免放大问题。
- **Stats 暂停**：两个不同的 Stats 接口连续返回 HTML 时，本轮后续 Stats 请求（含球员档案）会暂停并标记为 `skipped`，Live 数据仍会继续处理；下次运行会重新探测。
- **HTTP 200 不等于成功**：即使状态码是 200，HTML 页面、比赛/球员身份不匹配、结构不完整也会被识别为失败。
- **不轻易判定封禁**：HTTP 500 或 HTML 只记录观察到的错误，不直接下结论说 IP 被封。
- **跨源差异**：终场校验时，如果 Stats 与 Live 的比分、球队或投篮数不一致，会记录为校验失败并使整体变为 `partial`，不会静默覆盖。
- **空结果也可能矛盾**：合法空结果本身不算失败，但如果在终场校验中与其他数据矛盾，仍可能触发一致性失败。
- **复查**：上游数据稳定后，可以用 `--force` 刷新并重新校验；不要用 `--force` 替代对真实网络问题的排查。

---

## 10. 常见问题（FAQ）

### 10.1 安装与环境

#### Q1：提示 `uv: command not found`

按 [4.3 安装 uv](#43-安装-uv) 安装，然后重新打开终端。macOS/Linux 如果安装在 `~/.local/bin`，确认该目录在 `PATH` 中：

```bash
echo $PATH
export PATH="$HOME/.local/bin:$PATH"
```

Windows 请重新打开 PowerShell，或检查安装程序是否把 uv 加到了用户 PATH。

#### Q2：`uv sync` 下载依赖失败或很慢

先确认能访问 PyPI。公司网络或受限网络可以：

- 配置可用的 `HTTPS_PROXY` 后重试。
- 使用 uv 的镜像索引（示例，替换成你可用的镜像）：

```bash
# macOS / Linux
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --extra dev
```

Windows PowerShell：

```powershell
$env:UV_DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
uv sync --extra dev
```

- 如果只是某个包下载失败，先重试；uv 会复用已下载的缓存。
- 避免在同一个 `.venv` 中混用 pip 安装不同版本的 `nba_api`/`curl_cffi`；如怀疑版本冲突，删除 `.venv/` 后重新执行 `uv sync --extra dev`。

#### Q3：`Failed to initialize cache at ... Operation not permitted`

这是 uv 缓存目录不可写，不是项目代码错误。把缓存指到可写目录：

```bash
# macOS / Linux
UV_CACHE_DIR="$HOME/.cache/uv-nba" uv sync --extra dev

# Windows PowerShell
$env:UV_CACHE_DIR = "$env:TEMP\uv-cache"
uv sync --extra dev
```

后续命令也带上同一个 `UV_CACHE_DIR`，或把它写入 shell 配置。

#### Q4：Python 版本不对

uv 会读取 `.python-version` 并使用 Python 3.12。检查：

```bash
uv run python -V
```

如果本机没有可用的 3.12，可以显式安装：

```bash
uv python install 3.12
uv sync --extra dev
```

项目要求 Python `>=3.10`；如果你用其他方式管理环境，请不要低于 3.10。

#### Q5：激活虚拟环境失败（Windows PowerShell）

PowerShell 可能默认禁止执行脚本。可以只为当前会话放宽策略：

```powershell
Set-ExecutionPolicy -Scope Process RemoteSigned
.venv\Scripts\Activate.ps1
```

更简单的做法是不激活，始终使用 `uv run ...`。

### 10.2 网络与数据源

#### Q6：`stats.nba.com` 返回 HTML、403 或超时

先执行：

```bash
uv run nba-game 0022401196 --check-network
```

如果只有 `NBA Stats` 不可用：

- 这是 `stats.nba.com` 的路由/访问限制问题，常见于需要代理的网络。
- 使用 `--proxy` 或 `HTTPS_PROXY` 指向可用代理，再跑 `--check-network`。
- 切换代理节点后重试。
- 不要根据一个 HTML 错误页直接断言“IP 被封”；项目也只把它记录为“可能是接口临时异常或访问限制”，不直接判定封禁。
- 如果两个不同的 Stats 接口连续返回 HTML，程序会暂停本轮后续 Stats 请求（包括球员档案），但继续处理 Live 数据；下次运行会重新探测，不需要 `--force`。详见 [9.5 请求失败与暂停策略](#95-请求失败与暂停策略)。

如果 `NBA Stats` 和 `NBA Live CDN` 都不可用，先检查本机网络、DNS 和代理软件，而不是修改项目代码。如果只有 `NBA Live CDN` 不可用，Stats 数据仍可采集，但 Live 资源会失败，整体通常是 `partial`。

#### Q7：请求超时怎么办

默认单次请求 30 秒。代理较慢或上游响应慢时：

```bash
uv run nba-game 0022401196 --timeout 60
```

超时是**单次请求**的超时，不是整场总耗时；一场比赛有几十个请求，总耗时仍可能达到数分钟。

#### Q8：遇到 HTTP 429

429 表示请求过于频繁。程序会等待后重试一次；仍失败时该资源记为 `failed`。建议：

- 等待一段时间后重跑同一命令。
- 不要并发运行多个实例。
- 不要通过缩短间隔或并行请求“加速”。

#### Q9：代理端口冲突/代理不生效

本项目不监听任何端口，因此不存在“项目端口被占用”。需要检查的是**代理软件**的端口：

```bash
uv run nba-game 0022401196 --proxy http://127.0.0.1:7890 --check-network
```

确认代理软件正在运行，端口与实际一致，协议（HTTP/SOCKS）与 URL scheme 一致。只支持 HTTP/HTTPS/SOCKS，不支持 PAC。

#### Q10：设置 `NO_PROXY` 后仍然走了代理

`NO_PROXY` 只在程序自动探测代理时生效；显式传入 `--proxy` 会优先使用该代理。检查命令中是否带了 `--proxy`，并确认 `NO_PROXY` 的主机名与请求域名一致。

### 10.3 运行与输出

#### Q11：退出码是 1，但已经生成了很多文件

这通常表示“部分完成”。成功的结果已经保存，失败/跳过的资源记录在：

```text
data/games/<game_id>/summary.md
data/games/<game_id>/manifest.json
```

先看 `summary.md` 的“缺项与处理建议”，再重跑同一命令补抓。不要因为退出码 1 就删除整个目录。

#### Q12：`game_rotation` 返回 HTTP 500

这是上游接口可能出现的错误，不是本地参数错误。实际采集示例中出现过该情况。处理方式：

- 等待一段时间后重跑同一命令；程序会对失败资源重新请求。
- 如果长期 500，整体会是 `partial`，但其他资源仍然可用。
- 不要通过增加超时来“修复”500；超时只影响等待时间。

#### Q13：`dunk_score_leaders` 是空结果或失败

`DunkScoreLeaders` 依赖赛季和比赛的支持情况。部分比赛没有扣篮记录，返回空结果是合法的；部分年份可能不支持或返回错误。空结果会在下次运行重试，不会阻止其他资源采集。

如果该资源为空，`summary.md` 会标为“合法空结果”或“失败”，整体完成度以 `manifest.json` 为准。

#### Q14：为什么输出不在 `data/games` 下

可能原因：

1. 使用了 `--output-dir`，最终路径是 `<output-dir>/<game_id>`。
2. 以非 editable 方式安装（例如从 wheel 安装），默认目录会按包安装位置计算，而不是项目根目录。
3. 命令不是从项目根目录执行的，相对路径随当前工作目录变化。

显式指定绝对路径最稳妥：

```bash
uv run nba-game 0022401196 --output-dir /绝对路径/NBAGames/data/games
```

#### Q15：`Permission denied` 或 `无法原子保存`

输出目录必须可写。检查：

- 是否写到了系统目录（如 `/usr/local`、`C:\Program Files`）。
- 是否在 macOS 的“文稿/桌面/下载”等受 TCC 保护的目录，终端可能没有权限。
- 是否使用了只读挂载或容器内只读卷。

建议在项目目录或用户目录下运行，或显式指定可写目录：

```bash
uv run nba-game 0022401196 --output-dir "$HOME/nba-data"
```

不要用 `sudo` 运行本工具来绕过权限问题；这会让生成的文件归属 root，后续更难处理。

#### Q16：`complete` 但非空资源数小于计划数，正常吗

正常。`complete` 只要求计划内资源为 `success` 或 `empty`，不要求全部非空。以示例比赛 `0022401196` 为例，49 个比赛资源中 45 个返回非空数据，另外 4 个是合法空结果（例如没有扣篮、某阵容没有投篮）；它们结构合法、没有记录，计为 `empty`，不会让整体变成 `partial`。

如果数字明显偏少，或 `summary.md` 中有“失败/跳过”，则需要按缺项处理。

#### Q17：比赛还没结束，为什么状态可能是 `complete`

`complete` 表示“本次范围内的资源都处理完了”，不是“比赛结束了”。请查看 `manifest.json` 的 `game_status`：

- `1`：未开始。
- `2`：进行中。
- `3`：已结束。

比赛进行中重复运行同一命令即可得到新快照；程序不会后台轮询。

#### Q18：球员档案中的球队和比赛时不一致

这是预期行为。`CommonPlayerInfo` 返回的是**查询时的当前档案**，不是比赛发生时的历史档案。项目在 `manifest.json` 和 `summary.md` 中都注明了这一点。

### 10.4 数据使用

#### Q19：为什么没有 CSV 或 DataFrame 输出

项目刻意只保存原始 JSON，避免解析器裁剪字段或改变类型。需要 CSV/DataFrame 时，请基于 `raw/` 自行转换；这样也可以按你的分析需求选择字段和展开方式。

#### Q20：比赛 ID 的前导零丢了

始终把比赛 ID 当作**字符串**处理：

```bash
# 正确
uv run nba-game 0022401196
```

在 Excel/CSV 中，把该列设为文本格式，或使用公式/导入设置保留前导零；不要用整数类型存储。传入 9 位数字会被 CLI 拒绝并返回退出码 2。

#### Q21：可以采集历史赛季吗

可以，只要比赛 ID 是有效的 10 位数字。赛季和比赛类型由 ID 推导；具体接口对历史赛季的支持程度由 NBA 上游决定，部分资源可能为空或失败，届时以 `summary.md` 为准。

#### Q22：可以同时跑多场比赛吗

项目没有内置并发控制。建议串行运行；如果确实要并行，请为不同比赛使用不同输出目录，并自行控制频率。不要对**同一场比赛、同一输出目录**并发运行。

---

## 11. 开发与测试

### 11.1 开发环境

在项目根目录：

```bash
uv sync --extra dev
```

这会安装运行依赖、`pytest` 和 editable 的本项目。`.vscode/settings.json` 已把解释器指向 `.venv/bin/python` 并启用 pytest；使用其他 IDE 时，请手动选择 `.venv` 中的解释器。

### 11.2 离线测试

测试使用 `FakeTransport`，**不会访问网络**：

```bash
uv run --extra dev pytest -q
```

也可以只跑某个文件或某个测试：

```bash
uv run --extra dev pytest tests/test_game.py -q
uv run --extra dev pytest tests/test_game.py -q -k cache
```

测试覆盖：

- 所有官方端点的参数构造（不发送请求）。
- 赛季/比赛类型推导。
- 全量采集、缓存复用、强制刷新。
- 部分失败隔离、Live 回退、空结果保留。
- 清单重建、损坏/篡改文件、旧数据迁移。
- 原子写入失败、CLI 参数与退出码。
- 代理/凭据脱敏、HTML 错误页、Stats 暂停与恢复。
- 跨源比分不一致、阵容身份校验。
- 中断后的清单状态。

如果测试全部通过，说明本地代码逻辑正常；这不代表 NBA 上游当前一定可用。

### 11.3 构建

本项目是标准 Python 包，构建不是运行所必需。需要 wheel/sdist 时：

```bash
uv build
```

构建产物在 `dist/`（已被 `.gitignore` 忽略）。也可以指定输出目录：

```bash
uv build --out-dir /tmp/nba-dist
```

注意：从 wheel 做非 editable 安装后，默认输出目录会按安装位置计算；运行采集时建议显式传 `--output-dir`。

### 11.4 调试

推荐顺序：

1. **先隔离网络问题**

   ```bash
   uv run nba-game 0022401196 --check-network
   ```

   它会分别报告 `NBA Stats` 和 `NBA Live CDN` 是否可用，且不写存档。

2. **看单场摘要**

   `summary.md` 会按资源列出失败原因和建议，比控制台最后一行更具体。

3. **看清单中的请求上下文**

   `manifest.json` 的 `resources.<key>` 包含 `endpoint`、`parameters`、`attempts`、`error`、`sha256` 等，可判断是参数、身份校验还是网络问题。

4. **用临时输出目录做实验**

   ```bash
   uv run nba-game 0022401196 --output-dir /tmp/nba-debug --timeout 60
   ```

   避免反复污染正式归档；Windows 可用 `%TEMP%\nba-debug`。

5. **运行离线测试**

   ```bash
   uv run --extra dev pytest -q
   ```

   如果离线测试通过，问题更可能出在网络、上游数据或代理，而不是本地逻辑。

6. **在 IDE 中打断点**

   常用位置：

   - `src/nba_game/cli.py` 的 `main()`：参数和退出码。
   - `src/nba_game/collector.py` 的 `run()` / `collect()`：资源顺序、缓存和依赖。
   - `src/nba_game/transport.py` 的 `Transport.fetch()`：请求、重试和代理。
   - `src/nba_game/validation.py` 的 `inspect_response()`：身份/结构校验。

   项目没有独立的日志文件；进度打印到 stdout，错误打印到 stderr。需要更细的请求信息时，查看 `manifest.json` 中的 `endpoint` 和 `parameters`。

### 11.5 扩展新接口

新增一个 Stats 接口时，通常需要：

1. 在 `src/nba_game/sources/stats.py` 的 `RESOURCES` 中增加 `Resource` 定义（名称、模块、类名、根字段或结果集名）。
2. 在 `build_request()` 中补充该接口的参数；如果接口需要球队/阵容 ID，使用 `bind()`。
3. 确认 `validation.py` 能校验其身份和结构；必要时增加数据集名称或关键字段。
4. 如果它参与一致性检查，在 `consistency_checks()` 和 `KEY_FIELDS` 中补充。
5. 如果需要新的依赖展开（例如先取列表再逐项请求），在 `collector.py` 中显式声明。
6. 在 `tests/test_game.py` 中增加参数构造、校验和失败隔离测试。

固定资源由 `RESOURCES` 自动遍历；球队阵容、阵容投篮和球员档案分别动态统计，不需要手动改资源总数。

### 11.6 持续集成（CI）

- 仓库已配置 GitHub Actions：`.github/workflows/ci.yml`。
- 触发条件：推送到 `main`、Pull Request、手动 `workflow_dispatch`。
- 测试矩阵：`ubuntu-latest`、`macos-latest`、`windows-latest` × Python `3.10`、`3.12`。
- 每次运行执行：`uv sync --locked --extra dev`、`uv run --no-sync pytest -q`。
- `actions/checkout` 和 `astral-sh/setup-uv` 固定到具体 commit SHA，避免标签被移动带来的供应链风险。
- 首次 push 后，README 顶部的 CI 徽章会显示运行状态；在 workflow 推送并首次运行前，徽章可能显示 404 或 `no status`。

当前 CI **只做离线测试**，不访问 NBA 接口，也不验证真实上游可用性。仓库还没有配置 `ruff`、`mypy`、`black` 等 lint/format/type-check 任务；`.ruff_cache/` 可能只是本地运行工具留下的缓存。

> 注意：当前 `.gitignore` 中包含 `/tests/`，因此 `tests/test_proxy.py` 未被 Git 跟踪。CI 只会运行仓库中已跟踪的测试；如果希望覆盖代理选择测试，请先修正忽略规则并提交该文件。

提交前本地至少运行：

```bash
uv run --extra dev pytest -q
```

如需引入 lint/format，请同时更新 `pyproject.toml`、开发依赖和 CI，避免只有本地能跑。

### 11.7 维护者验证记录

以下操作已在本次 README 更新时实际执行（macOS Apple Silicon）：

- 全新 `git clone` 后执行 `uv sync --extra dev`（联网同步锁文件中的依赖）。
- `uv run nba-game --help` 和 `uv run python -m nba_game --help`。
- `uv run nba-game 0022401196 --check-network`，Stats 与 Live 均可用。
- 在全新 clone 中执行 `uv run nba-game 0022401196`：退出码 `0`，86 个资源记录，归档约 2 MB。
- 用一份旧版 v1 归档（`data/output/0022401196`）在临时目录验证旧数据导入：50 个资源写入新目录并带有 `migration` 信息。
- 离线测试在 Python `3.10.20` 与 `3.12.13` 下均通过。
- `uv build` 成功生成 wheel 与 sdist。

未在本次环境中验证：

- Windows 和 Linux 的逐条命令（已给出等价写法）。
- 所有历史赛季、所有球队组合的上游可用性。
- 需要代理的网络环境（本次网络可直连 NBA）。
- GitHub Actions 工作流尚未在远端实际运行；工作流文件刚新增，需要 push 后触发，README 中的 CI 徽章也要等首次运行后才有状态。

---

## 12. 许可与数据声明

- 本仓库当前**未包含 LICENSE 文件**。在再分发、修改或商用前，请先与仓库作者确认授权。
- NBA 数据、标识和接口内容的版权归 NBA 及其数据提供方所有。使用本项目采集的数据时，请遵守 NBA.com 的使用条款、robots 规则和当地法律。
- 本项目只访问公开接口，不绕过付费墙或访问控制；请合理控制请求频率，不要对上游造成压力。
- 采集结果仅供合法的分析、研究、教学和存档用途；使用者对数据的后续使用负责。

---

如果只想记住三件事：

1. 在项目根目录执行 `uv sync --extra dev`。
2. 先跑 `uv run nba-game <10位比赛ID> --check-network` 确认网络。
3. 再跑 `uv run nba-game <10位比赛ID>`，结果在 `data/games/<比赛ID>/`，先看 `summary.md`。
