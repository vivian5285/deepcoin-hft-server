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
    if not DINGTALK_WEBHOOK:
        return ""
    if not DINGTALK_SECRET:
        return DINGTALK_WEBHOOK
    ts = str(round(time.time() * 1000))
    hmac_code = hmac.new(DINGTALK_SECRET.encode('utf-8'), f'{ts}\n{DINGTALK_SECRET}'.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={sign}"

def send_alert(title, data_dict, header_color="#000000"):
    signed_url = _get_signed_url()
    if not signed_url:
        return

    text_lines = [f"- **{k}**: {v}" for k, v in data_dict.items()]
    body_text = "\n".join(text_lines)
    now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    markdown_text = f"""### <font color="{header_color}">{title}</font>
> **⏱ 时间**：`{now_time}`
> **策略**：深币智能保本刷单版

---
{body_text}

---
*🤖 战神刷单引擎 · 保本优先 + TP1 加成*"""

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

def get_regime_name(regime_code):
    if regime_code == 1: return "🧊 极弱震荡"
    if regime_code == 2: return "🚶 弱势波段"
    if regime_code == 3: return "🏃 中势推升"
    if regime_code == 4: return "🚀 强势单边"
    return "未知状态"

# ==================== 深币智能保本开仓战报 ====================
def report_deepcoin_open(side, entry_price, qty, fee_cover_price, tv_tp1, atr, old_qty=0, tv_price=0, regime=3):
    emoji = "🟩" if side == "LONG" else "🟥"
    clean_msg = "✅ 纯净新开" if old_qty == 0 else f"🚨 反转（强平旧仓 {old_qty} 张）"

    if tv_price > 0:
        slip = entry_price - tv_price if side == "LONG" else tv_price - entry_price
        slip_txt = f"{slip:+.2f}"
    else:
        slip_txt = "未知"

    # 保本价与 TP1 对比展示
    if tv_tp1 > 0:
        tp_compare = f"保本价 `{fee_cover_price:.2f}` | 策略TP1 `{tv_tp1:.2f}`"
    else:
        tp_compare = f"保本价 `{fee_cover_price:.2f}`（未收到TV TP1）"

    send_alert("🖨️ 深币智能保本开仓", {
        "方向": f"**{emoji} {side}**",
        "档位": get_regime_name(regime),
        "实盘均价": f"**`{entry_price:.2f}`** (滑点 {slip_txt})",
        "仓位": f"`{qty}` 张（100% 全仓）",
        "状态": clean_msg,
        "退出策略": tp_compare,
        "波动参考": f"ATR = {atr:.2f}"
    }, header_color="#FF6600")

# ==================== 深币清盘报告 ====================
def report_deepcoin_clear(reason):
    if "刷单完成" in reason or "手续费" in reason:
        title = "💰 刷单完成 · 手续费已锁定"
        header_color = "#00B050"
        status = "✅ 手续费已覆盖，资金安全回笼"
    else:
        title = "🧹 深币刷单清盘"
        header_color = "#808080"
        status = "仓位已平，等待下一次刷单机会"

    send_alert(title, {
        "触发原因": reason,
        "当前状态": status
    }, header_color=header_color)

# ==================== 强制对齐报告 ====================
def report_force_align(real_side, expected_side):
    send_alert("🚨 严重违纪 · 方向强行对齐", {
        "实盘方向": f"`{real_side}`",
        "TV 指令方向": f"`{expected_side}`",
        "处理结果": "**已执行强制市价平仓，对齐信号源**"
    }, header_color="#FF0000")

# ==================== 系统风险告警 ====================
def report_system_alert(title, detail):
    send_alert(f"⚠️ 系统告警: {title}", {
        "详情": detail,
        "建议": "请立即检查 Deepcoin 账户状态"
    }, header_color="#FF0000")

# ==================== 雷达干预报告 ====================
def report_intervention(qty, entry_px, new_level, action_msg):
    send_alert("⚡ 雷达动态响应", {
        "当前仓位": f"`{qty}` 张",
        "入场价格": f"`{entry_px:.2f}`",
        "响应动作": action_msg,
        "最新保本线": f"`{new_level:.2f}`"
    }, header_color="#0070C0")
