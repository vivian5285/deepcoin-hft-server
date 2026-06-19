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
            "text": f"### {title}\n> **⏱ 战神核对**：{datetime.now().strftime('%m-%d %H:%M:%S')}\n\n{text}\n\n---\n*🤖 ETH 万亿战神 V8.7 复利守护引擎*"
        }
    }
    try:
        requests.post(_get_signed_url(), json=payload, timeout=5)
    except Exception as e:
        logger.error(f"钉钉发送失败: {e}")

def report_deepcoin_open(side, price, qty, tp1_px, tp2_px, sl_px):
    emoji = "🟩" if side == "LONG" else "🟥"
    send_alert("⚔️ 战神已市价抢跑 (偶数动态复利)", {
        "防守方向": f"{emoji} {side}",
        "实盘均价": f"`{price:.2f}`",
        "核算头寸": f"`{qty}` 张 (已拆分对半防线)",
        "TP1 落袋 (7U)": f"`{tp1_px:.2f}`",
        "TP2 止盈 (15U)": f"`{tp2_px:.2f}`",
        "绝对止损 (20U)": f"`{sl_px:.2f}`"
    })

def report_intervention(qty, entry_px, new_tp, new_sl):
    send_alert("⚠️ 察觉仓位异动：哨兵自愈布防", {
        "触发原因": "检测到人工加减仓，或 TP1 已成功落袋",
        "残余头寸": f"`{qty}` 张",
        "最新均价": f"`{entry_px:.2f}`",
        "动作": "已撤销所有错乱挂单，挂载专属防卫网",
        "全仓止盈位": f"`{new_tp:.2f}`",
        "全仓止损位": f"`{new_sl:.2f}`"
    })

def report_deepcoin_clear(reason):
    send_alert("🧹 战阵彻底清盘", {"触发机制": reason, "当前状态": "挂单全撤，仓位全平，资金回炉待命"})

def report_system_alert(title, detail):
    send_alert(f"⚠️ 系统告警: {title}", {"详情": detail, "状态": "请管理员介入检查"})
