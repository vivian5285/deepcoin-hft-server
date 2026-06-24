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

        # 第一重：覆盖手续费 + 保本
        self.fee_cover_margin = 0.0014
        self.radar_activated = False
        self.fee_cover_price = 0.0
        self.tv_tp1 = 0.0

        self.current_side = None
        self.last_tv_side = None
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_sl = 0.0

        # 深币专用：固定金额阈值（推荐 $7）
        self.price_diff_threshold = 7.0

        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [最终版 - 固定金额 $7 阈值] 已加载")

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        self.tv_tp1 = float(payload.get("tv_tp1", 0.0))

        if not raw_action: return
        if not self._lock.acquire(blocking=False): return

        try:
            self.monitoring = False
            self.radar_activated = False

            if raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self._handle_smart_entry(raw_action)

        finally:
            self._lock.release()

    # ==================== 深币智能入场处理（固定金额 $7） ====================
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
            # 同方向
            diff = abs(alert_price - avg_price)
            if diff <= self.price_diff_threshold:
                logger.info(f"[深币忽略] 同方向差异 ${diff:.2f} ≤ ${self.price_diff_threshold}，直接忽略")
                return
            else:
                logger.info(f"[深币换仓] 同方向差异 ${diff:.2f} > ${self.price_diff_threshold}，执行先平后开")
                self._close_all("同方向换仓")
                time.sleep(1.2)
                self._open_position(action)
        else:
            # 反方向
            logger.info("[深币反方向] 执行先平后开")
            self._close_all("反方向信号")
            time.sleep(1.2)
            self._open_position(action)

    def _open_position(self, side):
        curr_px = deepcoin_client.get_current_price(self.symbol)
        qty = round(deepcoin_client.get_available_balance() * 0.28 / curr_px, 3)

        deepcoin_client.place_market_order(side, qty)
        time.sleep(2)

        pos = position_manager.get_position(self.symbol)
        if pos and float(pos.get("positionAmt", 0)) != 0:
            self.current_side = side
            self.watched_qty = abs(float(pos["positionAmt"]))
            self.watched_entry = float(pos["entryPrice"])
            self.current_sl = self.watched_entry
            self.radar_activated = False
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

                # 第一重：到达保本位
                reached = False
                if self.current_side == "LONG" and curr_px >= self.fee_cover_price:
                    reached = True
                elif self.current_side == "SHORT" and curr_px <= self.fee_cover_price:
                    reached = True

                if reached and not self.radar_activated:
                    self.radar_activated = True
                    self.current_sl = self.fee_cover_price
                    dingtalk.report_fee_cover_reached(self.current_side, self.watched_entry, self.fee_cover_price, remaining_qty)

                    # 有剩余仓位才切换到 TV tp1
                    if remaining_qty > 0.001 and self.tv_tp1 > 0:
                        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
                        deepcoin_client.place_limit_order(close_side, remaining_qty, self.tv_tp1, reduce_only=True)
                        dingtalk.report_switch_to_tp1(self.current_side, remaining_qty, self.tv_tp1)

                # 雷达移动保本止损
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
                        deepcoin_client.cancel_all_open_orders()
                        time.sleep(0.3)
                        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
                        deepcoin_client.place_stop_market_order(close_side, self.current_sl)
                        dingtalk.report_radar_move(self.current_side, self.current_sl)

            except Exception as e:
                logger.error(f"雷达异常: {e}")
            time.sleep(3.5)

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
