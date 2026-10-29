<p align="center">
  <img src="docs/assets/nba-game-banner.png" alt="NBA GAME · Single-game data collection and archiving" width="100%">
</p>

<p align="center">
  <strong>Enter a 10-digit game ID. Archive all available raw data for an NBA game.</strong>
</p>

<p align="center">
  <a href="https://github.com/luo-qing-xin/NBAGames/actions/workflows/ci.yml"><img src="https://github.com/luo-qing-xin/NBAGames/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI status"></a>
  <a href="#2-requirements"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white" alt="Python 3.10+"></a>
  <a href="#1-overview"><img src="https://img.shields.io/badge/version-0.2.0-0E7490?style=flat-square" alt="version 0.2.0"></a>
  <a href="#1-overview"><img src="https://img.shields.io/badge/data-NBA%20Stats%20%2B%20Live%20CDN-C9082C?style=flat-square" alt="NBA Stats + Live CDN"></a>
  <a href="#2-requirements"><img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-444444?style=flat-square&amp;logo=linux&amp;logoColor=white" alt="macOS, Linux, Windows"></a>
</p>

<p align="center">
  <a href="README.md">简体中文</a> &nbsp;|&nbsp; <strong>English</strong>
</p>

<p align="center">
  <a href="#1-overview">Overview</a> &nbsp;·&nbsp;
  <a href="#2-requirements">Requirements</a> &nbsp;·&nbsp;
  <a href="#3-quick-start">Quick Start</a> &nbsp;·&nbsp;
  <a href="#4-usage">Usage</a>
  <br>
  <a href="#5-output">Output</a> &nbsp;·&nbsp;
  <a href="#6-troubleshooting">Troubleshooting</a> &nbsp;·&nbsp;
  <a href="#7-development-and-testing">Development &amp; Testing</a> &nbsp;·&nbsp;
  <a href="#8-important-notes">Important Notes</a>
</p>

---

## 1. Overview

`nba-game` is a Python command-line tool for collecting NBA single-game data. Given a 10-digit game ID, it retrieves box scores, play-by-play events, shots, five-player lineups, and current player profiles from NBA Stats and Live CDN. It saves raw JSON by source and generates a Chinese summary and a traceable collection manifest.

The tool runs locally without a web server, listening port, database, or API key. Each run captures a snapshot of one game. Data availability depends on NBA endpoints, game status, and season coverage.

**The CLI messages and generated `summary.md` are currently in Chinese.** This guide explains the workflow in English; JSON keys and manifest status values remain as provided by the application and data sources.

## 2. Requirements

| Item | Requirement |
|---|---|
| Operating system | macOS, Linux, or Windows (PowerShell) |
| Python | 3.10+; the repository defaults to **3.12**, which uv can install |
| Tools | Git and uv; uv installation instructions are below |
| Installation network | Access to GitHub, Python downloads, and PyPI |
| Collection network | Access to `stats.nba.com` and `cdn.nba.com`, through a proxy if needed |
| File permissions | Writable project and output directories, with space for dependencies, Python caches, and collected data |

Node.js, a GPU, and additional background services are not required. Runtime dependencies are declared in `pyproject.toml` and locked in `uv.lock`; you do not need to install them individually.

## 3. Quick Start

### 3.1 Install uv

macOS / Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Reopen your terminal after installation, then check Git and uv:

```bash
git --version
uv --version
```

Install Git first if it is missing. Alternatively, download and extract the repository ZIP, then run the dependency installation commands below from the extracted directory.

### 3.2 Get the project and install dependencies

```bash
git clone https://github.com/luo-qing-xin/NBAGames.git
cd NBAGames
uv python install 3.12
uv sync --locked
uv run nba-game --help
```

`uv sync` creates `.venv` and installs the project and its runtime dependencies. Seeing the command help confirms that the entry point works. No manual virtual environment activation or configuration file is needed.

**Run all subsequent commands from the project root.** The same `uv run` commands work on macOS/Linux and in PowerShell.

### 3.3 Check data-source connectivity

Check both sources using the example game ID. This command does not write or modify game archives:

```bash
uv run nba-game 0022401196 --check-network
```

A successful check prints the following messages in Chinese:

```text
NBA Stats：可用（JSON 与比赛 ID 校验通过）
NBA Live CDN：可用（JSON 与比赛 ID 校验通过）
网络检查完成，未修改任何比赛存档。
```

