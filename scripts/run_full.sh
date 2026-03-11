#!/bin/bash
# 完整运行 - 先获取持仓数据再计算
cd "$(dirname "$0")/.."
uv run python main.py
