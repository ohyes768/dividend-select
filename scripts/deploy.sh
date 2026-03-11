#!/bin/bash
# dividend-select Docker 部署脚本
# 用法: ./scripts/deploy.sh

set -e

echo "=== dividend-select Docker 部署脚本 ==="

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "错误: Docker 未安装"
    exit 1
fi

# 检查 docker-compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "错误: docker-compose 未安装"
    exit 1
fi

# 使用 docker compose 还是 docker-compose
COMPOSE_CMD="docker compose"
if ! docker compose version &> /dev/null; then
    COMPOSE_CMD="docker-compose"
fi

# 创建数据目录
echo "创建数据目录..."
mkdir -p data logs

# 停止旧容器
echo "停止旧容器..."
$COMPOSE_CMD down 2>/dev/null || true

# 构建镜像
echo "构建镜像..."
$COMPOSE_CMD build

# 启动服务
echo "启动服务..."
$COMPOSE_CMD up -d

# 等待服务启动
echo "等待服务启动..."
sleep 5

# 健康检查
echo "健康检查..."
if curl -sf http://localhost:8092/health > /dev/null 2>&1; then
    echo "✅ 服务启动成功!"
    echo ""
    echo "本地访问:"
    echo "  - API 文档: http://localhost:8092/docs"
    echo "  - 健康检查: http://localhost:8092/health"
    echo "  - 股票列表: http://localhost:8092/api/stocks"
    echo ""
    echo "查看日志: $COMPOSE_CMD logs -f"
    echo "停止服务: $COMPOSE_CMD down"
else
    echo "❌ 服务启动失败，请检查日志"
    $COMPOSE_CMD logs
fi