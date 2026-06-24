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
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] DeepcoinBrain: %(message)s', handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)

class PositionSupervisor:
    def __init__(self):
        self.symbol = "ETHUSDT"
        self.monitoring = False
        self._lock = threading.Lock()

        # 第一重目标：覆盖手续费 + 保本（可根据实盘微调）
        self.fee_cover_margin = 0.0014          # 0.14%
        self.radar_activated = False

        self.current_side = None
        self.last_tv_side = None
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_sl = 0.0
        self.tv_tp1 = 0.0
        self.fee_cover_price = 0.0

        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [两道平仓 + 雷达保本版] 已加载")

    def _save_state(self):
        state = {
            "last_tv_side": self.last_tv_side,
            "current_side": self.current_side,
            "watched_qty": self.watched_qty,
            "watched_entry": self.watched_entry,
            "current_sl": self.current_sl,
            "radar_activated": self.radar_activated
        }
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
        except: pass

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        self.tv_tp1 = float(payload.get("tv_tp1", 0.0))

        if not raw_action: return
        if not self._lock.acquire(blocking=False): return

        try:
            self.monitoring = False
            self.radar_activated = False

            # 新信号到达 → 先全平 + 撤单
            if raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                deepcoin_client.cancel_all_open_orders()
                time.sleep(0.5)
                self._close_all("新方向到达，先全平再开仓")
                time.sleep(0.8)

                curr_px = deepcoin_client.get_current_price(self.symbol)
                balance = deepcoin_client.get_available_balance()

                # 计算第一重目标（覆盖手续费 + 保本）
                if raw_action == "LONG":
                    self.fee_cover_price = curr_px * (1 + self.fee_cover_margin)
                else:
                    self.fee_cover_price = curr_px * (1 - self.fee_cover_margin)

                # 下单（永远一手）
                qty = self._calc_qty(curr_px)
                deepcoin_client.place_market_order(raw_action, qty)
                time.sleep(2)

                pos = position_manager.get_position(self.symbol)
                if pos and float(pos.get("positionAmt", 0)) != 0:
                    self.current_side = raw_action
                    self.watched_qty = abs(float(pos["positionAmt"]))
                    self.watched_entry = float(pos["entryPrice"])
                    self.current_sl = self.watched_entry
                    self._start_monitor()

        finally:
            self._lock.release()

    def _calc_qty(self, price):
        # 简单仓位计算（可后续根据四档位优化）
        balance = deepcoin_client.get_available_balance()
        return round(balance * 0.25 / price, 3)   # 示例：使用25%资金

    def _start_monitor(self):
        self.monitoring = True
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                pos = position_manager.get_position(self.symbol)
                if not pos or float(pos.get("positionAmt", 0)) == 0:
                    self.monitoring = False
                    break

                curr_px = deepcoin_client.get_current_price(self.symbol)
                remaining_qty = abs(float(pos.get("positionAmt", 0)))

                # === 第一重：到达覆盖手续费 + 保本位 ===
                reached_fee_cover = False
                if self.current_side == "LONG" and curr_px >= self.fee_cover_price:
                    reached_fee_cover = True
                elif self.current_side == "SHORT" and curr_px <= self.fee_cover_price:
                    reached_fee_cover = True

                if reached_fee_cover and not self.radar_activated:
                    # 启动雷达 + 把止损移到保本位
                    self.current_sl = self.fee_cover_price
                    self.radar_activated = True
                    logger.info(f"[雷达启动] 已到达保本位，止损移至 {self.fee_cover_price}")

                    # 如果还有剩余头寸，把止盈挂到 TV 的 tp1
                    if remaining_qty > 0 and self.tv_tp1 > 0:
                        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
                        deepcoin_client.place_limit_order(close_side, remaining_qty, self.tv_tp1, reduce_only=True)
                        logger.info(f"[切换止盈] 剩余仓位止盈已挂到 TV tp1: {self.tv_tp1}")

                # === 雷达移动保本止损 ===
                if self.radar_activated:
                    # 简单雷达逻辑：价格有利时逐步上移止损
                    if self.current_side == "LONG":
                        new_sl = max(self.current_sl, curr_px * 0.995)   # 示例：每上涨0.5%上移止损
                        if new_sl > self.current_sl + 1:
                            self.current_sl = new_sl
                    else:
                        new_sl = min(self.current_sl, curr_px * 1.005)
                        if new_sl < self.current_sl - 1:
                            self.current_sl = new_sl

                # 更新止损单（简化版）
                if self.radar_activated:
                    deepcoin_client.cancel_all_open_orders()
                    time.sleep(0.3)
                    close_side = "SHORT" if self.current_side == "LONG" else "LONG"
                    deepcoin_client.place_stop_market_order(close_side, self.current_sl)

            except Exception as e:
                logger.error(f"哨兵异常: {e}")
            time.sleep(4)

    def _close_all(self, reason=""):
        deepcoin_client.cancel_all_open_orders()
        time.sleep(0.5)
        deepcoin_client.close_all_positions()
        self.monitoring = False
        self.radar_activated = False
        self.watched_qty = 0.0
        logger.info(f"[全平] {reason}")

# 全局实例
position_supervisor = PositionSupervisor()
