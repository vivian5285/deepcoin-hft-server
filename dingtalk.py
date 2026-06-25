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

# ==================== 深币专属紫色美学 ====================
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
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={sign}"

def send_alert(title, data_dict, header_color="#4B0082"):
    signed_url = _get_signed_url()
    if not signed_url: return

    text_lines = [f"- **{k}**: {v}" for k, v in data_dict.items()]
    body_text = "\n".join(text_lines)
    now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    markdown_text = f"""### <font color="{header_color}">{title}</font>
> **⏱ 军区时间**：`{now_time}`  
> **📍 阵地标识**：[ 中海资本 · 深币双擎雷达 v7.0 ]

---
{body_text}

---
*🖨️ Quant AI · 深币紫金高频印钞机*
"""
    payload = {"msgtype": "markdown", "markdown": {"title": title, "text": markdown_text}}
    try: requests.post(signed_url, json=payload, timeout=6)
    except Exception as e: logger.error(f"钉钉发送失败: {e}")

# ==================== 动作战报 ====================

def report_deepcoin_open(side, entry_price, tv_price, qty, fee_cover_price, tv_tp1):
    side_str = _green("🟩 现价做多 (LONG)") if side == "LONG" else _red("🟥 现价做空 (SHORT)")
    
    # 🎯 精准滑点计算
    if tv_price > 0:
        slip = entry_price - tv_price if side == "LONG" else tv_price - entry_price
        slip_txt = f"{slip:+.2f} 刀"
    else:
        slip_txt = "未知 (TV未传价)"

    data = {
        "🎛️ 潜伏方向": side_str,
        "💰 进场均价": f"**`{entry_price:.2f}`** USDT (滑点: **{slip_txt}**)",
        "📦 阵地头寸": f"`{qty}` 张 (双向对冲体系)",
        "⚙️ 双擎排单": f"保手续费: **`{fee_cover_price:.2f}`** | 终点 TV_TP1: **`{tv_tp1:.2f}`**",
        "📡 初始防守": _deep_purple("🟢 实盘核查：初始硬止损已隐身，限价双擎已铺设！")
    }
    send_alert("🖨️ 战神入局：深币双擎建仓完毕", data, header_color="#4B0082")

def report_fee_cover_reached(side, entry_price, fee_cover_price, remaining_qty):
    side_str = _green("多") if side == "LONG" else _red("空")
    data = {
        "触发方向": side_str,
        "保本已触发": _green(f"**{fee_cover_price:.2f}** USDT (手续费已安全覆盖)"),
        "剩余冲锋头寸": f"`{remaining_qty}` 张",
        "实盘核查": _purple("✅ 确认突破，雷达物理保本止损已挂至成本价！")
    }
    send_alert("🛡️ 第一重达成：雷达激活护甲", data, header_color="#8E44AD")

def report_radar_move(side, new_sl):
    side_str = _green("多头") if side == "LONG" else _red("空头")
    data = {
        "追踪方向": side_str,
        "最新止损位": _green(f"**{new_sl:.2f}** USDT"),
        "实盘核查": _purple("✅ 交易所条件单已成功上移锁润！")
    }
    send_alert("📈 雷达捷报：锁润防线推升", data, header_color="#8E44AD")

def report_deepcoin_clear(reason):
    if "TP3" in reason or "归零" in reason or "自然止盈" in reason:
        title = "🏆 完美清场：利润与返佣双收"
        header_color = "#27AE60"
        color_reason = _green(f"**{reason}**")
    elif "保护" in reason or "防守" in reason:
        title = "🛡️ 战术撤退：保本防守触发"
        header_color = "#E67E22"
        color_reason = _orange(f"**{reason}**")
    elif "人工" in reason or "违规" in reason:
        title = "🛑 铁血截断：人工违规干预"
        header_color = "#FF3333"
        color_reason = _red(f"**{reason}**")
    else:
        title = "🧹 深币对冲阵地全平"
        header_color = "#7F8C8D"
        color_reason = _gray(f"**{reason}**")

    data = {
        "触发原因": color_reason,
        "实盘核查": "**✅ API 确认：反向对冲完成，所有挂单已撤销，双向仓位物理归零！**"
    }
    send_alert(title, data, header_color=header_color)

def report_force_align(real_side, expected_side):
    send_alert("🚨 严重违纪 · 强行物理对齐", {
        "实盘方向": f"`{real_side}`",
        "TV期望方向": f"`{expected_side}`",
        "处理结果": "**已执行强制反向对冲市价平仓，强行对齐源头！**"
    }, header_color="#FF0000")

def report_system_alert(title, detail):
    send_alert(f"⚠️ 系统告警：{title}", {
        "告警级别": _red("最高级别 (CRITICAL)"),
        "详情": _red(f"**{detail}**")
    }, header_color="#FF0000")
