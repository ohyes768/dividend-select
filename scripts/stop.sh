#!/bin/bash
# 停止 dividend-select 服务
# 用法: ./scripts/stop.sh

echo "停止 dividend-select 服务..."

# 查找并杀掉进程
PID=$(pgrep -f "src.main:app" || pgrep -f "python src/main.py")

if [ -n "$PID" ]; then
    kill $PID
    echo "服务已停止 (PID: $PID)"
else
    echo "服务未运行"
fi