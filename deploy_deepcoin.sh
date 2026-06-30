#!/bin/bash
# ==========================================
# 深币双擎 - 工业级并发自动化部署 (核武清场版)
# ==========================================

PORT=5004
LOG_FILE="supervisor_deepcoin.log"
GATEWAY_LOG="gateway_deepcoin.log"

echo -e "\033[1;36m=== 正在执行深币系统详细部署与环境重置 ===\033[0m"

# [1/5] 彻底清理审计
echo -e "\033[0;33m[1/5] 正在执行端口清理与残留进程剔除...\033[0m"
fuser -k -9 $PORT/tcp 2>/dev/null
pkill -9 -f "app.py" 2>/dev/null
pkill -9 -f "gunicorn.*$PORT" 2>/dev/null
pkill -9 -f "position_supervisor_deepcoin.py" 2>/dev/null
sleep 2
echo "  -> 历史进程与端口已完成强制清理。"

# [2/5] 依赖检查
echo -e "\033[0;33m[2/5] 检查并安装高级核心依赖...\033[0m"
source venv/bin/activate 2>/dev/null || echo "未找到 venv，使用全局环境"
pip install -q requests flask gunicorn python-dotenv
echo "  -> 核心依赖已确保就绪。"

# [3/5] 启动审计
echo -e "\033[0;33m[3/5] 正在启动毫秒级守护进程...\033[0m"
mkdir -p logs
nohup gunicorn --workers 2 --threads 4 -b 0.0.0.0:$PORT app:app > "$GATEWAY_LOG" 2>&1 &
nohup python3 -u position_supervisor_deepcoin.py > "$LOG_FILE" 2>&1 &
echo "  -> 深币网关(Gunicorn)与大脑(Supervisor)已点火启动。"

# [4/5] 详细健康自检
echo -e "\033[0;33m[4/5] 正在进行详细健康与回路审计 (等待3秒)...\033[0m"
sleep 3

echo -e "  -> 核心进程监听审计:"
ps -ef | grep -E "gunicorn|position_supervisor_deepcoin" | grep -v grep | awk '{print "     PID: "$2", 进程: "$8" "$9}'

if netstat -tuln | grep -q ":$PORT "; then
    echo -e "  -> 端口状态: \033[0;32mLISTEN (Port $PORT)\033[0m"
    echo -e "  -> 本地网关回路测试:"
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:$PORT/webhook -H "Content-Type: application/json" -d '{"secret": "528586", "action": "PING"}')
    if [ "$HTTP_STATUS" -eq 200 ]; then
        echo -e "     \033[0;32m✅ 本地网关 200 OK，大脑通信回路极度畅通。\033[0m"
    else
        echo -e "     \033[0;31m⚠️ 本地网关响应异常，HTTP 状态码: $HTTP_STATUS\033[0m"
    fi
else
    echo -e "  -> 端口状态: \033[0;31mFAILED (请检查 gateway_deepcoin.log)\033[0m"
fi

echo -e "\n\033[1;36m=== 🚀 深币(Deepcoin)系统实盘升级完成 ===\033[0m"
echo -e "可以通过 \`tail -f supervisor_deepcoin.log\` 查看深币交易日志。\n"
