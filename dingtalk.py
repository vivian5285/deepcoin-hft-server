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
    # 🚀 阵地标识全面升格为 V9.9 黄金甜点微利版
    markdown_text = f"### <font color=\"{header_color}\">{title}</font>\n> **⏱ 军区时间**：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  \n> **📍 阵地标识**：[ 中海资本 · 深币双擎雷达 V9.9 黄金甜点微利版 ]\n\n---\n{body_text}\n\n---\n*🖨️ Quant AI · 深币紫金高频印钞机*"
    try: requests.post(signed_url, json={"msgtype": "markdown", "markdown": {"title": title, "text": markdown_text}}, timeout=6)
    except Exception as e: logger.error(f"钉钉发送失败: {e}")

def get_regime_name(regime_code):
    if regime_code == 1: return _gray("🧊 [1档] 极弱波段 (15% 防守开仓)")
    if regime_code == 2: return _blue("🚶 [2档] 弱势推升 (25% 标准开仓)")
    if regime_code == 3: return _orange("🏃 [3档] 中势单边 (35% 进攻开仓)")
    if regime_code == 4: return _green("🚀 [4档] 强势主升 (50% 满血开仓)")
    return "未知状态"

def report_deepcoin_open(side, regime, atr, entry_price, tv_price, qty, fee_qty, fee_price, tp1_qty=0, local_tp1=0, tv_tp1=0):
    side_str = _green("🟩 双向开多 (LONG)") if side == "LONG" else _red("🟥 双向开空 (SHORT)")
    slip_txt = f"{(entry_price - tv_price if side == 'LONG' else tv_price - entry_price):+.2f} 刀" if tv_price > 0 else "未知"
    
    send_alert("🖨️ 战神入局：全仓极速微利狙击", {
        "🎛️ 持仓方向": side_str,
        "📊 市场强度": get_regime_name(regime),
        "💰 进场均价": f"**`{entry_price:.2f}`** USDT (滑点: **{slip_txt}**)",
        "📦 动态头寸": f"`{qty}` 张 (20x 杠杆 | 开平仓双向对冲)",
        "📐 波动参考": _gray(f"ATR = {atr:.4f}"),
        "⚙️ 狙击布防": f"**100% 仓位全量埋伏**: `{fee_qty}`张 @ 甜点目标价 **`{fee_price:.2f}`** (4.5U价差)",
        "📡 战术意图": _deep_purple("🟢 姐姐指令：无惧双边摩擦损耗，精准覆盖后铁血收割纯净利润！")
    }, "#4B0082")

def report_fee_cover_reached(side, entry_price, fee_cover_price, remaining_qty):
    send_alert("🛡️ 第一重达成：雷达激活原子护甲", {
        "触发方向": _green("多头微利突破") if side == "LONG" else _red("空头微利突破"),
        "保本价激活": _green(f"**{fee_cover_price:.2f}** USDT (4.5U 黄金甜点位已触及)"),
        "实盘盯盘仓位": f"`{remaining_qty}` 张",
        "安全核查": _purple("✅ 确认越过利润线！雷达硬为止损单已强制同步架设在开仓均价！")
    }, "#8E44AD")

def report_radar_move(side, new_sl):
    send_alert("📈 雷达捷报：锁润防线物理推升", {
        "追踪方向": _green("多头阵地") if side == "LONG" else _red("空头阵地"),
        "最新硬止损": _green(f"**{new_sl:.2f}** USDT"),
        "实盘核查": _purple("✅ 交易所原生条件单已成功重置上移，死锁纯利底线！")
    }, "#8E44AD")

def report_deepcoin_clear(reason, status_msg):
    if "极速微利" in reason or "完全吃掉" in reason or "落袋" in reason: 
        title, color, r_color = "🏆 极速收网：4.5U 黄金甜点完美单向止盈", "#27AE60", _green(f"**{reason}**")
    elif "对齐" in reason or "换防" in reason:
        title, color, r_color = "🧹 阵地换防：双向对冲清仓空场", "#7F8C8D", _blue(f"**{reason}**")
    elif "人工" in reason or "违规" in reason: 
        title, color, r_color = "🛑 铁血截断：人工违规干预", "#FF3333", _red(f"**{reason}**")
    else: 
        title, color, r_color = "🛡️ 战术撤退：保本防守机制触发", "#E67E22", _orange(f"**{reason}**")
        
    send_alert(title, {"清场原因": r_color, "核查结果": f"**{status_msg}**"}, color)

def report_force_align(real_side, expected_side):
    send_alert("🚨 严重违纪 · 强行物理对齐", {"实盘方向": f"`{real_side}`", "TV期望方向": f"`{expected_side}`", "处理结果": "**检测到异动，已启动核武级全平一键抹杀！**"}, "#FF0000")

def report_system_alert(title, detail):
    send_alert(f"⚠️ 系统告警：{title}", {"告警级别": _red("最高级别 (CRITICAL)"), "详情": _red(f"**{detail}**")}, "#FF0000")