`可用` means available: JSON and game-ID validation passed. Continue when both sources are available. Otherwise, see [Using a proxy](#42-use-a-proxy) or [Troubleshooting](#6-troubleshooting). Live availability does not establish Stats availability, and a successful check does not guarantee that every endpoint will return data.

### 3.4 Collect your first game

```bash
uv run nba-game 0022401196
```

The tool sends requests sequentially with a delay between requests. A game may take several minutes to collect. Results are written automatically to `data/games/0022401196/`.

### 3.5 Verify the result

- `抓取完成` (collection complete) with exit code `0` means collection completed within the supported scope.
- `部分数据未完成` (some data incomplete) or exit code `1` means successful results were saved, but you should check missing items and suggested actions in the summary.
- Open `data/games/0022401196/summary.md` first. For detailed inspection, use `manifest.json` in the same directory.

To inspect the exit code, run the following immediately after the collection command:

```bash
# macOS / Linux
echo $?
```

```powershell
# Windows PowerShell
$LASTEXITCODE
```

Do not delete the output directory after a partial failure. Fix the network issue or wait for the upstream service to recover, then rerun the same collection command to retry missing resources.

## 4. Usage

### 4.1 Collect another game

Open the game page on the NBA website, find the 10-digit game ID in its URL, and replace the example ID below. Preserve leading zeros. The tool derives the season and game type automatically.

```bash
uv run nba-game 0022300001
```

Store game IDs as strings. Converting them to integers in Python, CSV processing, or spreadsheets removes leading zeros.

### 4.2 Use a proxy

Start your proxy software first, then replace the address and port below with your actual settings. Use the same proxy for the connectivity check and collection:

```bash
uv run nba-game 0022401196 --proxy http://127.0.0.1:7890 --check-network
uv run nba-game 0022401196 --proxy http://127.0.0.1:7890
```

`--proxy` accepts HTTP, HTTPS, and SOCKS URLs with a host and port, such as `socks5h://127.0.0.1:7890`. The tool does not execute PAC scripts.

Without `--proxy`, the tool detects proxy environment variables or system proxy settings. You can also set `HTTPS_PROXY` in the current terminal:

```bash
# macOS / Linux
export HTTPS_PROXY=http://127.0.0.1:7890
```

```powershell
# Windows PowerShell
$env:HTTPS_PROXY = "http://127.0.0.1:7890"
```

Then run the normal collection command. Automatic proxy selection considers `NO_PROXY`; an explicit `--proxy` takes precedence. **The project does not read `.env` files.** Pass options directly or set environment variables in your terminal.

### 4.3 Change the output directory and timeout

```bash
uv run nba-game 0022401196 --output-dir ./nba-data --timeout 60
```

Results are saved to `./nba-data/0022401196/`. `--output-dir` specifies the output root; the game ID is appended automatically. Relative paths are resolved against the current working directory.

`--timeout` is the timeout in seconds for each request, not a time limit for the entire collection.

### 4.4 Force a refresh

```bash
uv run nba-game 0022401196 --force
```

This ignores existing caches and fetches all game data and player profiles again. To retry failed resources, normally just rerun the original command without `--force`.

### 4.5 Command reference

| Argument | Default | Description |
|---|---|---|
| `game_id` | Required | Exactly 10 digits, including leading zeros |
| `--output-dir` | Project's `data/games` | Output root; the game ID is appended automatically |
| `--proxy` | Environment or system proxy detection | Proxy URL with a scheme, host, and port |
| `--timeout` | `30` | Per-request timeout in seconds; must be finite and positive |
| `--force` | Disabled | Ignore caches and fetch again |
| `--check-network` | Disabled | Check both sources without modifying archives |
| `-h` / `--help` | — | Display help and exit |

The module entry point is also supported: `uv run python -m nba_game --help`.

## 5. Output

Files are organized by source. A resource file exists only after it has been saved successfully:

```text
data/games/0022401196/
├── summary.md           # Chinese summary, missing items, and suggested actions
├── manifest.json        # Overall/per-resource status, parameters, and checksums
└── raw/
    ├── stats/           # NBA Stats game data, including team/lineup subdirectories
    ├── live/            # Live BoxScore and Play-by-Play
    └── players/         # Current profiles stored by player ID
```

Use `summary.md` for a quick overview and `manifest.json` for programmatic access, source verification, and failure inspection. `raw/` preserves source responses without merging Stats and Live fields. CSV export is not provided.

Read the manifest with this command (works on macOS/Linux and in PowerShell):

```bash
uv run python -c "import json; from pathlib import Path; p = Path('data/games/0022401196/manifest.json'); m = json.loads(p.read_text(encoding='utf-8')); print(m['game_id'], m['status']); print(m['summary'])"
```

To read raw data, replace the path with an existing JSON file under `raw/` and use the same `json.loads()` approach.

| Status or exit code | Meaning |
|---|---|
| `complete` / exit code `0` | Collection completed within scope; valid empty results are allowed |
| `partial` / exit code `1` | Resources, roster coverage, or consistency checks are incomplete; inspect the summary |
| Exit code `1` | Can also indicate interruption or a local file error; check console messages |
| Exit code `2` | Invalid command-line arguments, such as a game ID with fewer than 10 digits |

Resource statuses are `success`, `empty` (a valid empty response), `failed`, and `skipped`. A game with no dunks or a lineup with no shots may legitimately return empty data; this is not necessarily an error.

`complete` describes collection scope, **not whether the game has finished**. The manifest's `game_status` is `1` (not started), `2` (in progress), or `3` (finished). It may be `null` if the status cannot yet be determined.

## 6. Troubleshooting

### uv command not found

Reopen your terminal after installation. On macOS/Linux, if the default installation directory is missing from `PATH`, run this in the current session and retry:

```bash
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

On Windows, check that the uv installation directory is in your user `PATH`, then reopen PowerShell.

### Dependency or Python downloads fail

Check your installation network and terminal proxy settings, then retry `uv python install 3.12` or `uv sync --locked`. Previously downloaded files are reused from the cache.

If uv reports an unwritable cache directory, use a writable directory inside the project:

```bash
uv --cache-dir ./.uv-cache sync --locked
uv --cache-dir ./.uv-cache run nba-game --help
```

Add `--cache-dir ./.uv-cache` to subsequent uv commands as well. For Python version errors, confirm that you are using the repository default, 3.12.

### NBA requests time out or return HTML / HTTP errors

Run `--check-network` with the same game ID and proxy, then troubleshoot based on the result:

| Symptom | Action |
|---|---|
| Timeout or connection failure | Check networking, DNS, and proxy software; switch proxy nodes if needed or use `--timeout 60` |
| Stats returns HTML / 403 | Check proxy routing for `stats.nba.com`, switch nodes, or retry later |
| HTTP 429 | Wait before retrying and avoid concurrent instances |
| HTTP 5xx | The upstream endpoint may be temporarily unavailable; retry later. A longer timeout does not fix HTTP 500 |
| Only Live is available | Troubleshoot Stats separately; CDN success does not establish Stats availability |

If two different Stats endpoints consecutively return HTML, the tool pauses remaining Stats requests for that run and marks them as skipped, while continuing Live collection. After connectivity recovers, rerun the original command to probe and retry; `--force` is unnecessary.

### Partial failure, but many files were created

Keep the existing files and inspect missing items and suggestions in `summary.md`. Rerun the same command once the network or upstream service recovers. Unsupported resources for some historical seasons may remain empty or fail; refer to the actual manifest.

### Cannot write files or find the output

Ensure the output directory is writable. Use `--output-dir ./nba-data` for a directory under your current location, or specify a writable absolute path. When installed from a wheel or another built package, the default output path is derived from the installed package location; set `--output-dir` explicitly.

The project does not listen on a port. For proxy connection failures, check your proxy software's actual port, protocol, and running state.

## 7. Development and Testing

Development dependencies are not needed to run the tool. To modify code or verify local behavior, run this from the project root:

```bash
uv sync --locked --extra dev
uv run --no-sync pytest -q
```

Tests use a simulated transport and do not access NBA services. Passing tests validate the covered local behavior, not current upstream availability.

## 8. Important Notes

- **Caching and resuming:** Validated successful caches for finished games are reused by default. Failed, skipped, and empty resources are requested again on the next run. Progress is saved per resource; rerun the original command after an interruption.
- **Games in progress:** There is no background polling. Rerun manually for a new snapshot. A collection can be `complete` while the game is still in progress.
- **Player profiles:** Profiles reflect information at query time, not historical information at the time of the game. They are cached too; use `--force` to refresh them.
- **Legacy archives:** Without `--force`, the tool imports validated legacy raw files from `output/<game_id>` next to the output root, which defaults to `data/output/<game_id>`. Original files are retained and normal collection continues; this is not a separate offline migration command.
- **Concurrency:** There is no cross-process file lock. Do not run multiple instances for the same game and output directory. Collect multiple games sequentially to reduce upstream rate limiting.
- **Data scope:** The tool accesses public endpoints and saves the raw data available during the run. It does not provide game videos, frame-by-frame tracking, or historical player-profile reconstruction.
- **License and ownership:** The repository currently has no `LICENSE` file; confirm authorization with the author before redistribution, modification, or commercial use. NBA data and marks belong to their respective rights holders. Follow applicable service terms and keep request rates reasonable.
