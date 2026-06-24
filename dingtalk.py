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

def _purple(text): return f'<font color="#9B59B6">{text}</font>'
def _green(text): return f'<font color="#27AE60">{text}</font>'
def _red(text): return f'<font color="#E74C3C">{text}</font>'
def _blue(text): return f'<font color="#3498DB">{text}</font>'
def _orange(text): return f'<font color="#E67E22">{text}</font>'
def _gray(text): return f'<font color="#7F8C8D">{text}</font>'

def _get_signed_url():
    if not DINGTALK_WEBHOOK: return ""
    if not DINGTALK_SECRET: return DINGTALK_WEBHOOK
    ts = str(round(time.time() * 1000))
    hmac_code = hmac.new(DINGTALK_SECRET.encode('utf-8'), f'{ts}\n{DINGTALK_SECRET}'.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={sign}"

def send_alert(title, data_dict, header_color="#9B59B6"):
    signed_url = _get_signed_url()
    if not signed_url: return
    text_lines = [f"- **{k}** : {v}" for k, v in data_dict.items()]
    body_text = "\n".join(text_lines)
    now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    markdown_text = f"""### <font color="{header_color}">{title}</font>
> **⏱ 时间**：`{now_time}`
> **📍 系统**：深币高频刷单（两道平仓 + 雷达保本版）

---
{body_text}

---
*🤖 Deepcoin Engine · 紫色美学*
"""
    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": markdown_text}}
    try: requests.post(signed_url, json=payload, timeout=6)
    except Exception as e: logger.error(f"钉钉发送失败: {e}")

def report_fee_cover_reached(side, entry_price, fee_cover_price, remaining_qty):
    side_str = _green("多") if side == "LONG" else _red("空")
    data = {
        "方向": side_str,
        "入场价": f"`{entry_price:.2f}`",
        "保本目标价": _green(f"**{fee_cover_price:.2f}**"),
        "剩余仓位": f"`{remaining_qty}`",
        "状态": _purple("🚀 雷达已启动 · 止损移至保本位")
    }
    send_alert("🛡️ 第一重达成：保本雷达启动", data, header_color="#8E44AD")

def report_switch_to_tp1(side, remaining_qty, tv_tp1):
    side_str = _green("多") if side == "LONG" else _red("空")
    data = {
        "方向": side_str,
        "剩余仓位": f"`{remaining_qty}`",
        "切换止盈至": _orange(f"**TV tp1 = {tv_tp1:.2f}**"),
        "策略": _purple("雷达持续工作 · 目标吃到tp1全平")
    }
    send_alert("🎯 第二重启动：剩余仓位挂TV tp1", data, header_color="#9B59B6")

def report_radar_move(side, new_sl, reason="锁利润"):
    side_str = _green("多") if side == "LONG" else _red("空")
    data = {
        "方向": side_str,
        "新止损位": _green(f"**{new_sl:.2f}**"),
        "触发原因": reason
    }
    send_alert("📈 雷达上移止损", data, header_color="#8E44AD")

def report_supervisor_close(reason):
    if "tp1" in reason.lower() or "TP3" in reason:
        title = "🏆 第二重达成：吃到tp1全平"
        header_color = "#27AE60"
        color_reason = _green(f"**{reason}**")
    elif "保护" in reason:
        title = "🛡️ 保护性全平"
        header_color = "#E67E22"
        color_reason = _orange(f"**{reason}**")
    else:
        title = "🧹 仓位已清零"
        header_color = "#7F8C8D"
        color_reason = _gray(f"**{reason}**")
    data = {"触发原因": color_reason}
    send_alert(title, data, header_color=header_color)
