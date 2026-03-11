FROM python:3.12-slim

# 配置国内镜像源
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's|http://security.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 配置 pip 国内镜像源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 安装 uv
RUN pip install uv

WORKDIR /app

# 复制项目文件
COPY pyproject.toml ./
COPY uv.lock ./
COPY config ./config
COPY src ./src

# 安装依赖
RUN uv pip install --system -e .

# 创建数据目录
RUN mkdir -p data logs

# 暴露端口
EXPOSE 8092

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8092/health || exit 1

# 启动命令
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8092"]