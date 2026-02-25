#!/usr/bin/env python3
"""抓取指定标的、指定到期日的期权全量可用信息（基于 Longbridge Python SDK）。"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable, Sequence

try:
    from longport.openapi import Config, QuoteContext
except Exception as exc:  # pragma: no cover - 仅用于运行时提示
    raise SystemExit(
        "未找到 longport SDK，请先安装并配置环境后再运行。"
        "\n参考: https://open.longbridge.com/docs/getting-started.md"
    ) from exc


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
    return parser.parse_args()


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
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        # Enum
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, (str, int, float, bool)):
            return enum_value
    if hasattr(value, "__dict__"):
        return {k: to_python(v) for k, v in vars(value).items() if not k.startswith("_")}
    return value


def chunked(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def try_call(
    ctx: QuoteContext,
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


def fetch_batched(
    ctx: QuoteContext,
    option_symbols: Sequence[str],
    batch_size: int,
    method_names: Sequence[str],
    result_name: str,
    transform: Callable[[Any], Any] | None = None,
) -> dict[str, Any]:
    all_rows: list[Any] = []
    used_method: str | None = None
    for batch in chunked(option_symbols, batch_size):
        method, rows = try_call(ctx, method_names, list(batch))
        used_method = used_method or method
        all_rows.extend(rows or [])

    payload: dict[str, Any] = {
        "method": used_method,
        "count": len(all_rows),
        result_name: to_python(all_rows),
    }
    if transform:
        payload = transform(payload)
    return payload


def main() -> None:
    args = parse_args()
    expiry = date.fromisoformat(args.expiry)

    # 优先从环境变量读取；若本地已有 ~/.longport/config.toml 也可直接生效。
    config = Config.from_env()
    ctx = QuoteContext(config)

    used_methods: dict[str, str] = {}

    # 1) 读取可用到期日并校验
    expiry_method, expiry_list = try_call(
        ctx,
        ["option_chain_expiry_date_list", "option_chain_expiry_date"],
        args.symbol,
    )
    used_methods["expiry_dates"] = expiry_method
    expiry_dates = {to_python(d) for d in expiry_list}
    if args.expiry not in expiry_dates:
        available = ", ".join(sorted(expiry_dates))
        raise SystemExit(
            f"到期日 {args.expiry} 不在可选列表中。\n"
            f"标的: {args.symbol}\n可选到期日: {available}"
        )

    # 2) 获取该到期日的完整期权链
    chain_method, chain_rows = try_call(
        ctx,
        ["option_chain_info_by_date", "option_chain_by_date"],
        args.symbol,
        expiry,
    )
    used_methods["option_chain"] = chain_method
    option_chain = to_python(chain_rows)

    option_symbols = sorted(
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

    if not option_symbols:
        raise SystemExit(
            f"未在 {args.symbol} {args.expiry} 的期权链中提取到期权代码。"
        )

    # 3) 拉取期权和证券层面的可用行情数据
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

    # 深度 / 逐笔 / 经纪队列一般为单标的调用，逐个抓取
    depth_rows = []
    trade_rows = []
    broker_rows = []
    depth_method = trade_method = broker_method = None
    for symbol in option_symbols:
        if depth_method is None:
            depth_method, depth = try_call(ctx, ["depth", "security_depth"], symbol)
        else:
            _, depth = try_call(ctx, [depth_method], symbol)
        depth_rows.append({"symbol": symbol, "data": to_python(depth)})

        if trade_method is None:
            trade_method, trades = try_call(ctx, ["trades", "security_trades"], symbol)
        else:
            _, trades = try_call(ctx, [trade_method], symbol)
        trade_rows.append({"symbol": symbol, "data": to_python(trades)})

        if broker_method is None:
            broker_method, brokers = try_call(ctx, ["brokers", "security_brokers"], symbol)
        else:
            _, brokers = try_call(ctx, [broker_method], symbol)
        broker_rows.append({"symbol": symbol, "data": to_python(brokers)})

    used_methods["depth"] = depth_method or ""
    used_methods["trades"] = trade_method or ""
    used_methods["brokers"] = broker_method or ""

    result = {
        "requested": {
            "symbol": args.symbol,
            "expiry": args.expiry,
            "batch_size": args.batch_size,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        },
        "sdk_methods": used_methods,
        "summary": {
            "option_count": len(option_symbols),
            "chain_rows": len(option_chain),
        },
        "underlying": {
            "symbol": args.symbol,
            "available_expiry_dates": sorted(expiry_dates),
        },
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
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"完成: 已抓取 {len(option_symbols)} 个期权合约，输出到 {args.output}")


if __name__ == "__main__":
    main()
