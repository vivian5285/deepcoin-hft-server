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
        
        self.face_value = 0.1         # 1张 = 0.1 ETH
        self.target_net_profit = 3.0  # 止盈目标 3U
        self.max_loss_usd = 20.0      # 止损铁律 20U 全头寸
        self.fee_rate = 0.0006        # 手续费率
        self.always_one_hand = 1      # 永远一手
        
        self.watched_qty = 0
        self.watched_entry = 0.0
        self.current_side = None

        logger.info("🧠 智慧大脑 V8.5 已启动：开启单向一手、双向限价与反干预自愈！")

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        if not action: return

        # 1. 信号洁癖：收到任何新信号，先撤单再全平，保持头寸绝对干净
        with self._lock:
            self.monitoring = False 
        
        if action == "CLOSE":
            self._close_all("接收到大脑主控全平指令")
            return

        if action in ["LONG", "SHORT"]:
            logger.info(f"📡 接收新信号 {action}，执行战前清场！")
            self._close_all(f"新指令 {action} 入场，清除旧阵地残余")
            time.sleep(1) # 等待交易所结算

            # 2. 开仓：永远只开一手 (市价抢入或极速限价)
            current_px = deepcoin_client.get_current_price(self.symbol)
            if current_px <= 0: return
            
            logger.info(f"🐺 执行绝对单向开仓：方向 {action}，头寸 {self.always_one_hand}张")
            deepcoin_client.place_limit_order(self.symbol, action, current_px, self.always_one_hand)
            
            # 等待成交
            time.sleep(2)
            pos = self._get_active_position()
            if pos and pos['size'] > 0:
                self.current_side = action
                self._protect_and_monitor(pos['size'], pos['entry_price'])
            else:
                logger.error("🚨 开仓未成交或盘口滑点过大！")

    def _protect_and_monitor(self, qty, entry_price):
        """部署双向防线并启动雷达"""
        tp_px, sl_px = self._calc_tp_sl(qty, entry_price)
        
        # 挂止盈限价单
        close_side = "SHORT" if self.current_side == "LONG" else "LONG"
        deepcoin_client.place_limit_order(self.symbol, close_side, tp_px, qty, is_close=True)
        # 挂止损条件单 (如果交易所限制，哨兵也会进行软止损)
        deepcoin_client.place_conditional_order(self.symbol, close_side, sl_px, qty)
        
        dingtalk.report_deepcoin_open(self.current_side, entry_price, qty, tp_px, sl_px)
        
        # 启动防干预巡更
        with self._lock:
            self.watched_qty = qty
            self.watched_entry = entry_price
            self.monitoring = True
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _calc_tp_sl(self, qty, entry_price):
        """计算止盈止损价格"""
        notional = entry_price * qty * self.face_value
        est_fee = notional * self.fee_rate * 2
        
        # 止盈 3U 对应价差
        tp_diff = (self.target_net_profit + est_fee) / (qty * self.face_value)
        # 止损 20U 对应价差
        sl_diff = self.max_loss_usd / (qty * self.face_value)
        
        if self.current_side == "LONG":
            return entry_price + tp_diff, entry_price - sl_diff
        else:
            return entry_price - tp_diff, entry_price + sl_diff

    def _sentinel_loop(self):
        """哨兵巡更：防人工干预与自动自愈"""
        logger.info("👀 防御哨兵已升空，每 3 秒核实一次阵地数据...")
        while self.monitoring:
            try:
                pos = self._get_active_position()
                actual_qty = int(pos['size']) if pos else 0
                
                # 场景 1：完全平仓 (碰触止盈止损，或手动全平)
                if actual_qty == 0:
                    logger.info("✨ 发现阵地为空！已触达防线或被手动清空。")
                    self._close_all("系统检测到空仓，重置清理残留挂单")
                    break
                    
                actual_entry = pos['entry_price']
                
                # 场景 2：发生人工干预 (加减仓导致张数或均价偏移)
                if actual_qty != self.watched_qty or abs(actual_entry - self.watched_entry) > 0.5:
                    logger.warning(f"⚠️ 察觉持仓异动！原={self.watched_qty}张，现={actual_qty}张。启动防线重装机制！")
                    
                    # 1. 撤销旧防线
                    deepcoin_client.cancel_all_open_orders(self.symbol)
                    time.sleep(1)
                    
                    # 2. 更新记忆并重新布防
                    with self._lock:
                        self.watched_qty = actual_qty
                        self.watched_entry = actual_entry
                        
                    tp_px, sl_px = self._calc_tp_sl(actual_qty, actual_entry)
                    close_side = "SHORT" if self.current_side == "LONG" else "LONG"
                    
                    deepcoin_client.place_limit_order(self.symbol, close_side, tp_px, actual_qty, is_close=True)
                    deepcoin_client.place_conditional_order(self.symbol, close_side, sl_px, actual_qty)
                    
                    dingtalk.report_intervention(actual_qty, actual_entry, tp_px, sl_px)

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
        if reason:
            dingtalk.report_deepcoin_clear(reason)

deepcoin_processor = DeepcoinProcessor()
