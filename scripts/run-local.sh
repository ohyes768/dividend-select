#!/bin/bash
# 使用本地数据运行（跳过API获取）
# 用法: ./scripts/run-local.sh

cd "$(dirname "$0")/.."
uv run python main.py --use-local
