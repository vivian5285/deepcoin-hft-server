#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging, time, threading, os, json
from logging.handlers import RotatingFileHandler
from deepcoin_client import deepcoin_client
from position_manager import position_manager
import dingtalk

if not os.path.exists('logs'): os.makedirs('logs')
handler = RotatingFileHandler('logs/deepcoin_brain.log', maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Deepcoin: %(message)s', handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)

class PositionSupervisor:
    def __init__(self):
        self.symbol = "ETHUSDT"
        self.monitoring = False
        self._lock = threading.Lock()

        self.fee_cover_margin = 0.0014
        self.radar_activated = False
        self.fee_cover_price = 0.0
        self.tv_tp1 = 0.0

        self.current_side = None
        self.last_tv_side = None
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_sl = 0.0
        self.price_diff_threshold = 7.0
        self.last_protect_time = 0

        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [全限价防守+雷达保本版] 已加载：初始硬止损彻底移除！")

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        self.tv_tp1 = float(payload.get("tv_tp1", 0.0))

        if not raw_action: return
        if not self._lock.acquire(blocking=False): return

        try:
            if raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self._handle_smart_entry(raw_action)

            elif raw_action == "CLOSE_TP3":
                if position_manager.has_position(self.symbol):
                    self._close_all("🎯 TP3 止盈全平")

            elif raw_action.startswith("CLOSE_PROTECT"):
                self._handle_protective_close()

        finally:
            self._lock.release()

    def _handle_smart_entry(self, action):
        deepcoin_client.cancel_all_open_orders()
        self._close_all("新方向到达，先全平再开仓")

        current_pos = position_manager.get_position(self.symbol)
        has_position = current_pos and float(current_pos.get("positionAmt", 0)) != 0
        alert_price = self.tv_tp1

        if not has_position:
            self._open_position(action)
            return

        current_side = "LONG" if float(current_pos["positionAmt"]) > 0 else "SHORT"
        avg_price = float(current_pos["entryPrice"])

        if current_side == action:
            diff = abs(alert_price - avg_price)
            if diff <= self.price_diff_threshold:
                logger.info(f"[深币忽略] 同方向差异 ${diff:.2f} ≤ $7，直接忽略")
                return
            else:
                self._close_all("同方向换仓")
                time.sleep(1.2)
                self._open_position(action)
        else:
            self._close_all("反方向信号")
            time.sleep(1.2)
            self._open_position(action)

    def _open_position(self, side):
        curr_px = deepcoin_client.get_current_price(self.symbol)
        qty = round(deepcoin_client.get_available_balance() * 0.28 / curr_px, 3)
        qty = max(qty, round(10.0 / curr_px + 0.001, 3)) 

        deepcoin_client.place_market_order(side, qty)
        time.sleep(2)

        pos = position_manager.get_position(self.symbol)
        if pos and float(pos.get("positionAmt", 0)) != 0:
            self.current_side = side
            self.watched_qty = abs(float(pos["positionAmt"]))
            self.watched_entry = float(pos["entryPrice"])
            self.current_sl = self.watched_entry
            self.radar_activated = False
            self._protect_and_monitor(self.watched_qty, self.watched_entry)

    def _protect_and_monitor(self, qty, entry_price):
        if self.current_side == "LONG":
            self.fee_cover_price = round(entry_price * (1 + self.fee_cover_margin), 2)
        else:
            self.fee_cover_price = round(entry_price * (1 - self.fee_cover_margin), 2)

        distance = abs(self.fee_cover_price - self.tv_tp1)
        if distance > 0.10: fee_ratio = 0.80
        elif distance > 0.06: fee_ratio = 0.65
        else: fee_ratio = 0.50

        qty_fee = int(qty * fee_ratio)
        qty_tp1 = int(qty) - qty_fee

        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"

        # 🚀 开仓立刻挂上 覆盖手续费的限价单 与 剩余头寸的TP1单。初始硬止损移除！
        if qty_fee > 0:
            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.fee_cover_price, qty_fee)
        if qty_tp1 > 0 and self.tv_tp1 > 0:
            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.tv_tp1, qty_tp1)

        dingtalk.report_deepcoin_open(self.current_side, entry_price, qty, self.fee_cover_price, self.tv_tp1)
        self._start_radar_monitor()

    def _start_radar_monitor(self):
        self.monitoring = True
        threading.Thread(target=self._radar_loop, daemon=True).start()

    def _radar_loop(self):
        while self.monitoring:
            try:
                pos = position_manager.get_position(self.symbol)
                if not pos or float(pos.get("positionAmt", 0)) == 0:
                    self.monitoring = False
                    break

                curr_px = deepcoin_client.get_current_price(self.symbol)
                remaining_qty = abs(float(pos.get("positionAmt", 0)))

                reached = False
                if self.current_side == "LONG" and curr_px >= self.fee_cover_price:
                    reached = True
                elif self.current_side == "SHORT" and curr_px <= self.fee_cover_price:
                    reached = True

                # 🚀 当行情到达保本点（fee_cover_price被吃掉时），雷达激活
                if reached and not self.radar_activated:
                    self.radar_activated = True
                    self.current_sl = self.watched_entry # 锁定成本价
                    dingtalk.report_fee_cover_reached(self.current_side, self.watched_entry, self.fee_cover_price, remaining_qty)

                    close_side = "sell" if self.current_side == "LONG" else "buy"
                    pos_side = "long" if self.current_side == "LONG" else "short"
                    
                    # 挂出保本条件单
                    deepcoin_client._request("POST", "/trade/order-algo", {
                        "instId": self.symbol, "tdMode": "cross", "side": close_side, "posSide": pos_side,
                        "ordType": "conditional", "sz": str(int(remaining_qty)), "triggerPx": str(self.current_sl), "orderPx": "-1"
                    })

                # 🚀 激活后持续追踪剩余仓位（向 TP1 冲锋）
                if self.radar_activated:
                    moved = False
                    if self.current_side == "LONG" and curr_px > self.current_sl:
                        new_sl = max(self.current_sl, curr_px * 0.994)
                        if new_sl > self.current_sl + 0.8:
                            self.current_sl = round(new_sl, 2)
                            moved = True
                    elif self.current_side == "SHORT" and curr_px < self.current_sl:
                        new_sl = min(self.current_sl, curr_px * 1.006)
                        if new_sl < self.current_sl - 0.8:
                            self.current_sl = round(new_sl, 2)
                            moved = True

                    if moved:
                        # 撤销所有挂单（包括没吃掉的限价和旧止损），全面上推
                        deepcoin_client.cancel_all_open_orders()
                        time.sleep(0.3)
                        close_side = "sell" if self.current_side == "LONG" else "buy"
                        pos_side = "long" if self.current_side == "LONG" else "short"

                        # 重新把 TP1 的目标挂上去
                        if self.tv_tp1 > 0:
                            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.tv_tp1, remaining_qty)

                        # 上推最新的雷达止损线
                        deepcoin_client._request("POST", "/trade/order-algo", {
                            "instId": self.symbol, "tdMode": "cross", "side": close_side, "posSide": pos_side,
                            "ordType": "conditional", "sz": str(int(remaining_qty)), "triggerPx": str(self.current_sl), "orderPx": "-1"
                        })
                        dingtalk.report_radar_move(self.current_side, self.current_sl)

            except Exception as e:
                logger.error(f"雷达异常: {e}")
            time.sleep(3.5)

    def _handle_protective_close(self):
        if not position_manager.has_position(self.symbol):
            return
        if time.time() - self.last_protect_time < 30:
            return
        self.last_protect_time = time.time()
        self._close_all("🛡️ 保护性全平")

    def _close_all(self, reason=""):
        deepcoin_client.cancel_all_open_orders()
        time.sleep(0.4)
        deepcoin_client.close_all_positions()
        self.monitoring = False
        self.radar_activated = False
        self.watched_qty = 0.0
        logger.info(f"[全平] {reason}")
        dingtalk.report_supervisor_close(reason)

position_supervisor = PositionSupervisor()
