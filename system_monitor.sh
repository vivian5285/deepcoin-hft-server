#!/bin/bash
# system_monitor.sh (Deepcoin 引擎专属巡检守护神)

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
if [ -f "$DIR/.env" ]; then
    export $(cat "$DIR/.env" | grep -v '#' | awk '/=/ {print $1}')
fi

WEBHOOK_URL=${DINGTALK_WEBHOOK}

# 物理雷达：直接探测 5004 端口的心跳
if ! netstat -tuln | grep -q ":5004 "; then
    echo "$(date +'%Y-%m-%d %H:%M:%S') - 🚨 警告: 深币引擎(端口5004)已离线，正在执行紧急抢救..."
    
    # 自动重燃点火脚本
    cd $DIR
    bash deploy_deepcoin.sh
    sleep 3
    
    if netstat -tuln | grep -q ":5004 "; then
        STATUS_TEXT="✅ **抢救成功**：守护脚本已自动执行启动程序，深币引擎现已恢复监听 5004 端口，继续狩猎！"
    else
        STATUS_TEXT="❌ **抢救失败**：重启尝试无效，请立即使用 SSH 登入服务器排查日志！"
    fi
    
    if [ -n "$WEBHOOK_URL" ]; then
        MSG=$(cat <<EOF
{
    "msgtype": "markdown",
    "markdown": {
        "title": "🚨 深币引擎掉线警报",
        "text": "### 🚨 深币(Deepcoin) 极速引擎意外宕机！\n\n> **发生时间**：$(date +'%Y-%m-%d %H:%M:%S')\n> **进程状态**：端口 5004 丢失\n\n**自动应对措施**：\n$STATUS_TEXT\n\n*🛡️ 深币系统底层巡检哨兵*"
    },
    "at": {"isAtAll": true}
}
EOF
)
        curl -s -H "Content-Type: application/json" -d "$MSG" $WEBHOOK_URL > /dev/null
    fi
else
    echo "$(date +'%Y-%m-%d %H:%M:%S') - ✅ 巡检正常: Deepcoin 引擎 (Port 5004) 运行健康中。"
fi
