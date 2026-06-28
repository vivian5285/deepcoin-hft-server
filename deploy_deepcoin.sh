#!/bin/bash
# ==========================================
# 深币紫金双擎 - 工业级并发自动化部署 v8.0
# ==========================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PORT=5004
LOG_FILE="app.log"

echo -e "${CYAN}====================================================${NC}"
echo -e "${CYAN}🚀 开始部署并重启 深币极速印钞机 (Gunicorn 升级版)...${NC}"
echo -e "${CYAN}====================================================${NC}"

# ==========================================
# 1. 强制清理端口和历史幽灵进程
# ==========================================
echo -e "\n${YELLOW}🧹 [1/4] 正在执行核弹级清场，释放端口 $PORT...${NC}"
if command -v fuser >/dev/null 2>&1; then
    fuser -k -9 $PORT/tcp >/dev/null 2>&1
else
    lsof -t -i:$PORT | xargs -r kill -9 >/dev/null 2>&1
fi
pkill -9 -f "app.py" >/dev/null 2>&1
pkill -9 -f "gunicorn.*$PORT" >/dev/null 2>&1
sleep 2

if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo -e "${RED}❌ 致命错误：端口 $PORT 依然被死死占用！${NC}"
    exit 1
else
    echo -e "${GREEN}✅ 阵地已打扫完毕，端口 $PORT 纯净无污染。${NC}"
fi

# ==========================================
# 2. 激活虚拟环境 & 补充 Gunicorn
# ==========================================
echo -e "\n${YELLOW}📦 [2/4] 正在加载兵器库 (虚拟环境)...${NC}"
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
    pip install -q gunicorn  # 确保深币也安装了保时捷引擎
    echo -e "${GREEN}✅ Python 虚拟环境及 Gunicorn 核心就绪。${NC}"
else
    echo -e "${RED}❌ 找不到 venv/bin/activate！${NC}"
    exit 1
fi

# ==========================================
# 3. 后台守护启动服务 (Gunicorn 10线程爆发)
# ==========================================
echo -e "\n${YELLOW}⚙️ [3/4] 正在启动毫秒级并发大脑 ...${NC}"
# 🚀 核心升级：替换 python3 app.py 为 Gunicorn
nohup gunicorn --workers 1 --threads 10 -b 127.0.0.1:$PORT app:app > $LOG_FILE 2>&1 &
APP_PID=$!

echo -e "${YELLOW}⏳ 正在等待引擎点火预热 (4秒)...${NC}"
sleep 4

# ==========================================
# 4. 终极健康状态自检
# ==========================================
echo -e "\n${YELLOW}🔬 [4/4] 执行服务健康与高并发回路自检...${NC}"

if ps -p $APP_PID > /dev/null; then
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        echo -e "${GREEN}🎉 部署大获成功！深币工业级网关已在后台隐身运行。${NC}"
        
        # 回路测探
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:$PORT/webhook -H "Content-Type: application/json" -d '{"secret":"528586","action":"PING"}')
        if [ "$HTTP_CODE" == "200" ]; then
            echo -e "   ${GREEN}✅ 本地穿透测试 200 OK，大脑通信回路极度畅通。${NC}"
        else
            echo -e "   ${RED}❌ 网关回路异常 (HTTP: $HTTP_CODE)${NC}"
        fi

        echo -e "${CYAN}📍 进程守护 PID: $APP_PID | 📡 监听端口: $PORT${NC}"
        echo -e "\n${YELLOW}📄 最近日志：${NC}"
        tail -n 5 $LOG_FILE
    else
        echo -e "${RED}❌ 警告：进程活着但未监听 $PORT！报错详情：${NC}"
        tail -n 10 $LOG_FILE
    fi
else
    echo -e "${RED}❌ 启动失败！程序点火后意外坠毁。${NC}"
    tail -n 10 $LOG_FILE
    exit 1
fi
echo -e "\n${GREEN}====================================================${NC}"
echo -e "${GREEN}✅ Deepcoin 自动化运维并发升级完毕！${NC}"
echo -e "${GREEN}====================================================${NC}"
