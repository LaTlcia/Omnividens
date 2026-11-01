"""Command parser. Application dependencies are loaded only after parsing."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys


def positive(raw: str) -> float:
    try:
        value = float(raw)
        if not math.isfinite(value) or value <= 0:
            raise ValueError
        return value
    except ValueError:
        raise argparse.ArgumentTypeError("必须为有限正数") from None


def nonnegative(raw: str) -> float:
    try:
        value = float(raw)
        if not math.isfinite(value) or value < 0:
            raise ValueError
        return value
    except ValueError:
        raise argparse.ArgumentTypeError("必须为有限非负数") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lilyrex", description="GVG观战、伤害预估与离线回放")
    parser.add_argument("--config", type=Path, default=Path("config.toml"), help="本机TOML配置路径")
    parser.add_argument('--offline', action='store_true', help='跳过公开主数据更新（watch仍连接观战服务）')
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("watch", help="观战窗口，使用压缩WebSocket")
    record = commands.add_parser("record", help="显式连接并录制事件")
    record.add_argument("--duration", type=positive, default=180)
    record.add_argument("--max-mb", type=positive, default=50)
    record.add_argument("--out", type=Path, required=True)
    replay = commands.add_parser("replay", help="录制回放和分析（GUI启动检查公开主数据）")
    modes = replay.add_subparsers(dest="mode", required=True)
    for mode in ('gui', 'analyze', 'bench'):
        sub = modes.add_parser(mode)
        sub.add_argument('recording', type=Path)
        sub.add_argument('--json', action='store_true', help='输出JSON统计')
        if mode in ('gui', 'bench'):
            sub.add_argument('--timing', choices=('recorded', 'server', 'burst'))
            sub.add_argument('--speed', type=positive)
            sub.add_argument('--start', type=nonnegative, default=0)
            sub.add_argument('--seconds', type=positive, help='实际运行时限（秒）')
            sub.add_argument('--no-warmup', action='store_true', help='跳过历史预热，记牌可能不完整')
            ending = sub.add_mutually_exclusive_group()
            ending.add_argument('--hold', action='store_true', help='EOF保留最终画面（gui默认）')
            ending.add_argument('--exit-at-end', action='store_true', help='EOF退出窗口')
        if mode == 'bench':
            sub.add_argument('--headless', action='store_true', help='只测状态和预估，不加载Tk')
    imp = modes.add_parser('import', help='将旧文本接收帧转换为录制')
    imp.add_argument('recording', type=Path)
    imp.add_argument('--out', type=Path, required=True)
    data = commands.add_parser('data', help='显式本地主数据构建')
    builders = data.add_subparsers(dest='mode', required=True)
    build = builders.add_parser('build')
    build.add_argument('--source', type=Path, required=True)
    build.add_argument('--out', type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        from lilyrex.app import run
        return run(args)
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError) as exc:
        print(json.dumps({'code': 'invalid_input', 'message': str(exc), 'retryable': False}, ensure_ascii=False), file=sys.stderr)
        return 3
    except Exception as exc:
        # Unexpected library exceptions may contain credentials; only name the type.
        print(json.dumps({'code': 'runtime_error', 'message': type(exc).__name__, 'retryable': False}), file=sys.stderr)
        return 1
