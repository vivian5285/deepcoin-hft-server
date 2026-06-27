#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging, time, threading, os, json
from logging.handlers import RotatingFileHandler
from deepcoin_client import deepcoin_client
import dingtalk

if not os.path.exists('logs'): os.makedirs('logs')
handler = RotatingFileHandler('logs/deepcoin_brain.log', maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Deepcoin: %(message)s', handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)

class PositionSupervisor:
    def __init__(self):
        self.symbol = "ETH-USDT-SWAP"
        self.monitoring = False
        self._lock = threading.Lock()

        # ==================== 四档位参数（与币安V12.2 + Pine v6.9.19 完全同频） ====================
        self.regime_settings = {
            1: {"margin": 0.15, "ratios": [0.25, 0.35, 0.40], "tp_m": [0.75, 1.40, 2.00], "sl_m": 0.90, "trail": 0.55},
            2: {"margin": 0.25, "ratios": [0.20, 0.35, 0.45], "tp_m": [1.10, 2.00, 2.80], "sl_m": 1.05, "trail": 0.60},
            3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "tp_m": [1.30, 2.60, 3.80], "sl_m": 1.10, "trail": 0.65},
            4: {"margin": 0.50, "ratios": [0.05, 0.20, 0.75], "tp_m": [1.55, 3.00, 4.80], "sl_m": 1.25, "trail": 0.70}
        }

        self.leverage = 20
        self.face_value = 0.1

        self.regime = 3
        self.current_atr = 30.0
        self.tv_price = 0.0
        self.tv_tps = [0.0, 0.0, 0.0]

        self.current_side = None
        self.last_tv_side = None
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_sl = 0.0
        self.initial_qty = 0.0
        self.best_price = 0.0
        self.radar_activated = False
        self.manual_intervention_flag = False

        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [V12.4 最小下单量优化版] 已加载 - 参数与币安完全同频")

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    "last_tv_side": self.last_tv_side, "current_side": self.current_side,
                    "watched_qty": self.watched_qty, "watched_entry": self.watched_entry,
                    "current_sl": self.current_sl, "monitoring": self.monitoring
                }, f)
        except:
            pass

    def _get_active_position(self):
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                if int(p.get("pos", 0)) > 0:
                    return {
                        "size": int(p.get("pos")),
                        "entry_price": round(float(p.get("avgPx", p.get("price", 0))), 2),
                        "posSide": p.get("posSide", "long").lower()
                    }
        return None

    # ==================== 优先保证TP1至少1张的切分逻辑 ====================
    def _calculate_tp_quantities(self, total_qty: int, ratios: list) -> tuple:
        if total_qty <= 0:
            return 0, 0, 0

        raw_q1 = total_qty * ratios[0]
        q1 = max(1, round(raw_q1))
        remaining = total_qty - q1

        if remaining <= 0:
            return q1, 0, 0

        ratio_sum_23 = ratios[1] + ratios[2]
        if ratio_sum_23 <= 0:
            return q1, 0, remaining

        raw_q2 = remaining * (ratios[1] / ratio_sum_23)
        q2 = max(0, round(raw_q2))
        q3 = remaining - q2

        if q3 < 0:
            q3 = 0
            q2 = remaining

        # 微调避免0张
        if q2 == 0 and remaining >= 2:
            q2 = 1
            q3 = remaining - 1
        if q3 == 0 and remaining >= 2 and q2 > 1:
            q3 = 1
            q2 = remaining - 1

        return q1, q2, q3

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        if self.regime not in self.regime_settings:
            self.regime = 3
        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_price = round(float(payload.get("price", 0.0)), 2)
        self.tv_tps = [
            float(payload.get("tv_tp1", 0)),
            float(payload.get("tv_tp2", 0)),
            float(payload.get("tv_tp3", 0))
        ]

        if not raw_action:
            return
        if not self._lock.acquire(timeout=10.0):
            logger.error("⚠️ 系统正忙，指令被丢弃")
            return
        try:
            if raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self.manual_intervention_flag = False
                self._save_state()
                self._handle_smart_entry(raw_action)
            elif raw_action in ["CLOSE_TP3", "CLOSE"]:
                self._close_all("策略清场指令")
            elif raw_action.startswith("CLOSE_PROTECT"):
                self._close_all("保护性全平")
        finally:
            self._lock.release()

    def _handle_smart_entry(self, action):
        logger.info(f"⚡ 收到建仓信号 [{action}]，启动强制净身流程")
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)

        current_pos = self._get_active_position()
        curr_px = deepcoin_client.get_current_price(self.symbol)

        if current_pos and current_pos.get('size', 0) > 0:
            current_side = "LONG" if current_pos["posSide"] == "long" else "SHORT"
            self._close_all("同方向" if current_side == action else "反方向" + "强制先平后开")
            time.sleep(1.2)

        for attempt in range(3):
            pos = self._get_active_position()
            if not pos or int(pos.get('size', 0)) == 0:
                break
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4)
            deepcoin_client._request("POST", "/trade/batch-close-position", {"productGroup": "SwapU", "instId": self.symbol})
            time.sleep(1.2)

        self._open_position(action, curr_px)

    def _open_position(self, side, curr_px):
        if curr_px <= 0:
            return

        cfg = self.regime_settings[self.regime]
        margin_ratio = cfg["margin"]

        available = deepcoin_client.get_available_balance()
        qty = max(int((available * margin_ratio * self.leverage) / (curr_px * self.face_value)), 1)

        open_side, pos_side = ("buy", "long") if side == "LONG" else ("sell", "short")
        logger.info(f"🚀 开仓: {open_side} {qty}张 | Regime {self.regime}")

        deepcoin_client.place_market_order(self.symbol, open_side, pos_side, qty)
        time.sleep(2.0)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self.current_side = side
            real_qty = int(pos['size'])
            self.initial_qty = real_qty
            self.watched_qty = real_qty
            self.watched_entry = pos['entry_price']
            self.best_price = self.watched_entry
            self._protect_and_monitor(real_qty, self.watched_entry)

    def _protect_and_monitor(self, qty, entry_price):
        cfg = self.regime_settings[self.regime]
        ratios, tp_m, sl_m = cfg["ratios"], cfg["tp_m"], cfg["sl_m"]

        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"

        qty1, qty2, qty3 = self._calculate_tp_quantities(qty, ratios)
        logger.info(f"[TP切分] Regime{self.regime} Total={qty} → TP1={qty1}, TP2={qty2}, TP3={qty3}")

        tp_pxs = []
        if self.current_side == "LONG":
            tp_pxs = [round(entry_price + self.current_atr * m, 2) for m in tp_m]
            self.current_sl = round(entry_price - self.current_atr * sl_m, 2)
        else:
            tp_pxs = [round(entry_price - self.current_atr * m, 2) for m in tp_m]
            self.current_sl = round(entry_price + self.current_atr * sl_m, 2)

        if qty1 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[0], qty1, reduce_only=True)
        if qty2 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[1], qty2, reduce_only=True)
        if qty3 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[2], qty3, reduce_only=True)

        self.radar_activated = False
        self.monitoring = True
        self._save_state()

        dingtalk.report_deepcoin_open(self.current_side, self.regime, self.current_atr, entry_price, self.tv_price, qty, tp_pxs)
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                if not self._lock.acquire(timeout=2.0):
                    time.sleep(1.0)
                    continue
                try:
                    pos = self._get_active_position()
                    actual_qty = int(pos['size']) if pos else 0
                    actual_side = "LONG" if pos and pos.get('posSide') == "long" else "SHORT"
                    curr_px = deepcoin_client.get_current_price(self.symbol)

                    if actual_qty > 0 and actual_side != self.last_tv_side:
                        self._close_all("方向异常强制对齐")
                        dingtalk.report_force_align(actual_side, self.last_tv_side)
                        break

                    if actual_qty == 0 and self.watched_qty > 0:
                        self._close_all("仓位归零")
                        break

                    if actual_qty != self.watched_qty and actual_qty > 0:
                        old_qty = self.watched_qty
                        self.watched_qty = actual_qty
                        self.watched_entry = pos['entry_price']
                        self._save_state()
                        deepcoin_client.cancel_all_open_orders(self.symbol)
                        time.sleep(0.4)

                        new_q1, new_q2, new_q3 = self._calculate_tp_quantities(actual_qty, self.regime_settings[self.regime]["ratios"])
                        close_side = "sell" if self.current_side == "LONG" else "buy"
                        pos_side = "long" if self.current_side == "LONG" else "short"
                        tp_pxs = [round(self.watched_entry + self.current_atr * m, 2) if self.current_side == "LONG"
                                  else round(self.watched_entry - self.current_atr * m, 2)
                                  for m in self.regime_settings[self.regime]["tp_m"]]

                        if new_q1 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[0], new_q1, reduce_only=True)
                        if new_q2 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[1], new_q2, reduce_only=True)
                        if new_q3 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[2], new_q3, reduce_only=True)

                        action_msg = "手动加仓" if actual_qty > old_qty else "手动减仓"
                        dingtalk.report_manual_position_change(action_msg, old_qty, actual_qty, self.watched_entry)

                    # 保本止损上移
                    cfg = self.regime_settings[self.regime]
                    tp1_m = cfg["tp_m"][0]
                    trail_factor = cfg["trail"]
                    activation_ratio = 0.55

                    is_breakeven = actual_qty < (self.initial_qty * 0.95)
                    required = self.watched_entry + self.current_atr * tp1_m * activation_ratio if self.current_side == "LONG" else self.watched_entry - self.current_atr * tp1_m * activation_ratio
                    has_moved_favorably = curr_px >= required if self.current_side == "LONG" else curr_px <= required

                    if is_breakeven and has_moved_favorably:
                        trail_offset = self.current_atr * trail_factor * 0.45
                        new_sl = None
                        if self.current_side == "LONG":
                            new_sl = max(round(self.best_price - trail_offset, 2), self.watched_entry)
                            if new_sl > self.current_sl + 1.5:
                                self.current_sl = new_sl
                                self._save_state()
                                self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=new_sl)
                                dingtalk.report_radar_move(self.current_side, new_sl)
                        else:
                            new_sl = min(round(self.best_price + trail_offset, 2), self.watched_entry)
                            if new_sl < self.current_sl - 1.5:
                                self.current_sl = new_sl
                                self._save_state()
                                self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=new_sl)
                                dingtalk.report_radar_move(self.current_side, new_sl)

                    self.best_price = max(self.best_price, curr_px) if self.current_side == "LONG" else min(self.best_price, curr_px)

                finally:
                    self._lock.release()
            except Exception as e:
                logger.error(f"哨兵异常: {e}")
            time.sleep(4)

    def _rebuild_defenses(self, qty, entry, dynamic_sl=None):
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"

        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.4)

        qty1, qty2, qty3 = self._calculate_tp_quantities(qty, self.regime_settings[self.regime]["ratios"])
        tp_pxs = [round(entry + self.current_atr * m, 2) if self.current_side == "LONG"
                  else round(entry - self.current_atr * m, 2)
                  for m in self.regime_settings[self.regime]["tp_m"]]

        if qty1 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[0], qty1, reduce_only=True)
        if qty2 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[1], qty2, reduce_only=True)
        if qty3 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[2], qty3, reduce_only=True)

        if dynamic_sl:
            deepcoin_client.place_stop_market_order(self.symbol, close_side, pos_side, dynamic_sl)

    def _close_all(self, reason=""):
        logger.warning(f"🔨 全平: {reason}")
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)

        for _ in range(6):
            deepcoin_client._request("POST", "/trade/batch-close-position", {"productGroup": "SwapU", "instId": self.symbol})
            time.sleep(1.5)
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0:
                break

        self.monitoring = False
        self.watched_qty = 0
        self._save_state()
        dingtalk.report_deepcoin_clear(reason, "✅ 全平完成")

    def recover_state_on_startup(self):
        try:
            pos = self._get_active_position()
            if pos and pos.get('size', 0) > 0:
                real_amt = int(pos['size'])
                self.current_side = "LONG" if pos.get('posSide') == "long" else "SHORT"
                self.watched_qty = real_amt
                self.initial_qty = real_amt
                self.watched_entry = pos['entry_price']
                self.current_sl = self.watched_entry
                self.best_price = self.watched_entry
                self.monitoring = True
                threading.Thread(target=self._sentinel_loop, daemon=True).start()
                logger.info(f"🔄 启动恢复持仓: {self.current_side} {real_amt}张")
        except Exception as e:
            logger.error(f"启动恢复异常: {e}")


position_supervisor = PositionSupervisor()
position_supervisor.recover_state_on_startup()
