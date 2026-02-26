#!/usr/bin/env python3
"""抓取指定标的、指定到期日的期权全量可用信息（基于 Longbridge Python SDK）。"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from longport.openapi import QuoteContext


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取指定标的、指定到期日的期权相关信息并导出 JSON"
    )
    parser.add_argument("--symbol", required=True, help="标的代码，例如 AAPL.US")
    parser.add_argument(
        "--expiry",
        required=True,
        help="期权到期日，格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--output",
        default="option_data.json",
        help="输出文件路径（默认 option_data.json）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="批量请求大小（默认 50）",
    )
    parser.add_argument(
        "--strike",
        type=float,
        help="可选：仅输出指定行权价（例如 280）",
    )
    parser.add_argument(
        "--right",
        choices=["call", "put"],
        help="可选：仅输出 call 或 put 合约",
    )
    args = parser.parse_args()
    if args.batch_size <= 0:
        raise SystemExit("--batch-size 必须大于 0")
    return args


def normalize_symbol(symbol: str) -> str:
    """容错修正常见误拼（APPL -> AAPL），并统一大写。"""
    normalized = symbol.strip().upper()
    return "AAPL.US" if normalized == "APPL.US" else normalized


def to_python(value: Any) -> Any:
    """将 SDK 返回对象递归转换为可 JSON 序列化结构。"""
    if value is None:
        return None
    if is_dataclass(value):
        return {k: to_python(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): to_python(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_python(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dict__"):
        return {k: to_python(v) for k, v in vars(value).items() if not k.startswith("_")}
    return value


def chunked(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def try_call(
    ctx: Any,
    method_names: Sequence[str],
    *args: Any,
    **kwargs: Any,
) -> tuple[str, Any]:
    """兼容 SDK 不同版本的方法名。"""
    last_error: Exception | None = None
    for name in method_names:
        method = getattr(ctx, name, None)
        if method is None:
            continue
        try:
            return name, method(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - 运行时依赖远端 API
            last_error = exc
    if last_error:
        raise last_error
    raise AttributeError(f"未找到可用方法: {method_names}")


def load_api_credentials_from_key_file(key_file: str = "key") -> None:
    """从仓库内 key 文件读取凭证，并写入 LONGPORT_* 环境变量。"""
    path = Path(key_file)
    if not path.exists():
        return

    mapping = {
        "APPKEY": "LONGPORT_APP_KEY",
        "APPSECRET": "LONGPORT_APP_SECRET",
        "ACCESSTOKEN": "LONGPORT_ACCESS_TOKEN",
    }
    loaded = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        raw_key, raw_value = line.split(":", 1)
        field = raw_key.strip().upper()
        env_name = mapping.get(field)
        if not env_name:
            continue
        value = raw_value.strip()
        if value:
            loaded[env_name] = value

    for env_name, value in loaded.items():
        os.environ[env_name] = value


def generate_markdown_report(result: dict[str, Any]) -> str:
    requested = result.get("requested", {})
    summary = result.get("summary", {})
    selected_contracts = result.get("selected_contracts", [])
    methods = result.get("sdk_methods", {})

    lines = [
        "# 期权数据抓取报告",
        "",
        "## 请求参数",
        f"- 标的: `{requested.get('symbol', '')}`",
        f"- 到期日: `{requested.get('expiry', '')}`",
        f"- 行权价筛选: `{requested.get('strike', '')}`",
        f"- 方向筛选: `{requested.get('right', '')}`",
        f"- 生成时间(UTC): `{requested.get('generated_at', '')}`",
        "",
        "## 汇总",
        f"- 期权代码总数: `{summary.get('option_count', 0)}`",
        f"- 期权链行数: `{summary.get('chain_rows', 0)}`",
        f"- 筛选合约数: `{summary.get('selected_contracts', 0)}`",
        f"- 错误数: `{summary.get('errors', 0)}`",
        "",
        "## SDK 方法",
    ]

    for name, method in methods.items():
        lines.append(f"- {name}: `{method}`")

    lines.extend(["", "## 筛选到的合约"])
    if not selected_contracts:
        lines.append("- 无匹配合约")
    else:
        lines.extend(
            [
                "| 类型 | 行权价 | 代码 |",
                "| --- | ---: | --- |",
            ]
        )
        for row in selected_contracts:
            lines.append(
                f"| {row.get('type', '')} | {row.get('strike_price', '')} | `{row.get('symbol', '')}` |"
            )

    return "\n".join(lines) + "\n"


def fetch_batched(
    ctx: Any,
    option_symbols: Sequence[str],
    batch_size: int,
    method_names: Sequence[str],
    result_name: str,
) -> dict[str, Any]:
    all_rows: list[Any] = []
    used_method: str | None = None
    for batch in chunked(option_symbols, batch_size):
        method, rows = try_call(ctx, method_names, list(batch))
        used_method = used_method or method
        all_rows.extend(rows or [])

    return {
        "method": used_method,
        "count": len(all_rows),
        result_name: to_python(all_rows),
    }


def extract_option_symbols(option_chain: Sequence[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            row.get("call_symbol")
            for row in option_chain
            if isinstance(row, dict) and row.get("call_symbol")
        }
        | {
            row.get("put_symbol")
            for row in option_chain
            if isinstance(row, dict) and row.get("put_symbol")
        }
    )


def filter_chain_rows(
    option_chain: Sequence[dict[str, Any]],
    strike: float | None,
    right: str | None,
) -> list[dict[str, Any]]:
    selected_rows: list[dict[str, Any]] = []
    for row in option_chain:
        if not isinstance(row, dict):
            continue
        row_strike = row.get("strike_price")
        if strike is not None and row_strike is not None and float(row_strike) != float(strike):
            continue
        if right == "call":
            selected_rows.append(
                {
                    "strike_price": row_strike,
                    "symbol": row.get("call_symbol"),
                    "type": "call",
                }
            )
        elif right == "put":
            selected_rows.append(
                {
                    "strike_price": row_strike,
                    "symbol": row.get("put_symbol"),
                    "type": "put",
                }
            )
        else:
            selected_rows.extend(
                [
                    {
                        "strike_price": row_strike,
                        "symbol": row.get("call_symbol"),
                        "type": "call",
                    },
                    {
                        "strike_price": row_strike,
                        "symbol": row.get("put_symbol"),
                        "type": "put",
                    },
                ]
            )
    return [r for r in selected_rows if r.get("symbol")]


def main() -> None:
    args = parse_args()
    symbol = normalize_symbol(args.symbol)
    expiry = date.fromisoformat(args.expiry)
    load_api_credentials_from_key_file()

    from longport.openapi import Config, QuoteContext

    config = Config.from_env()
    ctx = QuoteContext(config)
    used_methods: dict[str, str] = {}

    expiry_method, expiry_list = try_call(
        ctx,
        ["option_chain_expiry_date_list", "option_chain_expiry_date"],
        symbol,
    )
    used_methods["expiry_dates"] = expiry_method
    expiry_dates = {to_python(d) for d in expiry_list}
    if args.expiry not in expiry_dates:
        available = ", ".join(sorted(expiry_dates))
        raise SystemExit(
            f"到期日 {args.expiry} 不在可选列表中。\n"
            f"标的: {symbol}\n可选到期日: {available}"
        )

    chain_method, chain_rows = try_call(
        ctx,
        ["option_chain_info_by_date", "option_chain_by_date"],
        symbol,
        expiry,
    )
    used_methods["option_chain"] = chain_method
    option_chain = to_python(chain_rows)

    option_symbols = extract_option_symbols(option_chain)
    if not option_symbols:
        raise SystemExit(f"未在 {symbol} {args.expiry} 的期权链中提取到期权代码。")

    option_quote = fetch_batched(
        ctx,
        option_symbols,
        args.batch_size,
        ["option_quote", "realtime_quote_of_option"],
        "rows",
    )
    if option_quote.get("method"):
        used_methods["option_quote"] = option_quote["method"]

    static_info = fetch_batched(
        ctx,
        option_symbols,
        args.batch_size,
        ["static_info", "security_static_info"],
        "rows",
    )
    if static_info.get("method"):
        used_methods["static_info"] = static_info["method"]

    quote = fetch_batched(
        ctx,
        option_symbols,
        args.batch_size,
        ["quote", "realtime_quote", "realtime_quotes_of_securities"],
        "rows",
    )
    if quote.get("method"):
        used_methods["quote"] = quote["method"]

    depth_rows = []
    trade_rows = []
    broker_rows = []
    depth_method = trade_method = broker_method = None
    errors: list[dict[str, str]] = []
    for contract_symbol in option_symbols:
        try:
            if depth_method is None:
                depth_method, depth = try_call(ctx, ["depth", "security_depth"], contract_symbol)
            else:
                _, depth = try_call(ctx, [depth_method], contract_symbol)
            depth_rows.append({"symbol": contract_symbol, "data": to_python(depth)})
        except Exception as exc:  # pragma: no cover
            errors.append({"symbol": contract_symbol, "api": "depth", "error": str(exc)})

        try:
            if trade_method is None:
                trade_method, trades = try_call(ctx, ["trades", "security_trades"], contract_symbol)
            else:
                _, trades = try_call(ctx, [trade_method], contract_symbol)
            trade_rows.append({"symbol": contract_symbol, "data": to_python(trades)})
        except Exception as exc:  # pragma: no cover
            errors.append({"symbol": contract_symbol, "api": "trades", "error": str(exc)})

        try:
            if broker_method is None:
                broker_method, brokers = try_call(ctx, ["brokers", "security_brokers"], contract_symbol)
            else:
                _, brokers = try_call(ctx, [broker_method], contract_symbol)
            broker_rows.append({"symbol": contract_symbol, "data": to_python(brokers)})
        except Exception as exc:  # pragma: no cover
            errors.append({"symbol": contract_symbol, "api": "brokers", "error": str(exc)})

    used_methods["depth"] = depth_method or ""
    used_methods["trades"] = trade_method or ""
    used_methods["brokers"] = broker_method or ""

    selected_contracts = filter_chain_rows(option_chain, args.strike, args.right)

    result = {
        "requested": {
            "symbol": symbol,
            "input_symbol": args.symbol,
            "expiry": args.expiry,
            "batch_size": args.batch_size,
            "strike": args.strike,
            "right": args.right,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        },
        "sdk_methods": used_methods,
        "summary": {
            "option_count": len(option_symbols),
            "chain_rows": len(option_chain),
            "selected_contracts": len(selected_contracts),
            "errors": len(errors),
        },
        "underlying": {
            "symbol": symbol,
            "available_expiry_dates": sorted(expiry_dates),
        },
        "selected_contracts": selected_contracts,
        "option_chain": option_chain,
        "option_symbols": option_symbols,
        "option_quote": option_quote,
        "quote": quote,
        "static_info": static_info,
        "depth": {
            "method": depth_method,
            "count": len(depth_rows),
            "rows": depth_rows,
        },
        "trades": {
            "method": trade_method,
            "count": len(trade_rows),
            "rows": trade_rows,
        },
        "brokers": {
            "method": broker_method,
            "count": len(broker_rows),
            "rows": broker_rows,
        },
        "errors": errors,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    markdown_output = str(Path(args.output).with_suffix(".md"))
    with open(markdown_output, "w", encoding="utf-8") as f:
        f.write(generate_markdown_report(result))

    print(
        "完成: "
        f"已抓取 {len(option_symbols)} 个期权合约，输出到 {args.output}，"
        f"并生成报告 {markdown_output}"
    )


if __name__ == "__main__":
    main()
