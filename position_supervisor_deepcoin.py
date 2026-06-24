#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging, time, threading, os, json
from datetime import datetime
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
        self.symbol = "ETH-USDT-SWAP"
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
        logger.info("🧠 深币 VPS [实盘核查紫金版] 已加载：雷达闭环修正完毕")

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
                pos = position_manager.get_position(self.symbol)
                if pos and float(pos.get("positionAmt", 0)) != 0:
                    self._close_all("🎯 TP3 终极止盈全平")

            elif raw_action.startswith("CLOSE_PROTECT"):
                reason = raw_action.split("|")[1] if "|" in raw_action else "保护性清仓"
                self._handle_protective_close(reason)
        finally:
            self._lock.release()

    def _handle_smart_entry(self, action):
        deepcoin_client.force_cancel_all(self.symbol)
        self._close_all("新方向到达，先全平再开仓")

        current_pos = position_manager.get_position(self.symbol)
        has_position = current_pos and float(current_pos.get("positionAmt", 0)) != 0

        if not has_position:
            self._open_position(action)
            return

        current_side = "LONG" if float(current_pos["positionAmt"]) > 0 else "SHORT"
        avg_price = float(current_pos["entryPrice"])

        if current_side == action:
            diff = abs(self.tv_tp1 - avg_price)
            if diff <= self.price_diff_threshold:
                logger.info(f"[深币忽略] 同方向差异 ${diff:.2f} ≤ $7，直接忽略")
                return
            else:
                self._close_all("同方向换仓(差异过大)")
                time.sleep(1.2)
                self._open_position(action)
        else:
            self._close_all("反方向信号")
            time.sleep(1.2)
            self._open_position(action)

    def _open_position(self, side):
        curr_px = deepcoin_client.get_current_price(self.symbol)
        # 极度轻仓，只用可用余额的28%计算数量
        qty = round(deepcoin_client.get_available_balance() * 0.28 / curr_px, 3)
        qty = max(qty, round(10.0 / curr_px + 0.001, 3)) # 至少保证有基本张数

        pos_side = "long" if side == "LONG" else "short"
        res = deepcoin_client.place_market_order(self.symbol, side.lower(), pos_side, qty)
        time.sleep(1.5)

        pos = position_manager.get_position(self.symbol)
        if pos and float(pos.get("positionAmt", 0)) != 0:
            self.current_side = side
            self.watched_qty = abs(float(pos["positionAmt"]))
            self.watched_entry = float(pos["entryPrice"])
            self.current_sl = self.watched_entry
            self.radar_activated = False
            
            # 计算保本线
            if self.current_side == "LONG":
                self.fee_cover_price = round(self.watched_entry * (1 + self.fee_cover_margin), 2)
            else:
                self.fee_cover_price = round(self.watched_entry * (1 - self.fee_cover_margin), 2)

            # 🚀 修复 Bug 1：开仓成功后，正式汇报钉钉
            dingtalk.report_deepcoin_open(self.current_side, self.watched_entry, self.watched_qty, self.fee_cover_price, self.tv_tp1)
            
            self._start_radar_monitor()
        else:
            dingtalk.report_system_alert("开仓失败", "API未返回错误，但实盘核查未发现新仓位！")

    def _start_radar_monitor(self):
        self.monitoring = True
        threading.Thread(target=self._radar_loop, daemon=True).start()

    def _radar_loop(self):
        while self.monitoring:
            try:
                pos = position_manager.get_position(self.symbol)
                if not pos or float(pos.get("positionAmt", 0)) == 0:
                    self._close_all("✅ 隐身雷达：仓位自然归零离场")
                    break

                curr_px = deepcoin_client.get_current_price(self.symbol)
                remaining_qty = abs(float(pos.get("positionAmt", 0)))
                actual_side = "LONG" if float(pos.get("positionAmt", 0)) > 0 else "SHORT"

                # 强行对齐防线
                if actual_side != self.last_tv_side and actual_side in ["LONG", "SHORT"]:
                    self._close_all("强行对齐")
                    dingtalk.report_force_align(actual_side, self.last_tv_side)
                    break

                # 雷达第一阶段：突破保本线
                reached = False
                if self.current_side == "LONG" and curr_px >= self.fee_cover_price:
                    reached = True
                elif self.current_side == "SHORT" and curr_px <= self.fee_cover_price:
                    reached = True

                if reached and not self.radar_activated:
                    self.radar_activated = True
                    self.current_sl = self.fee_cover_price
                    dingtalk.report_fee_cover_reached(self.current_side, self.watched_entry, self.fee_cover_price, remaining_qty)

                    if remaining_qty > 0.001 and self.tv_tp1 > 0:
                        close_side = "sell" if self.current_side == "LONG" else "buy"
                        pos_side = "long" if self.current_side == "LONG" else "short"
                        # 🚀 修复 Bug 2：核查实盘 API 返回结果后，再发钉钉
                        res = deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.tv_tp1, remaining_qty)
                        if res and str(res.get("code", "")) == "0":
                            dingtalk.report_switch_to_tp1(self.current_side, remaining_qty, self.tv_tp1)
                        else:
                            logger.error("挂载 TP1 限价单 API 报错！")

                # 雷达第二阶段：追踪推升
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
                        deepcoin_client.cancel_all_open_orders(self.symbol)
                        time.sleep(0.3)
                        close_side = "sell" if self.current_side == "LONG" else "buy"
                        pos_side = "long" if self.current_side == "LONG" else "short"
                        
                        # 使用深币的条件单 API 来挂止损
                        res = deepcoin_client._request("POST", "/trade/order-algo", {
                            "instId": self.symbol, "tdMode": "cross", "side": close_side, "posSide": pos_side,
                            "ordType": "conditional", "sz": str(int(remaining_qty)), "triggerPx": str(self.current_sl), "orderPx": "-1"
                        })
                        if res and str(res.get("code", "")) == "0":
                            dingtalk.report_radar_move(self.current_side, self.current_sl)

            except Exception as e:
                logger.error(f"雷达异常: {e}")
            time.sleep(3.5)

    def _handle_protective_close(self, reason):
        if not position_manager.has_position(self.symbol):
            return
        if time.time() - self.last_protect_time < 30:
            return
        self.last_protect_time = time.time()
        self._close_all(f"🛡️ 保护触发: {reason}")

    # 🚀 修复 Bug 3：重写深币专属物理平仓，保证 100% 核查
    def _close_all(self, reason=""):
        deepcoin_client.force_cancel_all(self.symbol)
        time.sleep(0.5)
        
        pos = position_manager.get_position(self.symbol)
        if pos and float(pos.get("positionAmt", 0)) != 0:
            qty = abs(float(pos["positionAmt"]))
            close_side = "sell" if float(pos["positionAmt"]) > 0 else "buy"
            pos_side = "long" if float(pos["positionAmt"]) > 0 else "short"
            deepcoin_client.place_market_order(self.symbol, close_side, pos_side, qty)
            time.sleep(1.0)
            
        # 二次核查，只有真实归零才停止监控并播报
        final_pos = position_manager.get_position(self.symbol)
        if not final_pos or float(final_pos.get("positionAmt", 0)) == 0:
            self.monitoring = False
            self.radar_activated = False
            self.watched_qty = 0.0
            logger.info(f"[全平核查通过] {reason}")
            if reason: dingtalk.report_supervisor_close(reason)
        else:
            dingtalk.report_system_alert("⚠️ 清仓不彻底", f"尝试全平后仍有残留仓位: {final_pos.get('positionAmt')}")

position_supervisor = PositionSupervisor()
