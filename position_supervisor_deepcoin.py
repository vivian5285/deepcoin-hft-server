#!/usr/bin/env python3
# position_supervisor_deepcoin.py（Deepcoin V8.0 限价刺客与哨兵巡更版）
import logging
import time
import threading
from deepcoin_client import deepcoin_client
import dingtalk

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] DeepcoinSupervisor: %(message)s')
logger = logging.getLogger(__name__)

class DeepcoinProcessor:
    def __init__(self):
        self.leverage = 20
        self.symbol = "ETH-USDT-SWAP"
        self.face_value = 0.1  # 深币 ETH 面值
        
        # 哨兵状态管理
        self.sentinel_thread = None
        self.monitoring = False
        self.watched_side = None
        self.watched_qty = 0
        self._lock = threading.Lock()
        
        logger.info("🟢 [Deepcoin] V8.0 刺客引擎就绪：开仓即挂 7U/15U 限价防线！")

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        if not action: return

        if action == "CLOSE":
            self._close_all("接收到 TV 主动平仓信号，执行绝对清场")
            self._stop_sentinel()
            return

        if action in ["LONG", "SHORT"]:
            signal_price = payload.get("price", deepcoin_client.get_current_price(self.symbol))
            logger.info(f"📡 接收到 TV {action} 信号！当前理论锚定预期价: {signal_price}")

            # 1. 强制重置阵地：不管多空，先撤挂单再全平！(保持干净单向一手)
            self._stop_sentinel()
            self._close_all(f"强制重置阵地: 准备执行新方向 {action}")
            
            # 2. 调用三段狙击引擎开仓
            success, entry_price, margin, final_qty = self._execute_escalating_open(action)
            
            if success and final_qty > 0:
                # 3. 计算 7U / 15U 止盈防线
                tp1_qty = int(final_qty * 0.5)
                tp2_qty = final_qty - tp1_qty  # 剩余的全部给 TP2
                
                tp1_price = round(entry_price + 7.0 if action == "LONG" else entry_price - 7.0, 2)
                tp2_price = round(entry_price + 15.0 if action == "LONG" else entry_price - 15.0, 2)
                
                logger.info(f"🛡️ 正在挂载极速限价防线... TP1: {tp1_price}({tp1_qty}张), TP2: {tp2_price}({tp2_qty}张)")
                
                if tp1_qty > 0:
                    deepcoin_client.place_limit_order(self.symbol, action, tp1_price, tp1_qty, is_close=True)
                if tp2_qty > 0:
                    deepcoin_client.place_limit_order(self.symbol, action, tp2_price, tp2_qty, is_close=True)
                
                # 4. 汇报战果并启动哨兵
                tp_dict = {"tp1": tp1_price, "tp2": tp2_price}
                dingtalk.report_deepcoin_open(action, entry_price, final_qty, tp_dict, margin)
                
                self._start_sentinel(action, final_qty)
            else:
                self._report_timeout()

    def _close_all(self, reason: str):
        logger.info(f"🧹 执行清场: {reason}")
        for attempt in range(3):
            deepcoin_client.cancel_all_open_orders(symbol=self.symbol)
            time.sleep(0.5)
            deepcoin_client.close_all_positions(symbol=self.symbol)
            time.sleep(1.0)
            
            if not self._get_active_position():
                if reason: dingtalk.report_deepcoin_clear(reason)
                return
            logger.warning(f"⚠️ 第 {attempt+1} 次清场仍有残余，继续清剿！")

    def _execute_escalating_open(self, action: str):
        balance = deepcoin_client.get_available_balance(ccy="USDT")
        if balance < 10:
            logger.warning("[Deepcoin] 账户余额不足，放弃建仓。")
            return False, 0.0, 0.0, 0
            
        margin = balance * 0.50  # 动用50%本金
        notional_usdt = margin * self.leverage
        
        current_price = deepcoin_client.get_current_price(self.symbol)
        if current_price <= 0: return False, 0.0, 0.0, 0

        total_contracts = int(notional_usdt / (current_price * self.face_value))
        if total_contracts <= 0: return False, 0.0, 0.0, 0

        escalation_steps = [0.0, 1.5, 3.0]
        final_pos = None
        
        for strike_idx, slippage in enumerate(escalation_steps, 1):
            curr_px = deepcoin_client.get_current_price(self.symbol)
            if curr_px <= 0: continue
                
            target_price = curr_px + slippage if action == "LONG" else curr_px - slippage
            deepcoin_client.place_limit_order(self.symbol, action, target_price, total_contracts, is_close=False)
            
            filled = False
            for _ in range(20): # 等待20秒
                time.sleep(1.0)
                pos = self._get_active_position()
                if pos and pos['side'] == action and pos['size'] >= total_contracts * 0.90: 
                    filled = True
                    final_pos = pos
                    break
                    
            if filled: break
            deepcoin_client.cancel_all_open_orders(symbol=self.symbol)
            time.sleep(1.0)

        if final_pos and final_pos['size'] > 0:
            return True, final_pos['entry_price'], margin, int(final_pos['size'])
            
        return False, 0.0, 0.0, 0

    def _get_active_position(self) -> dict:
        try:
            res = deepcoin_client.get_position_info(self.symbol)
            data = res.get("data", [])
            for pos in data:
                size = float(pos.get("pos", 0))
                if size > 0:
                    entry = float(pos.get("avgPx", pos.get("price", 0)))
                    side = pos.get("posSide", "").upper()
                    return {"size": size, "entry_price": entry, "side": side}
            return None
        except Exception: return None

    # ==================== V8.0 哨兵对账与汇报引擎 ====================
    def _start_sentinel(self, side: str, qty: int):
        with self._lock:
            self.watched_side = side
            self.watched_qty = qty
            self.monitoring = True
        self.sentinel_thread = threading.Thread(target=self._sentinel_loop, daemon=True)
        self.sentinel_thread.start()

    def _stop_sentinel(self):
        with self._lock:
            self.monitoring = False
            self.watched_side = None
            self.watched_qty = 0

    def _sentinel_loop(self):
        logger.info("👀 [Deepcoin] 哨兵巡更启动，紧盯 7U/15U 限价单吃单状况...")
        while self.monitoring:
            try:
                pos = self._get_active_position()
                current_qty = int(pos['size']) if pos else 0
                current_side = pos['side'] if pos else None

                # 核心防线：对账与纠偏
                if current_qty > 0 and current_side and current_side != self.watched_side:
                    logger.warning("🚨 [哨兵] 发现反向持仓！强制对齐清理！")
                    self._close_all("哨兵对齐：强平反向仓位")
                    self._stop_sentinel()
                    break

                if current_qty != self.watched_qty:
                    if current_qty == 0:
                        logger.info("💥 [哨兵] 仓位归零！清理盘口残余挂单。")
                        deepcoin_client.cancel_all_open_orders(self.symbol)
                        dingtalk.report_deepcoin_tp("全平 / 撤单", current_qty)
                        self._stop_sentinel()
                        break
                    
                    elif current_qty < self.watched_qty:
                        logger.info(f"✨ [哨兵] 仓位缩减: {self.watched_qty} -> {current_qty}！止盈落袋！")
                        dingtalk.report_deepcoin_tp("限价减仓落袋", current_qty)
                        with self._lock: self.watched_qty = current_qty

                    elif current_qty > self.watched_qty:
                        logger.warning(f"👀 [哨兵] 检测到人工加仓: {self.watched_qty} -> {current_qty}")
                        dingtalk.report_deepcoin_tp("人工加仓干预", current_qty)
                        with self._lock: self.watched_qty = current_qty

            except Exception: pass
            time.sleep(5)

    def _report_timeout(self):
        dingtalk.report_deepcoin_clear("黄金60秒狙击落空，撤单防站岗")

deepcoin_processor = DeepcoinProcessor()
