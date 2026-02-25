# codex-got_longbridge

## 期权信息抓取脚本

仓库新增了 `option_data_collector.py`，用于基于 Longbridge OpenAPI/SDK 抓取：

- 指定标的（如 `AAPL.US`）
- 指定到期日（如 `2026-01-16`）

对应期权链下所有期权合约可通过 API 获取的主要行情信息（期权报价、通用报价、静态信息、深度、逐笔、经纪队列等），并汇总为一个 JSON 文件。

### 运行前准备

1. 安装 Longbridge Python SDK（`longport.openapi`）。
2. 配置 OpenAPI 鉴权环境变量（至少包括 app key/secret/token）。

> 脚本默认通过 `Config.from_env()` 读取环境变量，也可配合本地 Longbridge 配置文件使用。

#### OpenAPI 鉴权环境变量去哪里配置？

你可以在**运行脚本的那台机器的 Shell 环境**里配置，常见有 3 种方式：

1. **当前终端临时生效（最快）**

```bash
export LONGPORT_APP_KEY="你的 app key"
export LONGPORT_APP_SECRET="你的 app secret"
export LONGPORT_ACCESS_TOKEN="你的 access token"
```

2. **写入用户级 Shell 配置（长期生效）**

以 `bash` 为例，把上面的 `export` 追加到 `~/.bashrc`（或 `~/.bash_profile`）：

```bash
echo 'export LONGPORT_APP_KEY="你的 app key"' >> ~/.bashrc
echo 'export LONGPORT_APP_SECRET="你的 app secret"' >> ~/.bashrc
echo 'export LONGPORT_ACCESS_TOKEN="你的 access token"' >> ~/.bashrc
source ~/.bashrc
```

3. **项目内 `.env` 文件 + 启动前加载**

在项目根目录新建 `.env`：

```env
LONGPORT_APP_KEY=你的 app key
LONGPORT_APP_SECRET=你的 app secret
LONGPORT_ACCESS_TOKEN=你的 access token
```

运行前执行：

```bash
set -a
source .env
set +a
```

> 可选：若你使用自定义网关/地址，可额外设置 `LONGPORT_HTTP_URL`、`LONGPORT_QUOTE_WS_URL`、`LONGPORT_TRADE_WS_URL`。

### 用法

```bash
python option_data_collector.py \
  --symbol AAPL.US \
  --expiry 2026-01-16 \
  --output aapl_options_2026-01-16.json
```

可选参数：

- `--batch-size`：批量请求大小，默认 `50`。

### 输出说明

输出 JSON 包含：

- 请求参数与生成时间
- 实际使用的 SDK 方法名（便于排查 SDK 版本差异）
- 到期日列表、期权链、期权代码列表
- `option_quote` / `quote` / `static_info`
- 每个期权合约的 `depth` / `trades` / `brokers`
