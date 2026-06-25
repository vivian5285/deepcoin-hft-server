#!/bin/bash

# ==========================================
# 深币紫金双擎 - 终极自动化部署脚本 v7.0
# ==========================================

# 颜色定义 (让输出更加骚气清晰)
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

PORT=5004
APP_NAME="app.py"
LOG_FILE="app.log"

echo -e "${CYAN}====================================================${NC}"
echo -e "${CYAN}🚀 开始部署并重启 深币紫金印钞机 (Deepcoin VPS)...${NC}"
echo -e "${CYAN}====================================================${NC}"

# ==========================================
# 1. 强制清理端口和历史幽灵进程
# ==========================================
echo -e "\n${YELLOW}🧹 [1/4] 正在执行核弹级清场，释放端口 $PORT...${NC}"

# 使用 fuser 强杀霸占 5004 的元凶
if command -v fuser >/dev/null 2>&1; then
    fuser -k -9 $PORT/tcp >/dev/null 2>&1
else
    # 备用方案 lsof 强杀
    lsof -t -i:$PORT | xargs -r kill -9 >/dev/null 2>&1
fi

# 兜底强杀所有名叫 app.py 的进程
pkill -9 -f $APP_NAME >/dev/null 2>&1

# 停顿 2 秒，给系统内核回收网络 Socket 的时间
sleep 2

# 严谨自检：端口是否真的干净了？
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${RED}❌ 致命错误：端口 $PORT 依然被死死占用！清理失败，请手工介入。${NC}"
    exit 1
else
    echo -e "${GREEN}✅ 阵地已打扫完毕，端口 $PORT 纯净无污染。${NC}"
fi

# ==========================================
# 2. 激活 Python 虚拟环境
# ==========================================
echo -e "\n${YELLOW}📦 [2/4] 正在加载兵器库 (虚拟环境)...${NC}"
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    echo -e "${GREEN}✅ Python 虚拟环境 (venv) 激活成功。${NC}"
else
    echo -e "${RED}❌ 找不到 venv/bin/activate，请检查是否在正确的目录下！${NC}"
    exit 1
fi

# ==========================================
# 3. 后台守护启动服务
# ==========================================
echo -e "\n${YELLOW}⚙️ [3/4] 正在启动智慧大脑 $APP_NAME ...${NC}"
# nohup 会把程序扔进系统后台，并且把所有输出塞进 app.log
nohup python3 $APP_NAME > $LOG_FILE 2>&1 &
APP_PID=$!

echo -e "${YELLOW}⏳ 正在等待引擎点火预热 (5秒)...${NC}"
sleep 5

# ==========================================
# 4. 终极健康状态自检
# ==========================================
echo -e "\n${YELLOW}🔬 [4/4] 执行服务健康自检...${NC}"

# 检查 1: 进程是否还活着？
if ps -p $APP_PID > /dev/null; then
    # 检查 2: 端口是否正常亮起？
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo -e "${GREEN}🎉 部署大获成功！深币双擎系统已在后台隐身运行。${NC}"
        echo -e "${CYAN}📍 进程守护 PID: $APP_PID${NC}"
        echo -e "${CYAN}📡 稳定监听端口: $PORT${NC}"
        echo -e "\n${YELLOW}📄 最近 10 行实时启动日志：${NC}"
        echo -e "${CYAN}---------------------------------------------------${NC}"
        tail -n 10 $LOG_FILE
        echo -e "${CYAN}---------------------------------------------------${NC}"
        echo -e "${GREEN}✨ (随时输入 'tail -f $LOG_FILE' 即可像看电影一样观看实时运行情况)${NC}"
    else
        echo -e "${RED}❌ 警告：进程虽然活着，但没有监听 $PORT 端口！可能是代码内部报错了。${NC}"
        echo -e "${YELLOW}请立刻查看报错详情：${NC}"
        tail -n 15 $LOG_FILE
    fi
else
    echo -e "${RED}❌ 启动失败！程序点火后意外坠毁。${NC}"
    echo -e "${YELLOW}坠毁黑匣子日志：${NC}"
    tail -n 15 $LOG_FILE
    exit 1
fi

echo -e "\n${GREEN}====================================================${NC}"
echo -e "${GREEN}✅ Deepcoin 自动化运维流程完毕！${NC}"
echo -e "${GREEN}====================================================${NC}"
