#!/bin/bash
# 测试运行（使用本地数据 + 限制10只股票）
# 用法: ./scripts/test-run.sh

cd "$(dirname "$0")/.."
uv run python main.py --use-local --limit 10
