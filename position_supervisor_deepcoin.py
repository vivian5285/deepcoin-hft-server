#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging, time, threading
from deepcoin_client import deepcoin_client
import dingtalk

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Brain: %(message)s')
logger = logging.getLogger(__name__)

class DeepcoinProcessor:
    def __init__(self):
        self.symbol = "ETH-USDT-SWAP"
        self.monitoring = False
        self._lock = threading.Lock()
        
        # 👑 动态资管参数
        self.margin_rate = 0.50     # 动用可用余额的 50%
        self.leverage = 20          # 合约杠杆倍数
        self.face_value = 0.1       # 1张 = 0.1 ETH
        
        # 🛡️ 战术防线参数
        self.tp1_diff = 7.0         # TP1：开仓价 ± 7U
        self.tp2_diff = 15.0        # TP2：开仓价 ± 15U
        self.sl_diff = 20.0         # 全头寸止损：开仓价 ± 20U
        
        self.watched_qty = 0
        self.watched_entry = 0.0
        self.current_side = None

        logger.info("🧠 智慧大脑 V8.7 启动：动态偶数算仓、市价抢跑、全域自愈已激活！")

    def _calculate_even_contracts(self):
        """算法：根据余额计算最大可开张数，并强制向下取偶数"""
        balance = deepcoin_client.get_available_balance()
        curr_px = deepcoin_client.get_current_price(self.symbol)
        if balance <= 0 or curr_px <= 0: return 0, balance
        
        # 计算理论最大张数
        margin_to_use = balance * self.margin_rate
        notional_value = margin_to_use * self.leverage
        raw_qty = int(notional_value / (curr_px * self.face_value))
        
        # 强制舍弃单数，向下取偶（确保能被2整除）
        even_qty = raw_qty if raw_qty % 2 == 0 else raw_qty - 1
        return even_qty, balance

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        if not action: return

        with self._lock: self.monitoring = False 
        
        if action == "CLOSE":
            self._close_all("接收到全平指令，撤单清仓")
            return

        if action in ["LONG", "SHORT"]:
            logger.info(f"📡 接收 {action} 信号，战前清场！")
            self._close_all(f"新兵入场 {action}，旧阵地彻底销毁")
            time.sleep(1) 

            # 自动核算偶数头寸
            target_qty, balance = self._calculate_even_contracts()
            if target_qty < 2:
                dingtalk.report_system_alert("可用弹药不足", f"当前余额 {balance:.2f}U 不足以开出最小偶数(2张)，放弃本次战机。")
                return
            
            logger.info(f"🐺 动态核算完毕：可用 {balance:.2f}U，执行市价抢跑 {target_qty} 张 {action}")
            deepcoin_client.place_market_order(self.symbol, action, target_qty)
            
            # 等待交易所撮合，获取真实成交价
            time.sleep(2)
            pos = self._get_active_position()
            if pos and pos['size'] > 0:
                self.current_side = action
                self._protect_and_monitor(pos['size'], pos['entry_price'])
            else:
                logger.error("🚨 抢跑失败或滑点脱靶！")

    def _protect_and_monitor(self, qty, entry_price):
        tp1_px, tp2_px, sl_px = self._calc_tp_sl(entry_price)
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        
        # 对半切割挂双阶止盈
        qty_tp1 = int(qty / 2)
        qty_tp2 = qty - qty_tp1

        deepcoin_client.place_limit_order(self.symbol, close_side, tp1_px, qty_tp1, is_close=True)
        if qty_tp2 > 0:
            deepcoin_client.place_limit_order(self.symbol, close_side, tp2_px, qty_tp2, is_close=True)
            
        deepcoin_client.place_conditional_order(self.symbol, close_side, sl_px, qty)
        dingtalk.report_deepcoin_open(self.current_side, entry_price, qty, tp1_px, tp2_px, sl_px)
        
        with self._lock:
            self.watched_qty = qty
            self.watched_entry = entry_price
            self.monitoring = True
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _calc_tp_sl(self, entry_price):
        if self.current_side == "LONG":
            return entry_price + self.tp1_diff, entry_price + self.tp2_diff, entry_price - self.sl_diff
        else:
            return entry_price - self.tp1_diff, entry_price - self.tp2_diff, entry_price + self.sl_diff

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                pos = self._get_active_position()
                actual_qty = int(pos['size']) if pos else 0
                
                if actual_qty == 0:
                    logger.info("✨ 阵地已归零，清理防线废单。")
                    self._close_all("系统检测到空仓，重置清理残留挂单")
                    break
                    
                actual_entry = pos['entry_price']
                
                if actual_qty != self.watched_qty or abs(actual_entry - self.watched_entry) > 0.5:
                    logger.warning("⚠️ 察觉持仓异动或部分止盈！重新组装防线！")
                    deepcoin_client.cancel_all_open_orders(self.symbol)
                    time.sleep(1)
                    
                    with self._lock:
                        self.watched_qty = actual_qty
                        self.watched_entry = actual_entry
                        
                    tp1_px, tp2_px, sl_px = self._calc_tp_sl(actual_entry)
                    close_side = "SHORT" if self.current_side == "LONG" else "LONG"
                    
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
                if size > 0: return {"size": size, "entry_price": float(p.get("avgPx", p.get("price", 0)))}
        return None

    def _close_all(self, reason: str):
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        deepcoin_client.close_all_positions(self.symbol)
        with self._lock: self.monitoring = False
        if reason: dingtalk.report_deepcoin_clear(reason)

deepcoin_processor = DeepcoinProcessor()
