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

# ==================== 紫色美观度渲染 ====================
def _purple(text): return f'<font color="#9B59B6">{text}</font>'
def _green(text): return f'<font color="#27AE60">{text}</font>'
def _red(text): return f'<font color="#E74C3C">{text}</font>'
def _blue(text): return f'<font color="#3498DB">{text}</font>'
def _orange(text): return f'<font color="#E67E22">{text}</font>'
def _gray(text): return f'<font color="#7F8C8D">{text}</font>'
def _bold(text): return f'**{text}**'

def _get_signed_url():
    if not DINGTALK_WEBHOOK:
        return ""
    if not DINGTALK_SECRET:
        return DINGTALK_WEBHOOK
    ts = str(round(time.time() * 1000))
    hmac_code = hmac.new(DINGTALK_SECRET.encode('utf-8'), f'{ts}\n{DINGTALK_SECRET}'.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={sign}"

def send_alert(title, data_dict, header_color="#9B59B6"):
    signed_url = _get_signed_url()
    if not signed_url:
        return

    text_lines = []
    for k, v in data_dict.items():
        text_lines.append(f"- **{k}** : {v}")

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

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": markdown_text
        }
    }
    try:
        requests.post(signed_url, json=payload, timeout=6)
    except Exception as e:
        logger.error(f"钉钉发送失败: {e}")

# ==================== 通用函数 ====================
def get_regime_name(regime_code):
    if regime_code == 1: return _gray("🧊 极弱震荡")
    if regime_code == 2: return _blue("🚶 弱势波段")
    if regime_code == 3: return _orange("🏃 中势推升")
    if regime_code == 4: return _green("🚀 强势单边")
    return "未知状态"

# ==================== 开仓播报 ====================
def report_supervisor_open(side, price, qty, regime, fee_cover_price):
    side_str = _green("🟩 做多") if side == "LONG" else _red("🟥 做空")
    data = {
        "交易方向": side_str,
        "入场价格": f"`{price:.2f}` USDT",
        "下单数量": f"`{qty}`",
        "市场环境": get_regime_name(regime),
        "第一重保本目标": _purple(f"**{fee_cover_price:.2f}** (覆盖手续费)")
    }
    send_alert("🟣 深币开仓成功", data, header_color="#9B59B6")

# ==================== 新增：第一重保本达成 ====================
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

# ==================== 新增：切换到 TV tp1 ====================
def report_switch_to_tp1(side, remaining_qty, tv_tp1):
    side_str = _green("多") if side == "LONG" else _red("空")
    data = {
        "方向": side_str,
        "剩余仓位": f"`{remaining_qty}`",
        "切换止盈至": _orange(f"**TV tp1 = {tv_tp1:.2f}**"),
        "策略": _purple("雷达持续工作 · 目标吃到tp1全平")
    }
    send_alert("🎯 第二重启动：剩余仓位挂TV tp1", data, header_color="#9B59B6")

# ==================== 新增：雷达移动止损 ====================
def report_radar_move(side, new_sl, reason="锁利润"):
    side_str = _green("多") if side == "LONG" else _red("空")
    data = {
        "方向": side_str,
        "新止损位": _green(f"**{new_sl:.2f}**"),
        "触发原因": reason
    }
    send_alert("📈 雷达上移止损", data, header_color="#8E44AD")

# ==================== 清仓播报 ====================
def report_supervisor_close(reason):
    if "TP3" in reason or "tp1" in reason.lower():
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

    data = {
        "触发原因": color_reason
    }
    send_alert(title, data, header_color=header_color)

# ==================== 系统告警 ====================
def report_system_alert(title, detail):
    data = {
        "告警内容": _red(f"**{detail}**")
    }
    send_alert(f"⚠️ 系统告警：{title}", data, header_color="#E74C3C")
