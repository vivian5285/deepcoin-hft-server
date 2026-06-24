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

def _green(text): return f'<font color="#00B050">{text}</font>'
def _red(text): return f'<font color="#FF3333">{text}</font>'
def _blue(text): return f'<font color="#0070C0">{text}</font>'
def _orange(text): return f'<font color="#FF9900">{text}</font>'
def _gray(text): return f'<font color="#808080">{text}</font>'

def _get_signed_url():
    if not DINGTALK_WEBHOOK: return ""
    if not DINGTALK_SECRET: return DINGTALK_WEBHOOK
    ts = str(round(time.time() * 1000))
    hmac_code = hmac.new(DINGTALK_SECRET.encode('utf-8'), f'{ts}\n{DINGTALK_SECRET}'.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={sign}"

def send_alert(title, data_dict, header_color="#00B050"):
    signed_url = _get_signed_url()
    if not signed_url: return
    text_lines = [f"- **{k}** : {v}" for k, v in data_dict.items()]
    body_text = "\n".join(text_lines)
    now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    markdown_text = f"""### <font color="{header_color}">{title}</font>
> **⏱ 时间**：`{now_time}`
> **📍 节点**：深币高频刷单系统（两道平仓 + 雷达版）

---
{body_text}

---
*🤖 Deepcoin Quant Engine*
"""
    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": markdown_text}}
    try: requests.post(signed_url, json=payload, timeout=6)
    except Exception as e: logger.error(f"钉钉发送失败: {e}")

# ==================== 新增播报函数 ====================

def report_fee_cover_reached(side, entry_price, fee_cover_price, remaining_qty):
    data = {
        "方向": _blue(side),
        "入场价": f"`{entry_price:.2f}`",
        "保本目标价": _green(f"**{fee_cover_price:.2f}**"),
        "剩余仓位": f"`{remaining_qty}`",
        "动作": "雷达已启动 + 止损移至保本位"
    }
    send_alert("🛡️ 第一重达成：保本雷达启动", data, header_color="#00B050")

def report_switch_to_tp1(side, remaining_qty, tv_tp1):
    data = {
        "方向": _blue(side),
        "剩余仓位": f"`{remaining_qty}`",
        "切换止盈到": _orange(f"**TV tp1 = {tv_tp1:.2f}**"),
        "状态": "雷达持续工作，目标吃到tp1全平"
    }
    send_alert("🎯 切换第二重：剩余仓位挂TV tp1", data, header_color="#FF9900")

def report_radar_move(side, new_sl, reason="锁利润"):
    data = {
        "方向": _blue(side),
        "新止损位": _green(f"**{new_sl:.2f}**"),
        "触发原因": reason
    }
    send_alert("🚀 雷达上移止损", data, header_color="#0070C0")
