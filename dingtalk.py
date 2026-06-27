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
    markdown_text = f"### <font color=\"{header_color}\">{title}</font>\n> **⏱ 军区时间**：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  \n> **📍 阵地标识**：[ 中海资本 · 深币高频微利刷佣版 V10.1 ]\n\n---\n{body_text}\n\n---\n*🖨️ Quant AI · 深币紫金高频印钞机*"
    try: requests.post(signed_url, json={"msgtype": "markdown", "markdown": {"title": title, "text": markdown_text}}, timeout=6)
    except Exception as e: logger.error(f"钉钉发送失败: {e}")

def get_regime_name(regime_code):
    if regime_code == 1: return _gray("🧊 [1档] 极弱波段")
    if regime_code == 2: return _blue("🚶 [2档] 弱势推升")
    if regime_code == 3: return _orange("🏃 [3档] 中势单边")
    if regime_code == 4: return _green("🚀 [4档] 强势主升")
    return "未知状态"

def report_deepcoin_open(side, regime, atr, entry_price, tv_price, qty, fee_qty, fee_price):
    side_str = _green("🟩 开多 (LONG)") if side == "LONG" else _red("🟥 开空 (SHORT)")
    slip_txt = f"{(entry_price - tv_price if side == 'LONG' else tv_price - entry_price):+.2f} 刀" if tv_price > 0 else "未知"
    
    send_alert("🖨️ 高频微利入局", {
        "🎛️ 持仓方向": side_str,
        "📊 市场强度": get_regime_name(regime),
        "💰 进场均价": f"**`{entry_price:.2f}`** USDT (滑点: **{slip_txt}**)",
        "📦 固定头寸": f"`{qty}` 张（固定使用余额 **30%** + **20x** 杠杆）",
        "📐 波动参考": _gray(f"ATR = {atr:.4f}"),
        "⚙️ 止盈布防": f"**4.5U 固定微利**：`{fee_qty}`张 @ **`{fee_price:.2f}`** USDT",
        "📡 战术意图": _deep_purple("高频微赚 + 手续费返佣为主，覆盖成本后快速离场")
    }, "#4B0082")

def report_fee_cover_reached(side, entry_price, fee_cover_price, remaining_qty):
    send_alert("🛡️ 微利目标达成", {
        "触发方向": _green("多头") if side == "LONG" else _red("空头"),
        "4.5U 微利价": _green(f"**{fee_cover_price:.2f}** USDT（已覆盖手续费 + 微利）"),
        "实盘仓位": f"`{remaining_qty}` 张",
        "策略备注": _purple("固定微利策略触发，准备快速收割")
    }, "#8E44AD")

def report_radar_move(side, new_sl):
    # 因为你以固定微利为主，追踪移动较少，这里保留但弱化提示
    send_alert("📈 止损微调", {
        "方向": _green("多头") if side == "LONG" else _red("空头"),
        "最新止损价": f"**{new_sl:.2f}** USDT",
        "说明": _gray("固定微利策略下的轻微止损保护调整")
    }, "#8E44AD")

def report_deepcoin_clear(reason, status_msg):
    if "极速微利" in reason or "落袋" in reason: 
        title, color = "🏆 微利收网成功", "#27AE60"
    elif "对齐" in reason or "换防" in reason:
        title, color = "🧹 阵地换防清仓", "#7F8C8D"
    elif "人工" in reason:
        title, color = "🛑 人工干预清仓", "#FF3333"
    else: 
        title, color = "🛡️ 策略清仓", "#E67E22"
        
    send_alert(title, {
        "清场原因": reason,
        "核查结果": f"**{status_msg}**"
    }, color)

def report_force_align(real_side, expected_side):
    send_alert("🚨 方向异常强制对齐", {
        "实盘方向": f"`{real_side}`",
        "TV期望方向": f"`{expected_side}`",
        "处理结果": "**已执行强制全平对齐**"
    }, "#FF0000")

def report_system_alert(title, detail):
    send_alert(f"⚠️ 系统告警：{title}", {
        "告警级别": _red("最高级别"),
        "详情": _red(f"**{detail}**")
    }, "#FF0000")
