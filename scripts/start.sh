#!/bin/bash
# 启动 dividend-select 服务
# 用法: ./scripts/start.sh

cd "$(dirname "$0")/.."

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    echo "错误: 虚拟环境不存在，请先运行: uv venv"
    exit 1
fi

# 激活虚拟环境
source .venv/bin/activate

# 检查 CSV 文件
if [ ! -f "data/近3年股息率汇总.csv" ]; then
    echo "警告: 数据文件不存在，请先运行 ./scripts/run.sh 生成数据"
fi

# 启动服务
echo "启动 dividend-select 服务..."
python src/main.py