# 使用Python 3.9作为基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# # 安装系统依赖（如果需要编译扩展）
# RUN apt-get update && apt-get install -y \
#     gcc \
#     && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY . /app

# 创建必要的目录
RUN mkdir -p /app/web/db

# 安装Python依赖
RUN pip install --no-cache-dir \
    Flask==2.3.3 \
    Flask-SocketIO==5.3.4 \
    python-socketio==5.9.0 \
    eventlet==0.33.3 \
    Werkzeug==2.3.7

# 暴露端口
EXPOSE 8443

# 设置环境变量
ENV FLASK_APP=web/app.py
ENV FLASK_ENV=production

# 运行应用
CMD ["python", "web/app.py"]
