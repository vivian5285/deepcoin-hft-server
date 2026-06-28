#!/bin/bash

# ==========================================
# 深币(Deepcoin)侧翼特种阵地 - 终极部署核检脚本 v8.0
# ==========================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

PORT=5004
APP_NAME="app.py"
LOG_FILE="app.log"
SECRET="528586"

echo -e "\n${PURPLE}=== 正在执行深币系统详细部署与全域升级 ===${NC}"

# ==========================================
# [1/5] 端口清理与残留进程剔除
# ==========================================
echo -e "${YELLOW}[1/5] 正在执行端口清理与残留进程剔除...${NC}"
# 找出霸占 5004 端口的进程，以及所有运行 app.py 的残留 Python 进程
PORT_PIDS=$(lsof -t -i:$PORT 2>/dev/null)
APP_PIDS=$(pgrep -f "python3 $APP_NAME" 2>/dev/null)

# 合并 PID 并去重
ALL_PIDS=$(echo "$PORT_PIDS $APP_PIDS" | xargs -n1 2>/dev/null | sort -u | xargs)

if [ ! -z "$ALL_PIDS" ]; then
    echo "  $ALL_PIDS  -> 进程与端口已完成强制清理。"
    kill -9 $ALL_PIDS >/dev/null 2>&1
else
    echo "  -> 无残留进程，环境纯净。"
fi
sleep 1.5

# ==========================================
# [2/5] 检查并加载高级核心依赖
# ==========================================
echo -e "${YELLOW}[2/5] 检查并安装高级核心依赖...${NC}"
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    echo "  -> 核心依赖 (venv 虚拟环境) 已确保就绪。"
else
    echo -e "${RED}  -> 警告: 未发现 venv 虚拟环境，将使用系统全局 Python 环境。${NC}"
fi

# ==========================================
# [3/5] 同步最新代码库
# ==========================================
echo -e "${YELLOW}[3/5] 正在同步最新代码库...${NC}"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    # 尝试拉取最新代码
    git pull origin main >/dev/null 2>&1 || git pull >/dev/null 2>&1
    COMMIT_HASH=$(git rev-parse --short HEAD)
    COMMIT_MSG=$(git log -1 --pretty=%B | head -n 1)
    echo "HEAD is now at $COMMIT_HASH $COMMIT_MSG"
    echo "  -> 代码库已强制更新至 HEAD 版本。"
else
    echo "  -> 当前非 Git 仓库，跳过云端同步，应用本地最新代码。"
fi

# ==========================================
# [4/5] 启动秒级守护进程
# ==========================================
echo -e "${YELLOW}[4/5] 正在启动秒级守护进程...${NC}"
nohup python3 $APP_NAME > $LOG_FILE 2>&1 &
NEW_PID=$!
echo "  -> 网关(Flask)与大脑(Supervisor)已点火启动。"
sleep 3.5 # 给予引擎充分的点火预热时间

# ==========================================
# [5/5] 详细健康与回路审计
# ==========================================
echo -e "${YELLOW}[5/5] 正在进行详细健康与回路审计...${NC}"
echo "  -> 核心进程监听审计："
echo "     PID: $NEW_PID, 启动时间: $(date +'%H:%M')"

if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "  -> 端口状态: ${GREEN}LISTEN (Port $PORT)${NC}"
    
    echo "  -> 本地网关回路测试："
    # 模拟 TV 发送一次假警报，测探大脑的响应状态
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:$PORT/webhook -H "Content-Type: application/json" -d '{"secret":"'$SECRET'","action":"PING"}')
    
    if [ "$HTTP_CODE" == "200" ]; then
        echo -e "     ${GREEN}✅ 本地网关 200 OK，大脑通信回路极度畅通。${NC}"
    else
        echo -e "     ${RED}❌ 网关回路异常 (HTTP: $HTTP_CODE)，请排查 app.py 路由逻辑！${NC}"
    fi
else
    echo -e "  -> 端口状态: ${RED}FAILED (Port $PORT 未监听)${NC}"
    echo "     启动异常，黑匣子最后几行日志如下："
    tail -n 10 $LOG_FILE
fi

echo -e "\n${PURPLE}=== 🚀 深币(Deepcoin)系统实盘升级完成 ===${NC}"
echo -e "可以通过 \`tail -f $LOG_FILE\` 查看 WSS 雷达与交易日志。\n"
