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
    # 🚀 在这里把名字改成了霸气的 V9.3 战前终极防线版！
    markdown_text = f"### <font color=\"{header_color}\">{title}</font>\n> **⏱ 军区时间**：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  \n> **📍 阵地标识**：[ 中海资本 · 深币双擎雷达 V9.3 终极防线版 ]\n\n---\n{body_text}\n\n---\n*🖨️ Quant AI · 深币紫金高频印钞机*"
    try: requests.post(signed_url, json={"msgtype": "markdown", "markdown": {"title": title, "text": markdown_text}}, timeout=6)
    except Exception as e: logger.error(f"钉钉发送失败: {e}")

def get_regime_name(regime_code):
    if regime_code == 1: return _gray("🧊 [1档] 极弱波段 (15% 防守仓)")
    if regime_code == 2: return _blue("🚶 [2档] 弱势推升 (25% 标准仓)")
    if regime_code == 3: return _orange("🏃 [3档] 中势单边 (35% 进攻仓)")
    if regime_code == 4: return _green("🚀 [4档] 强势主升 (50% 满血仓)")
    return "未知状态"

def report_deepcoin_open(side, regime, atr, entry_price, tv_price, qty, fee_qty, fee_price, tp1_qty, local_tp1, tv_tp1):
    side_str = _green("🟩 现价做多 (LONG)") if side == "LONG" else _red("🟥 现价做空 (SHORT)")
    slip_txt = f"{(entry_price - tv_price if side == 'LONG' else tv_price - entry_price):+.2f} 刀" if tv_price > 0 else "未知"
    
    send_alert("🖨️ 战神入局：深币双擎建仓完毕", {
        "🎛️ 潜伏方向": side_str,
        "📊 市场强度": get_regime_name(regime),
        "💰 进场均价": f"**`{entry_price:.2f}`** USDT (滑点: **{slip_txt}**)",
        "📦 动态头寸": f"`{qty}` 张 (20x 杠杆 | 双向对冲)",
        "📏 波动参考": _gray(f"ATR = {atr:.4f}"),
        "⚙️ 双擎排单": f"保本重兵: `{fee_qty}`张@**`{fee_price:.2f}`**\n\n  ➔ 冲锋残兵: `{tp1_qty}`张@**`{local_tp1:.2f}`** (TV:`{tv_tp1:.2f}`)",
        "📡 初始防守": _deep_purple("🟢 实盘核查：初始硬止损已隐身，双限价已强行铺设！")
    }, "#4B0082")

def report_fee_cover_reached(side, entry_price, fee_cover_price, remaining_qty):
    send_alert("🛡️ 第一重达成：雷达激活护甲", {
        "触发方向": _green("多") if side == "LONG" else _red("空"),
        "保本已触发": _green(f"**{fee_cover_price:.2f}** USDT (手续费与微利已安全覆盖)"),
        "剩余冲锋头寸": f"`{remaining_qty}` 张",
        "实盘核查": _purple("✅ 确认突破，雷达物理保本止损已挂至成本价！")
    }, "#8E44AD")

def report_radar_move(side, new_sl):
    send_alert("📈 雷达捷报：锁润防线推升", {
        "追踪方向": _green("多头") if side == "LONG" else _red("空头"),
        "最新止损位": _green(f"**{new_sl:.2f}** USDT"),
        "实盘核查": _purple("✅ 交易所条件单已成功上移锁润！")
    }, "#8E44AD")

def report_deepcoin_clear(reason, status_msg):
    if "TP3" in reason or "归零" in reason: title, color, r_color = "🏆 完美清场：利润与返佣双收", "#27AE60", _green(f"**{reason}**")
    elif "保护" in reason: title, color, r_color = "🛡️ 战术撤退：保本防守触发", "#E67E22", _orange(f"**{reason}**")
    elif "人工" in reason or "违规" in reason: title, color, r_color = "🛑 铁血截断：人工违规干预", "#FF3333", _red(f"**{reason}**")
    else: title, color, r_color = "🧹 深币对冲阵地全平", "#7F8C8D", _gray(f"**{reason}**")
    send_alert(title, {"触发原因": r_color, "核查结果": f"**{status_msg}**"}, color)

def report_force_align(real_side, expected_side):
    send_alert("🚨 严重违纪 · 强行物理对齐", {"实盘方向": f"`{real_side}`", "TV期望方向": f"`{expected_side}`", "处理结果": "**已强制反向对冲清仓对齐源头！**"}, "#FF0000")

def report_system_alert(title, detail):
    send_alert(f"⚠️ 系统告警：{title}", {"告警级别": _red("最高级别 (CRITICAL)"), "详情": _red(f"**{detail}**")}, "#FF0000")
