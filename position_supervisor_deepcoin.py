#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging, time, threading, os
from logging.handlers import RotatingFileHandler
from deepcoin_client import deepcoin_client
import dingtalk

if not os.path.exists('logs'): os.makedirs('logs')
handler = RotatingFileHandler('logs/deepcoin_brain.log', maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Brain: %(message)s', handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)

class DeepcoinProcessor:
    def __init__(self):
        self.symbol = "ETH-USDT-SWAP"
        self.monitoring = False
        self._lock = threading.Lock()
        
        self.margin_rate = 0.50
        self.leverage = 20
        self.face_value = 0.1
        
        # 👑 战术防线：7/15 止盈，30 绝对价差止损
        self.tp1_diff = 7.0
        self.tp2_diff = 15.0
        self.sl_diff = 30.0  # 统一提升至 30 美金抗震价差
        
        self.watched_qty = 0
        self.watched_entry = 0.0
        self.current_side = None

        logger.info("🧠 深币 V9.1 启动：轮询探针、并发锁、5U让步、30美金止损、全域自愈激活！")

    def _calculate_even_contracts(self):
        balance = deepcoin_client.get_available_balance()
        curr_px = deepcoin_client.get_current_price(self.symbol)
        if balance <= 0 or curr_px <= 0: return 0, balance
        
        raw_qty = int((balance * self.margin_rate * self.leverage) / (curr_px * self.face_value))
        return raw_qty if raw_qty % 2 == 0 else raw_qty - 1, balance

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        if not action: return

        if not self._lock.acquire(blocking=False): return
            
        try:
            self.monitoring = False 
            if action == "CLOSE":
                self._close_all("接收到全平指令，撤单清仓")
                return

            if action in ["LONG", "SHORT"]:
                self._close_all(f"新兵入场 {action}，旧阵地彻底销毁")
                
                target_qty, balance = self._calculate_even_contracts()
                if target_qty < 2: return
                
                logger.info(f"🐺 动态核算完毕：可用 {balance:.2f}U，抢跑 {target_qty} 张 {action}")
                
                for attempt in range(3):
                    res = deepcoin_client.place_market_order(self.symbol, action, target_qty)
                    if res and str(res.get("code")) == "0": break
                    time.sleep(0.5)
                
                pos = None
                for _ in range(5):
                    time.sleep(1)
                    pos = self._get_active_position()
                    if pos and pos['size'] > 0: break

                if pos and pos['size'] > 0:
                    self.current_side = action
                    self._protect_and_monitor(pos['size'], pos['entry_price'])
                else:
                    logger.error("🚨 抢跑失败或 REST API 缓存延迟！")
        finally:
            self._lock.release()

    def _calc_tp_sl(self, entry_price):
        if self.current_side == "LONG":
            return entry_price + self.tp1_diff, entry_price + self.tp2_diff, entry_price - self.sl_diff
        else:
            return entry_price - self.tp1_diff, entry_price - self.tp2_diff, entry_price + self.sl_diff

    def _protect_and_monitor(self, qty, entry_price):
        tp1_px, tp2_px, sl_px = self._calc_tp_sl(entry_price)
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        qty_tp1 = int(qty / 2)
        qty_tp2 = qty - qty_tp1

        deepcoin_client.place_limit_order(self.symbol, close_side, tp1_px, qty_tp1, is_close=True)
        if qty_tp2 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, tp2_px, qty_tp2, is_close=True)
        deepcoin_client.place_conditional_order(self.symbol, close_side, sl_px, qty)
        
        dingtalk.report_deepcoin_open(self.current_side, entry_price, qty, tp1_px, tp2_px, sl_px)
        
        self.watched_qty = qty
        self.watched_entry = entry_price
        self.monitoring = True
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                pos = self._get_active_position()
                actual_qty = int(pos['size']) if pos else 0
                if actual_qty == 0:
                    self._close_all("系统检测到空仓，重置清理残留挂单")
                    break
                    
                actual_entry = pos['entry_price']
                actual_side = pos.get('posSide', '').upper()
                if not actual_side: actual_side = "LONG" if actual_qty > 0 else "SHORT"

                if actual_side != self.current_side and actual_side in ["LONG", "SHORT"]:
                    self._close_all("强行对齐：抹杀与信号相悖的仓位")
                    dingtalk.report_force_align(actual_side, self.current_side)
                    break
                
                if actual_qty != self.watched_qty or abs(actual_entry - self.watched_entry) > 0.5:
                    deepcoin_client.cancel_all_open_orders(self.symbol)
                    time.sleep(1)
                    with self._lock:
                        self.watched_qty = actual_qty
                        self.watched_entry = actual_entry
                        
                    tp1_px, tp2_px, sl_px = self._calc_tp_sl(actual_entry)
                    close_side = "SHORT" if self.current_side == "LONG" else "LONG"
                    
                    # 自愈机制：剩余头寸全数挂最高止盈 (15价差)
                    deepcoin_client.place_limit_order(self.symbol, close_side, tp2_px, actual_qty, is_close=True)
                    deepcoin_client.place_conditional_order(self.symbol, close_side, sl_px, actual_qty)
                    dingtalk.report_intervention(actual_qty, actual_entry, tp2_px, sl_px)

            except Exception as e: logger.error(f"哨兵出错: {e}")
            time.sleep(3)

    def _get_active_position(self) -> dict:
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                size = float(p.get("pos", 0))
                if size > 0: return {"size": size, "entry_price": float(p.get("avgPx", p.get("price", 0))), "posSide": p.get("posSide", "")}
        return None

    def _close_all(self, reason: str):
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        deepcoin_client.close_all_positions(self.symbol)
        self.monitoring = False
        if reason: dingtalk.report_deepcoin_clear(reason)

deepcoin_processor = DeepcoinProcessor()
