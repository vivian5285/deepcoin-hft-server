# 替换深币服务器 dingtalk.py 中的 report_deepcoin_open 函数
def report_deepcoin_open(side, price, qty, tp_pxs, sl_px, atr):
    emoji = "🟩" if side == "LONG" else "🟥"
    send_alert("⚔️ 深币现价吃单 (三段ATR动态复利)", {
        "防守方向": f"{emoji} {side}",
        "实盘均价": f"`{price:.2f}`",
        "动态头寸": f"`{qty}` 张 (30/30/40切割)",
        "真实波动(ATR)": f"`{atr:.2f}` 美金",
        "自适应止盈 (1.28/2.5/3.6X)": f"`{tp_pxs[0]}` | `{tp_pxs[1]}` | `{tp_pxs[2]}`",
        "初始止损 (0.92X)": f"`{sl_px:.2f}`"
    })
