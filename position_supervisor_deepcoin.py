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
        
        self.margin_rate = 0.30
        self.leverage = 10
        self.face_value = 0.1
        
        self.tp_ratios = [0.30, 0.30, 0.40]
        self.tp1_mult = 1.28
        self.tp2_mult = 2.50
        self.tp3_mult = 3.60
        self.sl_mult = 0.92
        
        self.initial_qty = 0.0
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_side = None
        self.current_atr = 30.0

        logger.info("🧠 深币 V10 启动：官方最新API对齐、30%资金/10X测试就绪！")

    def _calculate_contracts(self, curr_px, balance):
        raw_qty = int((balance * self.margin_rate * self.leverage) / (curr_px * self.face_value))
        return raw_qty

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        tv_price = float(payload.get("price", 0.0))
        self.current_atr = float(payload.get("atr", 30.0))
        
        if not action: return
        if not self._lock.acquire(blocking=False): return
            
        try:
            self.monitoring = False 
            if action == "CLOSE":
                self._close_all("接收到全平指令，撤单清仓")
                return

            if action in ["LONG", "SHORT"]:
                curr_px = deepcoin_client.get_current_price(self.symbol)
                balance = deepcoin_client.get_available_balance()
                if balance <= 0 or curr_px <= 0: return

                if tv_price > 0 and abs(curr_px - tv_price) > 5.0:
                    dingtalk.report_system_alert("滑点拦截", f"偏差 {abs(curr_px - tv_price):.2f} U")
                    return

                self._close_all(f"新兵入场 {action}")
                
                target_qty = self._calculate_contracts(curr_px, balance)
                if target_qty < 1: return 
                
                # 🚨 严格区分开仓方向
                open_side = "buy" if action == "LONG" else "sell"
                open_pos_side = "long" if action == "LONG" else "short"

                for attempt in range(3):
                    res = deepcoin_client.place_market_order(self.symbol, open_side, open_pos_side, target_qty)
                    if res and str(res.get("code")) == "0": break
                    time.sleep(0.5)
                
                pos = None
                for _ in range(5):
                    time.sleep(1)
                    pos = self._get_active_position()
                    if pos and pos['size'] > 0: break

                if pos and pos['size'] > 0:
                    self.current_side = action
                    self.initial_qty = pos['size']
                    self._protect_and_monitor(pos['size'], pos['entry_price'])
        finally:
            self._lock.release()

    def _calc_tp_sl(self, entry_price):
        if self.current_side == "LONG":
            return (round(entry_price + self.current_atr * self.tp1_mult, 2), 
                    round(entry_price + self.current_atr * self.tp2_mult, 2), 
                    round(entry_price + self.current_atr * self.tp3_mult, 2), 
                    round(entry_price - self.current_atr * self.sl_mult, 2))
        else:
            return (round(entry_price - self.current_atr * self.tp1_mult, 2), 
                    round(entry_price - self.current_atr * self.tp2_mult, 2), 
                    round(entry_price - self.current_atr * self.tp3_mult, 2), 
                    round(entry_price + self.current_atr * self.sl_mult, 2))

    def _protect_and_monitor(self, qty, entry_price):
        tp1_px, tp2_px, tp3_px, sl_px = self._calc_tp_sl(entry_price)
        
        # 🚨 严格区分平仓方向：平多=卖出(sell)+多头(long)，平空=买入(buy)+空头(short)
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"
        
        qty1 = int(qty * self.tp_ratios[0])
        qty2 = int(qty * self.tp_ratios[1])
        qty3 = int(qty - qty1 - qty2)

        if qty1 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp1_px, qty1)
        if qty2 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp2_px, qty2)
        if qty3 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp3_px, qty3)
        
        deepcoin_client.place_conditional_order(self.symbol, close_side, pos_side, sl_px, qty)
        
        dingtalk.report_deepcoin_open(self.current_side, entry_price, qty, [tp1_px, tp2_px, tp3_px], sl_px, self.current_atr)
        self.watched_qty, self.watched_entry, self.monitoring = qty, entry_price, True
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                pos = self._get_active_position()
                actual_qty = int(pos['size']) if pos else 0
                if actual_qty == 0: self._close_all("空仓清场"); break
                    
                actual_entry = pos['entry_price']
                actual_side = pos.get('posSide', '').upper()
                if not actual_side: actual_side = "LONG" if actual_qty > 0 else "SHORT"

                if actual_side != self.current_side and actual_side in ["LONG", "SHORT"]:
                    self._close_all("强行对齐")
                    dingtalk.report_force_align(actual_side, self.current_side)
                    break
                
                if actual_qty != self.watched_qty or abs(actual_entry - self.watched_entry) > 0.5:
                    deepcoin_client.cancel_all_open_orders(self.symbol)
                    time.sleep(1)
                    with self._lock:
                        self.watched_qty, self.watched_entry = actual_qty, actual_entry
                        
                    _, _, tp3_px, original_sl_px = self._calc_tp_sl(actual_entry)
                    
                    close_side = "sell" if self.current_side == "LONG" else "buy"
                    pos_side = "long" if self.current_side == "LONG" else "short"
                    
                    is_breakeven = actual_qty < (self.initial_qty * 0.8)
                    sl_safe = round(actual_entry, 2) if is_breakeven else original_sl_px
                    
                    deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp3_px, actual_qty)
                    deepcoin_client.place_conditional_order(self.symbol, close_side, pos_side, sl_safe, actual_qty)
                    
                    action_msg = "已提损至保本" if is_breakeven else "维持标准防线"
                    dingtalk.report_intervention(actual_qty, actual_entry, tp3_px, sl_safe, action_msg)

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
