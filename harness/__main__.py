"""Harness CLI 入口 — 命令行启动 Agent。

使用方式:
    python -m harness run "帮我读 README.md"
    python -m harness eval ./tests/eval_suite.json
    python -m harness config  # 显示当前配置
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Harness Agent Runtime — 通用 Agent 执行框架",
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="配置文件路径 (JSON/YAML)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # run 命令
    run_parser = subparsers.add_parser("run", help="运行一个任务")
    run_parser.add_argument("task", help="任务描述")
    run_parser.add_argument(
        "--session", "-s",
        default=None,
        help="Session ID (用于恢复中断的任务)",
    )
    run_parser.add_argument(
        "--steps", "-n",
        type=int,
        default=50,
        help="最大步骤数 (默认: 50)",
    )

    # eval 命令
    eval_parser = subparsers.add_parser("eval", help="运行评估套件")
    eval_parser.add_argument("suite", help="评估套件文件路径 (JSON)")
    eval_parser.add_argument(
        "--output", "-o",
        default=None,
        help="评估报告输出路径",
    )

    # config 命令
    subparsers.add_parser("config", help="显示当前配置")

    # info 命令
    subparsers.add_parser("info", help="显示 Harness 信息")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "config":
        show_config()
    elif args.command == "info":
        show_info()
    elif args.command == "run":
        asyncio.run(run_task(args))
    elif args.command == "eval":
        asyncio.run(run_eval(args))


def show_config() -> None:
    """显示当前配置。"""
    from harness.config.schema import HarnessConfig
    config = HarnessConfig.default()
    print(json.dumps({
        "name": config.name,
        "max_steps": config.max_steps,
        "permission_level": config.permission_level.name,
        "llm": {
            "provider": config.llm.provider,
            "model": config.llm.model,
        },
        "memory": {
            "working_max_tokens": config.memory.working_max_tokens,
            "episodic_persist_dir": config.memory.episodic_persist_dir,
        },
        "recovery": {
            "checkpoint_dir": config.recovery.checkpoint_dir,
            "checkpoint_interval": config.recovery.checkpoint_interval,
        },
    }, ensure_ascii=False, indent=2))


def show_info() -> None:
    """显示 Harness 信息。"""
    print("Harness Agent Runtime v0.1.0")
    print("=" * 40)
    print("Python:", sys.version.split()[0])
    print("Platform:", sys.platform)
    print()
    print("Three dimensions:")
    print("  1. Universal Base — Loop, Permissions, Hooks, Memory, Recovery")
    print("  2. Capabilities — Plugins + Skills")
    print("  3. Feedback Loop — Tracing, Eval, Attribution, Optimization")


async def run_task(args: argparse.Namespace) -> None:
    """运行任务。"""
    from harness import Harness
    from harness.config.schema import HarnessConfig
    from harness.feedback.integration import FeedbackIntegrator

    config = HarnessConfig.default()
    config.max_steps = args.steps

    if args.verbose:
        print(f"Starting Harness...")
        print(f"Task: {args.task}")
        print(f"Max steps: {args.steps}")
        print()

    h = Harness(config=config)
    await h.start()

    # 集成反馈闭环
    feedback = FeedbackIntegrator()
    trace_id = feedback.start_trace()

    try:
        result = await h.run(args.task, session_id=args.session)

        # 输出结果
        if args.verbose:
            print(f"\nSession: {result.session_id}")
            print(f"Status: {result.status.name}")
            print(f"Steps: {len(result.steps)}")
            print(f"Duration: {result.total_duration:.2f}s")
            if result.error:
                print(f"Error: {result.error}")
        else:
            print(result.output or "(no output)")

        # 反馈分析
        analysis = feedback.end_trace_and_analyze()
        if analysis.get("status") == "analyzed" and args.verbose:
            attr = analysis["attribution"]
            print(f"\n[Feedback] Root cause: {attr.root_cause}")
            print(f"[Feedback] Suggestion: {attr.suggestion}")
            sug = analysis["suggestion"]
            if sug["auto_applicable"]:
                print(f"[Feedback] Auto-applicable fix available for: {sug['target']}")

    finally:
        await h.stop()


async def run_eval(args: argparse.Namespace) -> None:
    """运行评估。"""
    from harness import Harness
    from harness.feedback.eval import EvalSuite, EvalRunner

    suite = EvalSuite.from_file(args.suite)
    print(f"Loaded eval suite: '{suite.name}' ({suite.count} cases)")

    h = Harness()
    await h.start()

    try:
        runner = EvalRunner(harness=h)
        report = await runner.run_suite(suite)

        runner.print_report(report)

        if args.output:
            runner.save_report(report, args.output)
            print(f"Report saved to: {args.output}")

    finally:
        await h.stop()


if __name__ == "__main__":
    main()
