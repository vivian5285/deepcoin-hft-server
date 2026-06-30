#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# position_supervisor_deepcoin.py — 与币安 VPS 逻辑完全对齐（深币张数/15x 适配）
import logging
import time
import threading
import os
import json
from logging.handlers import RotatingFileHandler
from deepcoin_client import deepcoin_client
import dingtalk

if not os.path.exists('logs'):
    os.makedirs('logs')
handler = RotatingFileHandler('logs/deepcoin_brain.log', maxBytes=5 * 1024 * 1024, backupCount=3)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] Brain: %(message)s',
    handlers=[handler, logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class PositionSupervisor:
    def __init__(self):
        self.symbol = "ETH-USDT-SWAP"
        self.monitoring = False
        self._lock = threading.Lock()

        # 与币安完全一致的四档矩阵：activation=启动雷达的 TP1 距离比例，trail_offset=ATR 追踪倍数
        self.regime_settings = {
            1: {"margin": 0.15, "ratios": [0.25, 0.35, 0.40], "activation": 0.40, "trail_offset": 0.40},
            2: {"margin": 0.25, "ratios": [0.20, 0.35, 0.45], "activation": 0.50, "trail_offset": 0.60},
            3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
            4: {"margin": 0.50, "ratios": [0.05, 0.20, 0.75], "activation": 0.70, "trail_offset": 1.30},
        }
        self.leverage = 15
        self.face_value = 0.1

        self.regime = 3
        self.current_atr = 30.0
        self.best_price = 0.0
        self.current_sl = 0.0
        self.tv_price = 0.0
        self.tv_tps = [0.0, 0.0, 0.0]

        self.initial_qty = 0
        self.watched_qty = 0
        self.watched_entry = 0.0
        self.current_side = None
        self.last_tv_side = None

        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [军师托管版] 已加载：双轨智慧雷达部署完毕！")

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    "last_tv_side": self.last_tv_side,
                    "current_side": self.current_side,
                    "watched_qty": self.watched_qty,
                    "watched_entry": self.watched_entry,
                    "current_sl": self.current_sl,
                    "monitoring": self.monitoring,
                    "regime": self.regime,
                    "current_atr": self.current_atr,
                    "tv_tps": self.tv_tps,
                    "best_price": self.best_price,
                }, f)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    def _get_active_position(self):
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                if int(p.get("pos", 0)) > 0:
                    return {
                        "size": int(p.get("pos")),
                        "entry_price": round(float(p.get("avgPx", p.get("price", 0))), 2),
                        "posSide": p.get("posSide", "long").lower(),
                    }
        return None

    def _verify_flat(self):
        pos = self._get_active_position()
        return pos is None or int(pos.get("size", 0)) == 0

    def _verify_position(self, expected_side=None):
        pos = self._get_active_position()
        if not pos or int(pos.get("size", 0)) <= 0:
            return None
        side = "LONG" if pos["posSide"] == "long" else "SHORT"
        if expected_side and side != expected_side:
            return None
        return pos

    def _collect_limit_tp_prices(self):
        prices = []
        for o in deepcoin_client.get_pending_orders(self.symbol):
            if o.get("ordType") not in ("limit", "post_only", None):
                continue
            px = float(o.get("px", 0) or 0)
            if px > 0:
                prices.append(round(px, 2))
        return sorted(prices)

    def _expected_tp_count(self, tp_pxs=None):
        tp_pxs = tp_pxs if tp_pxs is not None else self.tv_tps
        return sum(1 for t in tp_pxs if t > 0)

    def _wait_tp_hung(self, tp_pxs, retries=5, delay=0.8):
        expected = self._expected_tp_count(tp_pxs)
        matched, pending = 0, []
        for _ in range(retries):
            matched, pending = self._count_matched_tp_orders(tp_pxs)
            if expected == 0 or matched >= expected:
                return matched, pending
            time.sleep(delay)
        return matched, pending

    def _count_matched_tp_orders(self, tp_pxs, tolerance=1.0):
        pending_prices = self._collect_limit_tp_prices()
        matched = 0
        for tp in tp_pxs:
            if tp <= 0:
                continue
            if any(abs(p - tp) <= tolerance for p in pending_prices):
                matched += 1
        return matched, pending_prices

    def _has_trigger_sl_near(self, sl_price, tolerance=2.0):
        for t in deepcoin_client.get_trigger_orders_pending(self.symbol):
            for key in ("triggerPx", "slTriggerPrice", "triggerPrice"):
                val = t.get(key)
                if val is not None and str(val).strip() not in ("", "0"):
                    try:
                        if abs(float(val) - sl_price) <= tolerance:
                            return True
                    except (TypeError, ValueError):
                        pass
        return False

    def _wait_verify(self, checks_fn, retries=3, delay=0.6):
        for i in range(retries):
            result = checks_fn()
            if result:
                return result
            time.sleep(delay)
        return checks_fn()

    def _calculate_tp_quantities(self, total_qty: int, ratios: list) -> tuple:
        """深币最小 1 张限制 + 余数吸收：qty1+qty2+qty3 恒等于 total_qty"""
        if total_qty <= 0:
            return 0, 0, 0

        qty1 = max(1, round(total_qty * ratios[0]))
        remaining = total_qty - qty1
        if remaining <= 0:
            return qty1, 0, 0

        ratio_sum_23 = ratios[1] + ratios[2]
        if ratio_sum_23 <= 0:
            return qty1, 0, remaining

        qty2 = max(0, round(remaining * (ratios[1] / ratio_sum_23)))
        qty3 = remaining - qty2
        if qty3 < 0:
            qty3, qty2 = 0, remaining

        if qty2 == 0 and remaining >= 2:
            qty2, qty3 = 1, remaining - 1
        if qty3 == 0 and remaining >= 2 and qty2 > 1:
            qty3, qty2 = 1, remaining - 1

        assert qty1 + qty2 + qty3 == total_qty, f"TP 分档不守恒: {qty1}+{qty2}+{qty3}!={total_qty}"
        return qty1, qty2, qty3

    def _resolve_live_qty(self, fallback_qty: int) -> int:
        """挂 reduceOnly 前重新读取交易所落账张数，避免冻结/部分成交导致数量漂移"""
        pos = self._get_active_position()
        if pos and int(pos.get("size", 0)) > 0:
            live = int(pos["size"])
            if live != fallback_qty:
                logger.info(f"📐 实盘张数校正: 账本 {fallback_qty} → 交易所 {live}")
            return live
        return fallback_qty

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        if self.regime not in self.regime_settings:
            self.regime = 3

        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_price = float(payload.get("price", 0.0))
        self.tv_tps = [
            float(payload.get("tv_tp1", 0)),
            float(payload.get("tv_tp2", 0)),
            float(payload.get("tv_tp3", 0)),
        ]
        close_reason = payload.get("reason", "策略指标反转/波动率安全退出")

        if not raw_action:
            return
        if not self._lock.acquire(timeout=10.0):
            return

        try:
            self.monitoring = False
            if raw_action == "CLOSE_PROTECT" or raw_action.startswith("CLOSE_PROTECT"):
                self._close_all(f"🛡️ 保护性全平：{close_reason}")
            elif raw_action == "CLOSE_TP3":
                self._close_all("🎯 完美胜利：大趋势吃满，TP3 终极收网")
            elif raw_action == "CLOSE":
                self._close_all(f"🧹 换防清场：{close_reason}")
            elif raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self._save_state()
                self._handle_smart_entry(raw_action)
        finally:
            self._lock.release()

    def _handle_smart_entry(self, action):
        """三重把关之一：新 TV 方向到达 → 先平后开（撤单→平仓→再开仓）"""
        logger.info(f"⚡ 收到建仓信号 [{action}]，启动绝对先平后开机制")
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            current_side = "LONG" if pos["posSide"] == "long" else "SHORT"
            if current_side == action:
                self._close_all("同方向新指令到达，触发【先平后开】洗清旧阵地")
            else:
                self._close_all("反方向指令到达，触发【先平后开】原子对冲换防")
            time.sleep(1.2)
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.5)

        curr_px = deepcoin_client.get_current_price(self.symbol)
        if curr_px > 0:
            self._open_position(action, curr_px)

    def _open_position(self, action, curr_px):
        balance = deepcoin_client.get_available_balance()
        margin_pct = self.regime_settings[self.regime]["margin"]

        deepcoin_client.set_leverage(self.symbol, leverage=self.leverage)
        qty = max(int((balance * margin_pct * self.leverage) / (curr_px * self.face_value)), 1)
        open_side = "buy" if action == "LONG" else "sell"
        pos_side = "long" if action == "LONG" else "short"

        logger.info(f"🚀 [唯一主仓] 极速开仓: {open_side} {qty} 张 | 档位 {self.regime}")
        deepcoin_client.place_market_order(self.symbol, open_side, pos_side, qty)
        time.sleep(2.0)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self.current_side = action
            real_qty = int(pos['size'])
            self.initial_qty = real_qty
            self._protect_and_monitor(real_qty, pos['entry_price'])

    def _protect_and_monitor(self, qty, entry_price):
        tp_pxs = self.tv_tps
        self.current_sl = entry_price
        self.best_price = entry_price
        self.watched_qty, self.watched_entry, self.monitoring = qty, entry_price, True
        self._save_state()

        self._rebuild_defenses(qty, entry_price, dynamic_sl=None)

        verified = self._wait_verify(lambda: self._verify_position(self.current_side))
        if verified:
            matched, pending_prices = self._wait_tp_hung(tp_pxs)
            expected = self._expected_tp_count(tp_pxs)
            verify_note = (
                f"持仓 {verified['size']}张 @ {verified['entry_price']:.2f} | "
                f"限价止盈 {matched}/{expected} 档 | 挂单价 {pending_prices}"
            )
            dingtalk.report_supervisor_open(
                self.current_side, verified['entry_price'], self.tv_price,
                verified['size'], tp_pxs, self.current_atr, self.regime, self.tv_tps,
                verify_note=verify_note,
            )
            if expected > 0 and matched < expected:
                dingtalk.report_system_alert(
                    "开仓后限价止盈未全部挂上",
                    f"{self.current_side} {verified['size']}张 | 仅 {matched}/{expected} 档 | 挂单价 {pending_prices}",
                )
        else:
            logger.warning("开仓钉钉跳过：实盘持仓核查未通过")
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                if not self._lock.acquire(timeout=2.0):
                    continue
                try:
                    pos = self._get_active_position()
                    real_amt = int(pos.get("size", 0)) if pos else 0
                    actual_side = "LONG" if pos and pos.get('posSide') == "long" else "SHORT"

                    if real_amt == 0:
                        if self.watched_qty > 0:
                            self._close_all("仓位归零 (达到目标止盈或 TV 强制平仓)")
                        break

                    if actual_side != self.last_tv_side:
                        reason = f"致命方向背离：实盘({actual_side}) vs TV({self.last_tv_side})"
                        self._close_all(reason, force_align=(actual_side, self.last_tv_side))
                        break

                    if abs(real_amt - self.watched_qty) != 0:
                        old_qty = self.watched_qty
                        self.watched_qty = real_amt
                        self.watched_entry = pos['entry_price']

                        logger.info(f"🔄 [智慧大脑] 感知到仓位变化: {old_qty} ➔ {real_amt}，重新重构防线！")
                        deepcoin_client.cancel_all_open_orders(self.symbol)
                        time.sleep(1.0)

                        sl_to_pass = None
                        if (self.current_side == "LONG" and self.current_sl > self.watched_entry) or \
                           (self.current_side == "SHORT" and self.current_sl < self.watched_entry):
                            sl_to_pass = self.current_sl
                        self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=sl_to_pass)

                        verified = self._verify_position(self.current_side)
                        if verified and int(verified['size']) == real_amt:
                            matched, pending_prices = self._wait_tp_hung(self.tv_tps)
                            verify_note = (
                                f"核实 {real_amt}张 @ {verified['entry_price']:.2f} | "
                                f"重挂止盈 {matched} 档 | 挂单价 {pending_prices}"
                            )
                            action_msg = "手动加仓" if real_amt > old_qty else "部分止盈吃单 / 手动减仓"
                            dingtalk.report_manual_position_change(
                                action_msg, old_qty, real_amt, verified['entry_price'],
                                verify_note=verify_note,
                            )
                        else:
                            logger.warning("人工异动钉钉跳过：实盘核查未通过")

                    curr_px = deepcoin_client.get_current_price(self.symbol)
                    if self.current_side == "LONG":
                        self.best_price = max(self.best_price, curr_px)
                    else:
                        self.best_price = min(self.best_price, curr_px)

                    tp1_dist = abs(self.tv_tps[0] - self.watched_entry) if self.tv_tps[0] > 0 else self.current_atr * 1.5
                    cfg = self.regime_settings[self.regime]
                    activation_ratio = cfg["activation"]
                    trail_atr_multiplier = cfg["trail_offset"]

                    if self.current_side == "LONG":
                        required = self.watched_entry + tp1_dist * activation_ratio
                        has_moved_favorably = curr_px >= required
                    else:
                        required = self.watched_entry - tp1_dist * activation_ratio
                        has_moved_favorably = curr_px <= required

                    if has_moved_favorably:
                        trail_offset = self.current_atr * trail_atr_multiplier
                        fee_buffer = self.watched_entry * 0.0015

                        if self.current_side == "LONG":
                            breakeven_floor = self.watched_entry + fee_buffer
                            new_sl = max(round(self.best_price - trail_offset, 2), breakeven_floor)
                            if new_sl > self.current_sl + 1.0:
                                deepcoin_client.cancel_all_open_orders(self.symbol)
                                time.sleep(0.5)
                                self.current_sl = new_sl
                                self._save_state()
                                self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=new_sl)
                                if self._has_trigger_sl_near(new_sl):
                                    verify_note = f"条件止损已挂 @ {new_sl:.2f} | 持仓 {real_amt}张"
                                    dingtalk.report_intervention(
                                        real_amt, self.watched_entry, new_sl,
                                        f"🚀 档位{self.regime} 雷达激活：保本盾升起，锁润底线物理推升！",
                                        verify_note=verify_note,
                                    )
                                else:
                                    logger.warning(f"雷达钉钉跳过：条件止损 @{new_sl} 实盘核查未通过")
                        else:
                            breakeven_floor = self.watched_entry - fee_buffer
                            new_sl = min(round(self.best_price + trail_offset, 2), breakeven_floor)
                            if self.current_sl >= self.watched_entry or new_sl < self.current_sl - 1.0:
                                deepcoin_client.cancel_all_open_orders(self.symbol)
                                time.sleep(0.5)
                                self.current_sl = new_sl
                                self._save_state()
                                self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=new_sl)
                                if self._has_trigger_sl_near(new_sl):
                                    verify_note = f"条件止损已挂 @ {new_sl:.2f} | 持仓 {real_amt}张"
                                    dingtalk.report_intervention(
                                        real_amt, self.watched_entry, new_sl,
                                        f"🚀 档位{self.regime} 雷达激活：保本盾降下，锁润顶线物理下压！",
                                        verify_note=verify_note,
                                    )
                                else:
                                    logger.warning(f"雷达钉钉跳过：条件止损 @{new_sl} 实盘核查未通过")
                finally:
                    self._lock.release()
            except Exception as e:
                logger.error(f"哨兵异常: {e}")
            time.sleep(6)

    def _rebuild_defenses(self, qty, entry, dynamic_sl=None):
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"
        ratios = self.regime_settings[self.regime]["ratios"]

        live_qty = self._resolve_live_qty(qty)
        if live_qty <= 0:
            logger.warning(f"重建防线跳过：交易所无可用持仓 (传入 {qty} 张)")
            return 0
        if live_qty != qty:
            self.watched_qty = live_qty
            self._save_state()

        qty1, qty2, qty3 = self._calculate_tp_quantities(live_qty, ratios)
        tp_pxs = self.tv_tps
        placed = 0

        logger.info(
            f"🕸️ 补挂 TP123: 总 {live_qty}张 → TP1={qty1} TP2={qty2} TP3={qty3} "
            f"(合计 {qty1 + qty2 + qty3})"
        )

        for q, px in ((qty1, tp_pxs[0]), (qty2, tp_pxs[1]), (qty3, tp_pxs[2])):
            if q > 0 and px > 0:
                res = deepcoin_client.place_limit_order(
                    self.symbol, close_side, pos_side, px, q, reduce_only=True,
                )
                if res and deepcoin_client._is_success(res):
                    placed += 1
                time.sleep(0.35)

        if dynamic_sl:
            sl_qty = self._resolve_live_qty(live_qty)
            deepcoin_client.place_trigger_order(
                self.symbol, close_side, pos_side, sl_qty, dynamic_sl,
                order_type="market", td_mode="cross", mrg_position="merge",
            )
        return placed

    def _close_all(self, reason="", force_align=None):
        """三重把关之二：TV 全平/保护性全平 → 先撤单释放冻结仓位，6 轮阶梯强平至归零"""
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        closed_successfully = False

        for round_i in range(6):
            pos = self._get_active_position()
            if not pos or int(pos.get("size", 0)) == 0:
                closed_successfully = True
                break

            close_side = "sell" if pos["posSide"] == "long" else "buy"
            live_sz = int(pos["size"])
            logger.info(f"🔪 强平第 {round_i + 1}/6 轮: {close_side} {live_sz}张 reduceOnly")
            deepcoin_client.place_market_order(
                self.symbol, close_side, pos["posSide"], live_sz, reduce_only=True,
            )
            time.sleep(1.5)

        if not closed_successfully:
            residual = self._get_active_position()
            residual_sz = int(residual["size"]) if residual else 0
            logger.error(f"❌ 6 轮强平后仍有残单: {residual_sz}张")
            dingtalk.report_system_alert(
                "强平未完全归零",
                f"6 轮市价平仓后仍剩 {residual_sz} 张，请人工核查 Deepcoin 盘口",
            )

        self.monitoring = False
        self.watched_qty = 0
        self.current_side = None
        self._save_state()
        deepcoin_client.cancel_all_open_orders(self.symbol)

        if reason and closed_successfully:
            flat = self._wait_verify(self._verify_flat)
            if flat:
                verify_note = "盘口无持仓 | 挂单已清空"
                if force_align:
                    real_side, expected_side = force_align
                    dingtalk.report_force_align(real_side, expected_side, verify_note=verify_note)
                else:
                    dingtalk.report_supervisor_close(reason, verify_note=verify_note)
            else:
                logger.warning(f"平仓钉钉跳过：空仓核查未通过 | reason={reason}")

    def recover_state_on_startup(self):
        """重启闪电接管：核实实盘 → 补挂 TP123 → 恢复雷达 → 钉钉报告"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    s = json.load(f)
                    self.last_tv_side = s.get("last_tv_side")
                    self.current_side = s.get("current_side")
                    self.current_sl = s.get("current_sl", 0.0)
                    self.regime = s.get("regime", 3)
                    self.current_atr = s.get("current_atr", 30.0)
                    self.tv_tps = s.get("tv_tps", [0.0, 0.0, 0.0])
                    self.best_price = s.get("best_price", 0.0)
                    self.watched_qty = s.get("watched_qty", 0)
                    self.watched_entry = s.get("watched_entry", 0.0)

            pos = self._get_active_position()
            if pos and int(pos.get("size", 0)) != 0:
                real_amt = int(pos["size"])
                self.current_side = "LONG" if pos.get("posSide") == "long" else "SHORT"
                if not self.last_tv_side:
                    self.last_tv_side = self.current_side

                self.watched_qty = self.initial_qty = real_amt
                self.watched_entry = float(pos["entry_price"])
                if self.best_price == 0.0:
                    self.best_price = self.watched_entry
                if self.current_sl == 0.0:
                    self.current_sl = self.watched_entry

                radar_active = (
                    (self.current_side == "LONG" and self.current_sl > self.watched_entry) or
                    (self.current_side == "SHORT" and self.current_sl < self.watched_entry)
                )
                sl_to_pass = self.current_sl if radar_active else None

                logger.info(
                    f"🔄 [系统重启点火] 检测到实盘持仓 {self.current_side} {real_amt}张，"
                    f"雷达={'已激活' if radar_active else '待命'}"
                )

                deepcoin_client.cancel_all_open_orders(self.symbol)
                time.sleep(1.0)

                expected = self._expected_tp_count(self.tv_tps)
                for attempt in range(3):
                    placed = self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=sl_to_pass)
                    logger.info(f"重启补挂 TP 尝试 {attempt + 1}/3，API 返回成功 {placed}/{expected} 笔")
                    matched, pending_prices = self._wait_tp_hung(self.tv_tps, retries=4, delay=0.8)
                    if expected == 0 or matched >= expected:
                        break
                    logger.warning(
                        f"重启补挂 TP 未完成 ({matched}/{expected})，挂单价 {pending_prices}，准备重试"
                    )
                    time.sleep(1.0)

                self.monitoring = True
                self._save_state()

                threading.Thread(target=self._sentinel_loop, daemon=True).start()

                verified = self._verify_position(self.current_side)
                if verified and int(verified['size']) == real_amt:
                    verify_note = (
                        f"接管 {real_amt}张 @ {verified['entry_price']:.2f} | "
                        f"止盈 {matched} 档 | 挂单价 {pending_prices}"
                    )
                    dingtalk.report_recover_takeover(
                        self.current_side, real_amt, verified['entry_price'],
                        self.tv_tps, self.regime, radar_active, self.current_sl,
                        verify_note=verify_note,
                        tp_matched=matched,
                        tp_expected=expected,
                    )
                    if expected > 0 and matched < expected:
                        dingtalk.report_system_alert(
                            "重启接管后限价止盈未挂上",
                            f"{self.current_side} {real_amt}张 @ {verified['entry_price']:.2f} | "
                            f"仅 {matched}/{expected} 档 | 挂单价 {pending_prices} | 请查 logs/deepcoin_brain.log",
                        )
                else:
                    logger.warning("重启接管钉钉跳过：实盘核查未通过")
                logger.info("  -> 🎉 实盘阵地接管完毕，TP123 及雷达系统已复位。")
            else:
                logger.info("🔄 [系统重启点火] 盘口干净无持仓，账本复位为空仓待命。")
                self.monitoring = False
                self.watched_qty = 0
                self._save_state()
        except Exception as e:
            logger.error(f"❌ 闪电接管异常: {e}")
            dingtalk.report_system_alert("重启接管失败", str(e))


position_supervisor = PositionSupervisor()

# 仅在被 app / gunicorn 导入时执行一次闪电接管（避免 deploy 重复启动双进程）
if __name__ != "__main__":
    position_supervisor.recover_state_on_startup()
