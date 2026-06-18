#!/bin/bash
# ==============================================
# 深币(Deepcoin) 独立系统全域部署脚本 (V7.0 终极实战版)
# ==============================================

# 注意这里的路径，完全适配你刚刚新建的 deepcoin 纯净用户
PROJECT_DIR="/home/deepcoin/deepcoin-hft-server"
PORT=5004
LOG_FILE="gateway_deepcoin.log"

GREEN='\033[1;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== 🚀 正在执行深币(Deepcoin)独立引擎极速部署 ===${NC}"

cd $PROJECT_DIR || { echo -e "${RED}❌ 目录 $PROJECT_DIR 不存在，请检查！${NC}"; exit 1; }

echo -e "${YELLOW}[1/4] 正在执行端口 5004 清理与残留进程剔除...${NC}"
sudo fuser -k -n tcp $PORT >/dev/null 2>&1
sudo pkill -f "gunicorn -b 127.0.0.1:$PORT" >/dev/null 2>&1
sleep 2

echo -e "${YELLOW}[2/4] 正在清理历史战报日志...${NC}"
rm -f $LOG_FILE

echo -e "${YELLOW}[3/4] 激活外层专属虚拟环境并安装依赖...${NC}"
source venv/bin/activate
pip install -r requirements.txt --quiet

echo -e "${YELLOW}[4/4] 启动深币信号网关 (端口 $PORT)...${NC}"
nohup gunicorn -b 127.0.0.1:$PORT app:app > $LOG_FILE 2>&1 &

echo -e "${YELLOW}=== ⏳ 等待引擎预热 (3秒) ===${NC}"
sleep 3

if netstat -tuln | grep -q ":$PORT "; then
    echo -e "${GREEN}=== ✅ 深币(Deepcoin)微利剥头皮引擎启动完成 (Port 5004) ===${NC}"
    echo -e "你可以通过 'tail -f $LOG_FILE' 查看实盘战报。"
else
    echo -e "${RED}❌ 启动失败！端口 $PORT 未监听，请查看 $LOG_FILE 排查错误。${NC}"
fi
