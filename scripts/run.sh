#!/bin/bash
# 完整运行（从API获取持仓数据）
# 用法: ./scripts/run.sh

cd "$(dirname "$0")/.."
uv run python main.py
