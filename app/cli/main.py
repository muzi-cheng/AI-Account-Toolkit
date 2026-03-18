from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-Account-Toolkit CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("register", help="执行批量注册")

    maintain_parser = subparsers.add_parser("maintain", help="持续保号：巡检本地账号并自动补足到 total_accounts")
    maintain_parser.add_argument("--interval", type=int, default=0, help="巡检周期秒数")

    check_parser = subparsers.add_parser("check-tokens", help="巡检本地账号，并删除 401+deactivated 的账号")
    check_parser.add_argument("--input", default="", help="账号输入文件")
    check_parser.add_argument("--report", default="", help="检测报告输出文件")

    return parser
