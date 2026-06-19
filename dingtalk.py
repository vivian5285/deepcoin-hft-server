#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, time, hmac, hashlib, base64, urllib.parse, logging, requests
from datetime import datetime
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
logger = logging.getLogger(__name__)

DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

def _get_signed_url():
    if not DINGTALK_SECRET: return DINGTALK_WEBHOOK
    ts = str(round(time.time() * 1000))
    hmac_code = hmac.new(DINGTALK_SECRET.encode('utf-8'), f'{ts}\n{DINGTALK_SECRET}'.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={sign}"

def send_alert(title, data_dict):
    text = "\n".join([f"- **{k}**: {v}" for k, v in data_dict.items()])
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"### {title}\n> **⏱ 战神核对**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{text}\n\n---\n*🤖 深币(Deepcoin) 战神 V10.1 终极版*"
        }
    }
    try: requests.post(_get_signed_url(), json=payload, timeout=5)
    except: pass

def report_deepcoin_open(side, price, qty, tp_pxs, sl_px, atr, old_qty=0):
    emoji = "🟩" if side == "LONG" else "🟥"
    
    # 🚀 V10.1 新增：旧仓遗留识别与警报
    clean_msg = "✅ 纯净新开 (旧仓已成功清零)" if old_qty == 0 else f"🚨 战阵反转 (已强平之前遗留的 {old_qty} 张)"

    send_alert("⚔️ 深币现价吃单 (参数全透传)", {
        "防守方向": f"{emoji} {side}",
        "实盘均价": f"`{price:.2f}`",
        "动态头寸": f"`{qty}` 张 (30/30/40切分)",
        "状态反馈": clean_msg,
        "真实波动(ATR)": f"`{atr:.2f}` 美金",
        "自适应止盈": f"`{tp_pxs[0]}` | `{tp_pxs[1]}` | `{tp_pxs[2]}`",
        "初始止损": f"`{sl_px:.2f}`"
    })

def report_intervention(qty, entry_px, new_tp, new_sl, action_msg):
    send_alert("⚠️ 雷达动态追踪启动", {
        "当前残余头寸": f"`{qty}` 张",
        "更新后均价": f"`{entry_px:.2f}`",
        "当前状态": f"**{action_msg}**",
        "当前安全止损": f"`{new_sl:.2f}`"
    })

def report_force_align(real_side, expected_side):
    send_alert("🚨 严重违纪事件：触发铁血镇压", {"实盘方向": real_side, "TV应有方向": expected_side, "处理结果": "已强行清仓，坚决对齐信号！"})

def report_deepcoin_clear(reason):
    send_alert("🧹 战阵彻底清盘", {"触发机制": reason, "当前状态": "挂单全撤，仓位全平，资金回炉待命"})

def report_system_alert(title, detail):
    send_alert(f"⚠️ 系统告警: {title}", {"详情": detail})
