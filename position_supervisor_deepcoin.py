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

        # ==================== VPS 内置四档位参数（核心） ====================
        self.regime_settings = {
            1: {"margin": 0.18, "ratios": [0.40, 0.35, 0.25], "tp_m": [2.0, 4.5, 7.5], "sl_m": 1.0, "trail": 0.55},
            2: {"margin": 0.25, "ratios": [0.35, 0.35, 0.30], "tp_m": [2.5, 5.0, 8.0], "sl_m": 1.1, "trail": 0.60},
            3: {"margin": 0.32, "ratios": [0.30, 0.35, 0.35], "tp_m": [3.0, 5.5, 8.5], "sl_m": 1.2, "trail": 0.65},
            4: {"margin": 0.40, "ratios": [0.25, 0.35, 0.40], "tp_m": [3.5, 6.0, 9.5], "sl_m": 1.3, "trail": 0.70}
        }

        self.leverage = 20
        self.face_value = 0.1
        self.price_diff_pct = 0.0035

        self.regime = 3
        self.current_atr = 30.0
        self.tv_price = 0.0

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
        logger.info("🧠 深币 VPS [V11.0 四档位分批止盈雷达版] 已加载")

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    "last_tv_side": self.last_tv_side,
                    "current_side": self.current_side,
                    "watched_qty": self.watched_qty,
                    "watched_entry": self.watched_entry,
                    "current_sl": self.current_sl,
                    "monitoring": self.monitoring
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

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        if self.regime not in self.regime_settings:
            self.regime = 3
        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_price = round(float(payload.get("price", 0.0)), 2)

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
            if current_side == action:
                self._close_all("同方向强制先平后开")
            else:
                self._close_all("反方向强制先平后开")
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
        logger.info(f"🚀 开仓: {open_side} {qty}张 | Regime {self.regime} | 比例 {margin_ratio*100:.0f}%")

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

        # 计算三档止盈价
        tp_pxs = []
        if self.current_side == "LONG":
            tp_pxs = [round(entry_price + self.current_atr * m, 2) for m in tp_m]
            self.current_sl = round(entry_price - self.current_atr * sl_m, 2)
        else:
            tp_pxs = [round(entry_price - self.current_atr * m, 2) for m in tp_m]
            self.current_sl = round(entry_price + self.current_atr * sl_m, 2)

        # 分批挂限价止盈
        for i, (ratio, tp_px) in enumerate(zip(ratios, tp_pxs)):
            q = max(int(qty * ratio), 1)
            if q >= 1:
                deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_px, q, reduce_only=True)

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

                    if actual_qty == 0 and self.watched_qty > 0:
                        self._close_all("仓位归零")
                        break

                    if actual_side != self.last_tv_side and actual_qty > 0:
                        self._close_all("方向异常强制对齐")
                        dingtalk.report_force_align(actual_side, self.last_tv_side)
                        break

                    # TODO: 可在此处继续扩展保本止损上移逻辑（后续迭代）

                finally:
                    self._lock.release()
            except Exception as e:
                logger.error(f"哨兵异常: {e}")
            time.sleep(4)

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
                self.monitoring = True
                threading.Thread(target=self._sentinel_loop, daemon=True).start()
                logger.info(f"🔄 启动恢复持仓: {self.current_side} {real_amt}张")
        except Exception as e:
            logger.error(f"启动恢复异常: {e}")


position_supervisor = PositionSupervisor()
position_supervisor.recover_state_on_startup()
