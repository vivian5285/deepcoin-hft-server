#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, time, hmac, hashlib, base64, urllib.parse, logging, requests
from datetime import datetime

logger = logging.getLogger(__name__)

WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
SECRET = os.getenv("DINGTALK_SECRET", "")

def _get_signed_url():
    if not SECRET: return WEBHOOK
    ts = str(round(time.time() * 1000))
    hmac_code = hmac.new(SECRET.encode('utf-8'), f'{ts}\n{SECRET}'.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{WEBHOOK}&timestamp={ts}&sign={sign}"

def send_alert(title, data_dict):
    text = "\n".join([f"- **{k}**: {v}" for k, v in data_dict.items()])
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"### {title}\n> **⏱ 战神大脑核对**：{datetime.now().strftime('%m-%d %H:%M:%S')}\n\n{text}\n\n---\n*🤖 ETH 万亿战神 V8.5 实时守护*"
        }
    }
    try:
        requests.post(_get_signed_url(), json=payload, timeout=5)
    except Exception as e:
        logger.error(f"钉钉发送失败: {e}")

def report_deepcoin_open(side, price, qty, tp_px, sl_px):
    emoji = "🟩" if side == "LONG" else "🟥"
    send_alert("⚔️ 战神建仓完毕 (单向一手)", {
        "防守方向": f"{emoji} {side}",
        "入场均价": f"{price:.2f}",
        "持仓头寸": f"{qty} 张",
        "限价止盈 (3U目标)": f"{tp_px:.2f}",
        "限价止损 (20U铁律)": f"{sl_px:.2f}"
    })

def report_intervention(qty, entry_px, new_tp, new_sl):
    send_alert("⚠️ 察觉人工干预：自动修正防线", {
        "最新真实持仓": f"{qty} 张",
        "最新均价": f"{entry_px:.2f}",
        "动作": "已撤销旧单，重新铺设专属限价止盈/止损网",
        "新止盈价": f"{new_tp:.2f}",
        "新止损价": f"{new_sl:.2f}"
    })

def report_deepcoin_clear(reason):
    send_alert("🧹 阵地彻底清盘", {"触发原因": reason, "当前状态": "挂单已撤销，仓位已全平，空仓待命"})
