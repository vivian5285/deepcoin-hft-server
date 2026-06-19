#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深币 (Deepcoin) 专属战报系统 V9.0
适配参数：7/15 止盈网，20美金价差条件止损
"""
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
            "text": f"### {title}\n> **⏱ 战神核对**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n{text}\n\n---\n*🤖 深币(Deepcoin) 战神 V9.0 极速防线守护*"
        }
    }
    try:
        requests.post(_get_signed_url(), json=payload, timeout=5)
    except Exception as e:
        logger.error(f"钉钉发送失败: {e}")

def report_deepcoin_open(side, price, qty, tp1_px, tp2_px, sl_px):
    emoji = "🟩" if side == "LONG" else "🟥"
    send_alert("⚔️ 深币已市价抢跑 (偶数动态复利)", {
        "防守方向": f"{emoji} {side}",
        "实盘均价": f"`{price:.2f}`",
        "核算头寸": f"`{qty}` 张 (已对半切割)",
        "TP1 止盈 (7美金价差)": f"`{tp1_px:.2f}`",
        "TP2 止盈 (15美金价差)": f"`{tp2_px:.2f}`",
        "全仓止损 (20美金价差)": f"`{sl_px:.2f}`"
    })

def report_intervention(qty, entry_px, new_tp, new_sl):
    send_alert("⚠️ 察觉深币仓位异动：哨兵已自愈重装", {
        "触发原因": "检测到人工干预加减仓，或前置止盈已落袋",
        "残余头寸": f"`{qty}` 张",
        "最新均价": f"`{entry_px:.2f}`",
        "动作": "旧网已全撤，按新均价重新布设专属防线",
        "统一限价止盈位 (15价差)": f"`{new_tp:.2f}`",
        "条件止损防线位 (20价差)": f"`{new_sl:.2f}`"
    })

def report_force_align(real_side, expected_side):
    send_alert("🚨 严重违纪事件：触发铁血镇压", {
        "实盘方向": real_side,
        "TV应有方向": expected_side,
        "处理结果": "已强行平掉与策略相悖的持仓，坚决对齐大盘信号！"
    })

def report_deepcoin_clear(reason):
    send_alert("🧹 战阵彻底清盘", {"触发机制": reason, "当前状态": "挂单全撤，仓位全平，资金回炉待命"})

def report_system_alert(title, detail):
    send_alert(f"⚠️ 系统告警: {title}", {"详情": detail, "状态": "请管理员介入检查"})
