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
            "text": f"### {title}\n> **⏱ 战神核对**：{datetime.now().strftime('%m-%d %H:%M:%S')}\n\n{text}\n\n---\n*🤖 ETH 万亿战神 V8.6 全域防线守护中*"
        }
    }
    try:
        requests.post(_get_signed_url(), json=payload, timeout=5)
    except Exception as e:
        logger.error(f"钉钉发送失败: {e}")

def report_deepcoin_open(side, price, qty, tp1_px, tp2_px, sl_px):
    emoji = "🟩" if side == "LONG" else "🟥"
    send_alert("⚔️ 战神建仓完毕 (单向清场式介入)", {
        "防守方向": f"{emoji} {side}",
        "入场均价": f"`{price:.2f}`",
        "标准头寸": f"`{qty}` 张",
        "TP1 止盈 (7U)": f"`{tp1_px:.2f}`",
        "TP2 止盈 (15U)": f"`{tp2_px:.2f}`",
        "绝境止损 (20U)": f"`{sl_px:.2f}`"
    })

def report_intervention(qty, entry_px, new_tp, new_sl):
    send_alert("⚠️ 察觉仓位异动：已自愈重新布防", {
        "触发原因": "检测到人工加减仓，或 TP1 已落袋",
        "最新残余仓位": f"`{qty}` 张",
        "最新均价": f"`{entry_px:.2f}`",
        "动作": "已撤销所有旧单，生成全新专属防线",
        "剩余全仓止盈": f"`{new_tp:.2f}`",
        "新限价止损": f"`{new_sl:.2f}`"
    })

def report_deepcoin_clear(reason):
    send_alert("🧹 阵地彻底清盘", {"触发原因": reason, "当前状态": "残单已全撤，仓位已全平，战阵重置为空仓"})
