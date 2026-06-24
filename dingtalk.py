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

# ==================== Markdown 颜色渲染辅具 ====================
def _green(text): return f'<font color="#00B050">{text}</font>'
def _red(text): return f'<font color="#FF3333">{text}</font>'
def _blue(text): return f'<font color="#0070C0">{text}</font>'
def _orange(text): return f'<font color="#FF9900">{text}</font>'
def _gray(text): return f'<font color="#808080">{text}</font>'
def _purple(text): return f'<font color="#800080">{text}</font>'

def _get_signed_url():
    if not DINGTALK_WEBHOOK:
        return ""
    if not DINGTALK_SECRET:
        return DINGTALK_WEBHOOK
    ts = str(round(time.time() * 1000))
    hmac_code = hmac.new(DINGTALK_SECRET.encode('utf-8'), f'{ts}\n{DINGTALK_SECRET}'.encode('utf-8'), hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{DINGTALK_WEBHOOK}&timestamp={ts}&sign={sign}"

def send_alert(title, data_dict, header_color="#4B0082"):
    signed_url = _get_signed_url()
    if not signed_url:
        return

    # 构建高颜值 Markdown 文本
    text_lines = []
    for k, v in data_dict.items():
        text_lines.append(f"- **{k}** : {v}")
    
    body_text = "\n".join(text_lines)
    now_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 深币专属 Header
    markdown_text = f"""### <font color="{header_color}">{title}</font>
> **⏱ 军区时间**：`{now_time}`
> **📍 策略节点**：[ 中海资本 · 深币高频双擎 v7.0 ]

---
{body_text}

---
*🖨️ Quant AI 返佣印钞机持仓播报*
"""

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title, # 钉钉通知栏显示的标题
            "text": markdown_text
        }
    }
    try:
        requests.post(signed_url, json=payload, timeout=6)
    except Exception as e:
        logger.error(f"钉钉发送失败: {e}")

def get_regime_name(regime_code):
    if regime_code == 1: return _gray("🧊 [1档] 极弱震荡 (保守刷单)")
    if regime_code == 2: return _blue("🚶 [2档] 弱势波段 (稳健刷单)")
    if regime_code == 3: return _orange("🏃 [3档] 中势推升 (均衡刷单)")
    if regime_code == 4: return _green("🚀 [4档] 强势单边 (吃满利润)")
    return "未知状态"

# ==================== 开仓战报 (深币专属视觉) ====================
def report_deepcoin_open(side, entry_price, qty, fee_cover_price, tv_tp1, atr, old_qty=0, tv_price=0, regime=3):
    side_str = _green("🟩 现价做多 (LONG)") if side == "LONG" else _red("🟥 现价做空 (SHORT)")
    clean_msg = _green("✅ 纯净新开") if old_qty == 0 else _orange(f"🚨 反转对冲 (强平旧仓 {old_qty} 张)")
    
    # 滑点计算
    if tv_price > 0:
        slip = entry_price - tv_price if side == "LONG" else tv_price - entry_price
        slip_txt = f"{slip:+.2f} 刀"
    else:
        slip_txt = "未知"

    # 🚀 展示核心：双擎矩阵比对
    if tv_tp1 > 0:
        engine_str = f"🛡️ 保本线 `{fee_cover_price:.2f}` ➔ 🎯 利润线 `{tv_tp1:.2f}`"
    else:
        engine_str = f"🛡️ 保本线 `{fee_cover_price:.2f}` (未收到TV理论TP1)"

    data = {
        "🎛️ 交易方向": side_str,
        "📊 市场环境": get_regime_name(regime),
        "💰 进场均价": f"**{entry_price:.2f}** USDT (滑点: **{slip_txt}**)",
        "📦 部署数量": f"**{qty}** 张 (100% 满仓出击)",
        "⚙️ 双擎矩阵": _purple(engine_str),
        "状态反馈": clean_msg,
        "📏 波动参考": _gray(f"ATR = {atr:.4f}")
    }
    # 使用魅影紫作为深币入场的主色调
    send_alert("🖨️ 深币双擎：高频刷单阵地建立", data, header_color="#4B0082")

# ==================== 动态保本 / 干预报告 ====================
def report_intervention(qty, entry_px, new_level, action_msg):
    data = {
        "🛡️ 战术动作": _blue(action_msg),
        "📦 阵地头寸": f"`{qty}` 张",
        "💰 入场成本": f"`{entry_px:.2f}` USDT",
        "🔒 最新保本线": _purple(f"**{new_level:.2f}** USDT (已重置网格)")
    }
    send_alert("💎 捷报：追踪雷达锁定返佣", data, header_color="#800080")

# ==================== 强制对齐报告 (极度危险警告) ====================
def report_force_align(real_side, expected_side):
    data = {
        "🚨 异常状况": _red("**深币实盘仓位与策略发生精神分裂！**"),
        "🕵️ 实盘方向": _red(real_side),
        "🧠 策略指令": _blue(expected_side),
        "⚡ 仲裁结果": _red("**拒绝妥协！已执行物理斩仓，强行对齐信号源！**")
    }
    send_alert("🚨 严重警告：方向强行物理对齐", data, header_color="#FF0000")

# ==================== 清仓战报（深币专属语境） ====================
def report_deepcoin_clear(reason):
    if "完成" in reason or "止盈" in reason:
        title = "💸 返佣到手：深币双擎完美离场"
        header_color = "#00B050"
        color_reason = _green(f"**{reason}**")
        status = _green("手续费已全额覆盖，毛利落袋为安。")
    elif "保护" in reason or "反转" in reason or "异常" in reason:
        title = "🛡️ 战术撤退：触发安全保护机制"
        header_color = "#FF9900"
        color_reason = _orange(f"**{reason}**")
        status = _gray("防守止损已触发，底层挂单撤销干净。")
    elif "人工" in reason or "违规" in reason:
        title = "🛑 系统截断：拒绝人工干预"
        header_color = "#FF3333"
        color_reason = _red(f"**{reason}**")
        status = _red("系统已剥夺人工接管权限，执行强制物理清盘！")
    else:
        title = "🧹 阵地清场：仓位已归零"
        header_color = "#808080"
        color_reason = _gray(f"**{reason}**")
        status = "挂单已撤销，底层账本确认归零。"

    data = {
        "📋 触发归因": color_reason,
        "✅ 账本状态": status
    }
    send_alert(title, data, header_color=header_color)

# ==================== 系统底层风险告警 ====================
def report_system_alert(title, detail):
    data = {
        "⚠️ 告警级别": _red("最高级别 (CRITICAL)"),
        "📝 核心详情": _red(f"**{detail}**"),
        "🛠️ 建议动作": "请立即登录 Deepcoin 服务器或 APP 复核状态！"
    }
    send_alert(f"⚠️ 系统熔断：{title}", data, header_color="#FF0000")
