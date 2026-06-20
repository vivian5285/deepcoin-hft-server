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
        
        # 🚀 V10.29 核心修复：完美对齐 TV 的 10/30/60 网格切割比例
        self.tp_ratios = [0.10, 0.30, 0.60]
        
        self.tp1_mult = 1.28
        self.tp2_mult = 2.45
        self.tp3_mult = 3.45
        self.sl_mult = 1.03
        self.current_trail_factor = 0.50 
        self.current_atr = 30.0
        
        # V10.29 理论价格透传缓存
        self.tv_price = 0.0
        self.tv_tp1 = 0.0
        self.tv_tp2 = 0.0
        self.tv_tp3 = 0.0
        self.tv_sl = 0.0
        
        self.initial_qty = 0.0
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_side = None
        self.best_price = 0.0
        self.current_sl = 0.0

        logger.info("🧠 深币 V10.29 完美对齐大脑加载完毕：全量接收 TV 理论数据！")

    def _calculate_contracts(self, curr_px, balance):
        return int((balance * self.margin_rate * self.leverage) / (curr_px * self.face_value))

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        
        # 🚀 V10.29 全域 JSON 解析 (囊括真实倍数与理论绝对价)
        self.tv_price = float(payload.get("price", 0.0))
        self.current_atr = float(payload.get("atr", 30.0))
        self.tp1_mult = float(payload.get("tp1_m", 1.28))
        self.tp2_mult = float(payload.get("tp2_m", 2.45))
        self.tp3_mult = float(payload.get("tp3_m", 3.45))
        self.sl_mult  = float(payload.get("sl_m", 1.03)) 
        self.current_trail_factor = float(payload.get("trail_factor", 0.50)) 
        
        self.tv_tp1 = float(payload.get("tv_tp1", 0.0))
        self.tv_tp2 = float(payload.get("tv_tp2", 0.0))
        self.tv_tp3 = float(payload.get("tv_tp3", 0.0))
        self.tv_sl  = float(payload.get("tv_sl", 0.0))
        
        if not action: return
        if not self._lock.acquire(blocking=False): return
            
        try:
            self.monitoring = False 
            # 🚀 V10.29 最高指令：TV 下发 CLOSE，无条件全平清场
            if action == "CLOSE":
                self._close_all("终极兜底防线：TV 图表已清仓，深币实盘强制对齐！")
                return

            if action in ["LONG", "SHORT"]:
                curr_px = deepcoin_client.get_current_price(self.symbol)
                balance = deepcoin_client.get_available_balance()
                if balance <= 0 or curr_px <= 0: return

                if self.tv_price > 0 and abs(curr_px - self.tv_price) > 5.0:
                    dingtalk.report_system_alert("防追高拦截", f"偏差过大: 现价 {curr_px} vs TV {self.tv_price}")
                    return

                old_pos = self._get_active_position()
                old_qty = int(old_pos['size']) if old_pos else 0

                self._close_all(f"新战局启动 {action}")
                
                target_qty = self._calculate_contracts(curr_px, balance)
                if target_qty < 1: return 
                
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
                    # 把实际抢到的均价传给排兵布阵函数
                    self._protect_and_monitor(pos['size'], pos['entry_price'], old_qty)
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

    def _protect_and_monitor(self, qty, entry_price, old_qty=0):
        tp1_px, tp2_px, tp3_px, sl_px = self._calc_tp_sl(entry_price)
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"
        
        qty1 = int(qty * self.tp_ratios[0])
        qty2 = int(qty * self.tp_ratios[1])
        qty3 = int(qty - qty1 - qty2)

        if qty1 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp1_px, qty1)
        if qty2 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp2_px, qty2)
        if qty3 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp3_px, qty3)
        deepcoin_client.place_conditional_order(self.symbol, close_side, pos_side, sl_px, qty)
        
        self.best_price = entry_price
        self.current_sl = sl_px

        # 🚀 带着 TV 的理论绝对价格，去钉钉战报里“照妖镜”对比滑点
        dingtalk.report_deepcoin_open(
            self.current_side, entry_price, qty, 
            [tp1_px, tp2_px, tp3_px], sl_px, self.current_atr, old_qty,
            self.tv_price, [self.tv_tp1, self.tv_tp2, self.tv_tp3], self.tv_sl
        )
        
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
                
                curr_px = deepcoin_client.get_current_price(self.symbol)
                if self.current_side == "LONG": self.best_price = max(self.best_price, curr_px)
                else: self.best_price = min(self.best_price, curr_px)

                trail_offset = self.current_atr * self.current_trail_factor * 0.45 
                # 🚀 适配 10/30/60：一旦前 10% 或 30% 被吃掉，防线立刻启动绝对保本
                is_breakeven = actual_qty < (self.initial_qty * 0.95)

                if is_breakeven:
                    close_side = "sell" if self.current_side == "LONG" else "buy"
                    pos_side = "long" if self.current_side == "LONG" else "short"
                    
                    if self.current_side == "LONG":
                        calculated_sl = round(self.best_price - trail_offset, 2)
                        new_sl = max(calculated_sl, self.watched_entry, self.current_sl)
                        
                        if new_sl - self.current_sl > 2.0:
                            deepcoin_client.cancel_all_open_orders(self.symbol)
                            time.sleep(0.5)
                            self.current_sl = new_sl
                            _, _, tp3_px, _ = self._calc_tp_sl(actual_entry)
                            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp3_px, actual_qty)
                            deepcoin_client.place_conditional_order(self.symbol, close_side, pos_side, new_sl, actual_qty)
                            dingtalk.report_intervention(actual_qty, actual_entry, tp3_px, new_sl, "🚀 追踪止盈：防线向前推进，绝对保本！")
                            
                    else:
                        calculated_sl = round(self.best_price + trail_offset, 2)
                        new_sl = min(calculated_sl, self.watched_entry, self.current_sl)
                        
                        if self.current_sl - new_sl > 2.0:
                            deepcoin_client.cancel_all_open_orders(self.symbol)
                            time.sleep(0.5)
                            self.current_sl = new_sl
                            _, _, tp3_px, _ = self._calc_tp_sl(actual_entry)
                            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp3_px, actual_qty)
                            deepcoin_client.place_conditional_order(self.symbol, close_side, pos_side, new_sl, actual_qty)
                            dingtalk.report_intervention(actual_qty, actual_entry, tp3_px, new_sl, "🚀 追踪止盈：防线向下推进，绝对保本！")
                
                elif abs(actual_qty - self.watched_qty) > 0.001 or abs(actual_entry - self.watched_entry) > 0.5:
                    deepcoin_client.cancel_all_open_orders(self.symbol)
                    time.sleep(1)
                    with self._lock:
                        self.watched_qty, self.watched_entry = actual_qty, actual_entry
                        
                    _, _, tp3_px, original_sl_px = self._calc_tp_sl(actual_entry)
                    close_side = "sell" if self.current_side == "LONG" else "buy"
                    pos_side = "long" if self.current_side == "LONG" else "short"
                    
                    sl_safe = round(actual_entry, 2) if is_breakeven else original_sl_px
                    deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp3_px, actual_qty)
                    deepcoin_client.place_conditional_order(self.symbol, close_side, pos_side, sl_safe, actual_qty)
                    dingtalk.report_intervention(actual_qty, actual_entry, tp3_px, sl_safe, "已触发异常自愈重装")

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
        
        max_retries = 8
        for i in range(max_retries):
            deepcoin_client.close_all_positions(self.symbol)
            time.sleep(0.8) 
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0:
                break 
            logger.warning(f"⚠️ 第 {i+1} 次平仓后底仓仍未归零，继续轰炸！")
            
        self.monitoring = False
        if reason: dingtalk.report_deepcoin_clear(reason)

deepcoin_processor = DeepcoinProcessor()
