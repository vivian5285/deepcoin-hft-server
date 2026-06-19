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
        
        # 👑 核心战术参数
        self.standard_hand = 2      # “永远一手”的定义：每次开 2 张（为了方便分批止盈）
        self.tp1_diff = 7.0         # TP1：开仓价 ± 7U
        self.tp2_diff = 15.0        # TP2：开仓价 ± 15U
        self.sl_diff = 20.0         # 全头寸止损：开仓价 ± 20U
        
        self.watched_qty = 0
        self.watched_entry = 0.0
        self.current_side = None

        logger.info("🧠 智慧大脑 V8.6 已启动：双阶止盈(7/15)、铁血止损(20)与反干预自愈就绪！")

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        if not action: return

        # 1. 信号洁癖：新TV信号到达，必须先撤单再全平，保持头寸绝对干净
        with self._lock: self.monitoring = False 
        
        if action == "CLOSE":
            self._close_all("接收到大脑主控全平指令")
            return

        if action in ["LONG", "SHORT"]:
            logger.info(f"📡 接收新信号 {action}，执行战前清场！")
            self._close_all(f"新指令 {action} 入场，清除旧阵地残余")
            time.sleep(1) # 等待交易所结算

            # 2. 永远开一手：保持阵地纯净，同向不加，反向重开
            current_px = deepcoin_client.get_current_price(self.symbol)
            if current_px <= 0: return
            
            logger.info(f"🐺 执行绝对单向开仓：方向 {action}，标准头寸 {self.standard_hand}张")
            deepcoin_client.place_limit_order(self.symbol, action, current_px, self.standard_hand)
            
            # 等待成交并布防
            time.sleep(2)
            pos = self._get_active_position()
            if pos and pos['size'] > 0:
                self.current_side = action
                self._protect_and_monitor(pos['size'], pos['entry_price'])
            else:
                logger.error("🚨 开仓未成交或盘口滑点过大！")

    def _protect_and_monitor(self, qty, entry_price):
        """部署双阶止盈与全头寸止损防线"""
        tp1_px, tp2_px, sl_px = self._calc_tp_sl(entry_price)
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        
        # 拆分仓位用于双阶止盈
        qty_tp1 = max(1, int(qty / 2))
        qty_tp2 = int(qty - qty_tp1)

        # 挂止盈限价单
        deepcoin_client.place_limit_order(self.symbol, close_side, tp1_px, qty_tp1, is_close=True)
        if qty_tp2 > 0:
            deepcoin_client.place_limit_order(self.symbol, close_side, tp2_px, qty_tp2, is_close=True)
            
        # 挂止损条件单 (全头寸统一止损)
        deepcoin_client.place_conditional_order(self.symbol, close_side, sl_px, qty)
        
        dingtalk.report_deepcoin_open(self.current_side, entry_price, qty, tp1_px, tp2_px, sl_px)
        
        # 启动防干预巡更自查
        with self._lock:
            self.watched_qty = qty
            self.watched_entry = entry_price
            self.monitoring = True
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _calc_tp_sl(self, entry_price):
        """核心算法：计算绝对价差止盈止损"""
        if self.current_side == "LONG":
            return entry_price + self.tp1_diff, entry_price + self.tp2_diff, entry_price - self.sl_diff
        else:
            return entry_price - self.tp1_diff, entry_price - self.tp2_diff, entry_price + self.sl_diff

    def _sentinel_loop(self):
        """全域自审自查：防人工干预与自动自愈"""
        while self.monitoring:
            try:
                pos = self._get_active_position()
                actual_qty = int(pos['size']) if pos else 0
                
                # 场景 1：碰触止盈/止损，或手动全平导致仓位归零
                if actual_qty == 0:
                    logger.info("✨ 发现阵地为空！自动清理残留废单。")
                    self._close_all("系统检测到空仓，重置清理残留挂单")
                    break
                    
                actual_entry = pos['entry_price']
                
                # 场景 2：发生人工干预 (加减仓或只触发了TP1)
                if actual_qty != self.watched_qty or abs(actual_entry - self.watched_entry) > 0.5:
                    logger.warning(f"⚠️ 察觉持仓异动或部分止盈！启动防线重装机制！")
                    
                    # 撤销所有旧挂单
                    deepcoin_client.cancel_all_open_orders(self.symbol)
                    time.sleep(1)
                    
                    with self._lock:
                        self.watched_qty = actual_qty
                        self.watched_entry = actual_entry
                        
                    # 以新的张数和均价重新计算并挂单
                    tp1_px, tp2_px, sl_px = self._calc_tp_sl(actual_entry)
                    close_side = "SHORT" if self.current_side == "LONG" else "LONG"
                    
                    # 此时如果有零头，统一挂最高级别的止盈
                    deepcoin_client.place_limit_order(self.symbol, close_side, tp2_px, actual_qty, is_close=True)
                    deepcoin_client.place_conditional_order(self.symbol, close_side, sl_px, actual_qty)
                    
                    dingtalk.report_intervention(actual_qty, actual_entry, tp2_px, sl_px)

            except Exception as e:
                logger.error(f"哨兵轮询出错: {e}")
            time.sleep(3)

    def _get_active_position(self) -> dict:
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                size = float(p.get("pos", 0))
                if size > 0:
                    return {"size": size, "entry_price": float(p.get("avgPx", p.get("price", 0)))}
        return None

    def _close_all(self, reason: str):
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        deepcoin_client.close_all_positions(self.symbol)
        with self._lock: self.monitoring = False
        if reason: dingtalk.report_deepcoin_clear(reason)

deepcoin_processor = DeepcoinProcessor()
