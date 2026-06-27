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
def _deep_purple(text): return f'<font color="#4B0082">{text}</font>'
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
    return f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={urllib.parse.quote_plus(base64.b64encode(hmac_code))}"

def send_alert(title, data_dict, header_color="#4B0082"):
    signed_url = _get_signed_url()
    if not signed_url: return
    body_text = "\n".join([f"- **{k}**: {v}" for k, v in data_dict.items()])
    markdown_text = f"### <font color=\"{header_color}\">{title}</font>\n> **⏱ 军区时间**：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  \n> **📍 阵地标识**：[ 中海资本 · 深币四档位雷达版 V11.1 ]\n\n---\n{body_text}\n\n---\n*🖨️ Quant AI · 深币紫金高频印钞机*"
    try: requests.post(signed_url, json={"msgtype": "markdown", "markdown": {"title": title, "text": markdown_text}}, timeout=6)
    except Exception as e: logger.error(f"钉钉发送失败: {e}")

def get_regime_name(regime_code):
    if regime_code == 1: return _gray("🧊 [1档] 极弱波段")
    if regime_code == 2: return _blue("🚶 [2档] 弱势推升")
    if regime_code == 3: return _orange("🏃 [3档] 中势单边")
    if regime_code == 4: return _green("🚀 [4档] 强势主升")
    return "未知状态"

def report_deepcoin_open(side, regime, atr, entry_price, tv_price, qty, tp_pxs):
    side_str = _green("🟩 开多 (LONG)") if side == "LONG" else _red("🟥 开空 (SHORT)")
    slip_txt = f"{(entry_price - tv_price if side == 'LONG' else tv_price - entry_price):+.2f} 刀" if tv_price > 0 else "未知"

    # 构建三档止盈显示
    tp_str = ""
    for i, tp in enumerate(tp_pxs):
        if tp > 0:
            prefix = "" if tp_str == "" else "\n  ➔ "
            tp_str += f"{prefix}TP{i+1} `{tp:.2f}`"

    send_alert("🔶 深币战神出击", {
        "🎛️ 持仓方向": side_str,
        "📊 市场强度": get_regime_name(regime),
        "💰 进场均价": f"**`{entry_price:.2f}`** USDT (滑点: **{slip_txt}**)",
        "📦 开仓数量": f"`{qty}` 张（20x杠杆）",
        "🕸️ 分批止盈": _orange(tp_str),
        "📏 ATR参考": _gray(f"{atr:.2f}"),
        "📡 雷达状态": _blue("已启动保本止损追踪")
    }, "#4B0082")

def report_radar_move(side, new_sl):
    send_alert("📈 雷达追踪：保本止损上移", {
        "方向": _green("多头") if side == "LONG" else _red("空头"),
        "最新止损价": _green(f"**{new_sl:.2f}** USDT"),
        "说明": _purple("价格有利，已上移止损锁定利润")
    }, "#0070C0")

def report_manual_position_change(action_type, old_qty, new_qty, new_entry_price, fee_price):
    if action_type == "加仓":
        title = "📈 人工加仓同步"
        color = "#27AE60"
    else:
        title = "📉 人工减仓同步"
        color = "#E67E22"

    send_alert(title, {
        "操作类型": _blue(action_type),
        "原数量": f"`{old_qty}` 张",
        "当前数量": f"`{new_qty}` 张",
        "最新均价": f"**{new_entry_price:.2f}** USDT",
        "止盈单": f"已重新挂载对应数量止盈单"
    }, color)

def report_manual_full_close():
    send_alert("🛑 人工全平检测", {
        "操作类型": _red("人工全平"),
        "雷达动作": "已停止自动监控",
        "说明": _purple("检测到人工全平，系统已退出自动管理")
    }, "#C0392B")

def report_force_align(real_side, expected_side):
    send_alert("🚨 方向异常强制对齐", {
        "实盘方向": f"`{real_side}`",
        "TV期望方向": f"`{expected_side}`",
        "处理结果": "**已强制全平对齐**"
    }, "#FF0000")

def report_deepcoin_clear(reason, status_msg):
    if "人工全平" in reason:
        title, color = "🛑 人工全平", "#C0392B"
    elif "方向异常" in reason:
        title, color = "🚨 方向异常清仓", "#FF3333"
    elif "保护性" in reason:
        title, color = "🛡️ 保护性清仓", "#FF9900"
    else:
        title, color = "🧹 策略清仓", "#7F8C8D"

    send_alert(title, {
        "清场原因": reason,
        "核查结果": f"**{status_msg}**"
    }, color)

def report_system_alert(title, detail):
    send_alert(f"⚠️ 系统告警：{title}", {
        "告警级别": _red("最高级别"),
        "详情": _red(f"**{detail}**")
    }, "#FF0000")
