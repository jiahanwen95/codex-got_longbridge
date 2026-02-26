# codex-got_longbridge

## 期权信息抓取脚本

仓库提供 `option_data_collector.py`，用于基于 Longbridge OpenAPI/SDK 抓取：

- 指定标的（如 `AAPL.US`）
- 指定到期日（如 `2026-01-16`）

对应期权链下所有期权合约可通过 API 获取的主要行情信息（期权报价、通用报价、静态信息、深度、逐笔、经纪队列等），并汇总为 JSON 文件。

## 运行前准备

1. 一键安装依赖：

```bash
pip install -r requirements.txt
```

2. 准备 OpenAPI 鉴权信息：
   - 推荐直接在仓库根目录维护 `key` 文件（脚本会自动读取并写入 `LONGPORT_*` 环境变量）
   - 也可手工配置环境变量（`LONGPORT_APP_KEY` / `LONGPORT_APP_SECRET` / `LONGPORT_ACCESS_TOKEN`）

> 脚本会优先读取仓库内 `key` 文件，再通过 `Config.from_env()` 初始化。

### OpenAPI 鉴权环境变量去哪里配置？

配置在你运行脚本所在机器的 Shell 环境即可，常用变量如下：

- `LONGPORT_APP_KEY`
- `LONGPORT_APP_SECRET`
- `LONGPORT_ACCESS_TOKEN`
- （可选）`LONGPORT_HTTP_URL`
- （可选）`LONGPORT_QUOTE_WS_URL`
- （可选）`LONGPORT_TRADE_WS_URL`

常见方式：

1. **当前终端临时生效**

```bash
export LONGPORT_APP_KEY="xxx"
export LONGPORT_APP_SECRET="xxx"
export LONGPORT_ACCESS_TOKEN="xxx"
```

2. **写入 `~/.bashrc` / `~/.bash_profile`（长期生效）**

```bash
echo 'export LONGPORT_APP_KEY="xxx"' >> ~/.bashrc
echo 'export LONGPORT_APP_SECRET="xxx"' >> ~/.bashrc
echo 'export LONGPORT_ACCESS_TOKEN="xxx"' >> ~/.bashrc
source ~/.bashrc
```

3. **项目中使用 `.env` 并在运行前 `source`**

```bash
set -a
source .env
set +a
```

## 用法

```bash
python option_data_collector.py \
  --symbol AAPL.US \
  --expiry 2026-01-16 \
  --output aapl_options_2026-01-16.json
```

如需只筛选某个行权价/方向（例如 call 280）：

```bash
python option_data_collector.py \
  --symbol AAPL.US \
  --expiry 2026-03-30 \
  --strike 280 \
  --right call \
  --output aapl_call_280_2026-03-30.json
```

> 脚本内置常见误拼修正：当输入 `APPL.US` 时会自动修正为 `AAPL.US`。

## 输出内容


另外会自动生成同名 Markdown 报告文件（例如输出 `aapl_call_280_2026-03-30.json` 时，同时生成 `aapl_call_280_2026-03-30.md`），便于快速查看筛选合约与抓取摘要。
JSON 主要字段：

- `requested`：请求参数（含原始输入和标准化后的 symbol）
- `summary`：数量汇总、筛选合约数、错误数
- `selected_contracts`：按 `--strike` / `--right` 筛选出的合约摘要
- `option_chain` / `option_symbols`
- `option_quote` / `quote` / `static_info`
- `depth` / `trades` / `brokers`
- `errors`：单合约 API 拉取失败记录（不中断全量抓取）
