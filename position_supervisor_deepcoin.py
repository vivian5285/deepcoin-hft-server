#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging, time, threading, os, json
from logging.handlers import RotatingFileHandler
from deepcoin_client import deepcoin_client
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

        # 四档资金利用率配置
        self.regime_settings = {
            1: {"margin": 0.15}, 
            2: {"margin": 0.25}, 
            3: {"margin": 0.35}, 
            4: {"margin": 0.50}  
        }

        self.leverage = 20
        self.face_value = 0.1
        self.fee_cover_margin = 0.0014 # 覆盖双边手续费+微利的安全空间（0.14%）
        
        self.radar_activated = False
        self.fee_cover_price = 0.0
        self.local_tp1 = 0.0  # 微利流模式下 local_tp1 弃用，保持为 0
        
        self.regime = 3
        self.current_atr = 30.0
        self.tv_tp1 = 0.0     
        self.tv_price = 0.0

        self.current_side = None
        self.last_tv_side = None
        self.watched_qty = 0
        self.watched_entry = 0.0
        self.current_sl = 0.0
        
        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [V9.7 双向持仓微利版] 已加载：覆盖手续费全平，彻底斩断波段利润！")

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f: json.dump({
                "last_tv_side": self.last_tv_side, 
                "watched_qty": self.watched_qty,
                "local_tp1": self.local_tp1
            }, f)
        except: pass

    def _get_active_position(self):
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                if int(p.get("pos", 0)) > 0:
                    return {"size": int(p.get("pos")), "entry_price": round(float(p.get("avgPx", p.get("price", 0))), 2), "posSide": p.get("posSide", "long").lower()}
        return None

    def process_signal(self, payload):
        self.handle_signal(payload)

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        
        self.regime = int(payload.get("regime", 3))
        if self.regime not in self.regime_settings: self.regime = 3
        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_tp1 = round(float(payload.get("tv_tp1", 0.0)), 2)
        self.tv_price = round(float(payload.get("price", 0.0)), 2)

        if not raw_action: return
        
        if not self._lock.acquire(timeout=10.0): 
            logger.error("⚠️ 系统正忙，指令获取锁超时被丢弃！")
            return

        try:
            if raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self._save_state()
                self._handle_smart_entry(raw_action)
            elif raw_action == "CLOSE_TP3" or raw_action == "CLOSE": 
                self._handle_close_command("🧹 策略清场指令到达")
            elif raw_action.startswith("CLOSE_PROTECT"): 
                self._handle_close_command(f"🛡️ 保护性全平: {raw_action.split('|')[1] if '|' in raw_action else '保护性全平'}")
        finally:
            self._lock.release()

    def _handle_close_command(self, reason):
        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0: self._close_all(reason)
        else: dingtalk.report_deepcoin_clear(f"{reason}", "✅ 提前安全空仓")

    # ================= 🚀 V9.7 战前双向原子持仓清理清道夫 =================
    def _handle_smart_entry(self, action):
        current_pos = self._get_active_position()
        curr_px = deepcoin_client.get_current_price(self.symbol)

        if current_pos and current_pos.get('size', 0) > 0:
            current_side = "LONG" if current_pos["posSide"] == "long" else "SHORT"
            # 如果实盘持仓方向和新信号方向一致，先全平刷新阵地，实现高频刷佣
            if current_side == action: 
                self._close_all("同方向新交易到达 (高频刷佣刷新阵地)")
            else: 
                self._close_all("反方向指令到达，执行原子对冲换防")
            time.sleep(1.2)
        else:
            logger.info("🧹 [战前清理] 优先强撤历史残余保本挂单与条件单...")
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.5)

        logger.info("🛡️ [战前自检] 启动双向持仓严密空间净空巡检...")
        for attempt in range(3):
            pos = self._get_active_position()
            if not pos or int(pos.get('size', 0)) == 0:
                break 
                
            qty = int(pos['size'])
            logger.warning(f"⚠️ [开仓前警报] 监测到双向持仓中仍残留 {qty} 张，执行战前原子抹杀 (第{attempt+1}次)！")
            
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4)
            # 强平该交易对下所有双向持仓[cite: 7]
            deepcoin_client._request("POST", "/trade/batch-close-position", {"productGroup": "SwapU", "instId": self.symbol})
            time.sleep(1.2)

        self._open_position(action, curr_px)

    # ================= 🚀 V9.7 核心：100% 仓位微利单全量挂单开仓 =================
    def _open_position(self, side, curr_px):
        if curr_px <= 0: return
        
        qty = max(int((deepcoin_client.get_available_balance() * self.regime_settings[self.regime]["margin"] * self.leverage) / (curr_px * self.face_value)), 1)
        open_side, pos_side = ("buy", "long") if side == "LONG" else ("sell", "short")
        
        logger.info(f"🚀 [双向持仓开仓] 建立新阵地: {open_side} {qty}张 (持仓方向: {pos_side})")
        deepcoin_client.place_market_order(self.symbol, open_side, pos_side, qty)
        time.sleep(2.0)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self.current_side = side
            self.watched_qty = int(pos['size'])
            self.watched_entry = pos['entry_price']
            self.current_sl = self.watched_entry
            self.radar_activated = False
            
            # 计算微利全平的目标价格（覆盖双边手续费）
            if self.current_side == "LONG":
                self.fee_cover_price = round(self.watched_entry * (1 + self.fee_cover_margin), 2)
                close_side = "sell" # 做多对应卖出平多[cite: 6]
            else:
                self.fee_cover_price = round(self.watched_entry * (1 - self.fee_cover_margin), 2)
                close_side = "buy"  # 做空对应买入平空[cite: 6]
            
            self.local_tp1 = 0.0 # 微利流放弃大止盈波段
            self._save_state()

            # 战术硬核：100%全量持仓，直接挂单至保本微利价（利用 reduce_only 确保只减仓不反向开仓）[cite: 6]
            logger.info(f"🎯 [微利挂单] 全仓 {self.watched_qty} 张直接布防于保本微利价: {self.fee_cover_price}")
            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.fee_cover_price, self.watched_qty, reduce_only=True)

            # 推送定制战报
            dingtalk.report_deepcoin_open(self.current_side, self.regime, self.current_atr, self.watched_entry, self.tv_price, self.watched_qty, self.watched_qty, self.fee_cover_price, 0, 0, 0)
            self._start_radar_monitor()

    def _start_radar_monitor(self):
        self.monitoring = True
        threading.Thread(target=self._radar_loop, daemon=True).start()

    def _radar_loop(self):
        while self.monitoring:
            try:
                if not self._lock.acquire(timeout=2.0):
                    time.sleep(1.0)
                    continue

                try:
                    pos = self._get_active_position()
                    actual_qty = int(pos['size']) if pos else 0
                    actual_side = "LONG" if pos and pos.get('posSide') == "long" else "SHORT"

                    # 双向持仓校验：防止发生方向错乱异常
                    if actual_qty > 0 and actual_side != self.last_tv_side:
                        self._close_all("强行对齐方向")
                        dingtalk.report_force_align(actual_side, self.last_tv_side)
                        break

                    if actual_qty == 0:
                        # 好消息：仓位成功归零说明微利限价挂单已被交易所完美吃掉落袋
                        if self.watched_qty > 0: 
                            self._close_all("🎯 极速微利：保本限价单已被完全吃掉，落袋为安！")
                        else: 
                            self.monitoring = False
                        break

                    if actual_qty > self.watched_qty:
                        self._close_all("🚨 人工违规加仓，强制对冲！")
                        break

                    # 监测是否发生 Partial Fill (部分成交)
                    qty_reduced = False
                    if actual_qty < self.watched_qty:
                        logger.info(f"📦 监测到实盘仓位减少: {self.watched_qty} -> {actual_qty}，微利单已被部分蚕食")
                        qty_reduced = True
                        self.watched_qty = actual_qty
                        self._save_state()

                    curr_px = deepcoin_client.get_current_price(self.symbol)
                    
                    # 第一重护甲触发条件：价格越过微利线，或者仓位发生减少[cite: 2]
                    reached = (self.current_side == "LONG" and curr_px >= self.fee_cover_price) or \
                              (self.current_side == "SHORT" and curr_px <= self.fee_cover_price) or \
                              qty_reduced

                    if reached and not self.radar_activated:
                        self.radar_activated = True
                        self.current_sl = self.watched_entry
                        dingtalk.report_fee_cover_reached(self.current_side, self.watched_entry, self.fee_cover_price, actual_qty)
                        close_side, pos_side = ("sell", "long") if self.current_side == "LONG" else ("buy", "short")
                        
                        # 触发双保险：利用原生条件单在持仓开仓均价挂上硬止损条件单保护[cite: 2, 6]
                        deepcoin_client._request("POST", "/trade/trigger-order", {
                            "instId": self.symbol, "productGroup": "Swap", "sz": str(int(actual_qty)),
                            "side": close_side, "posSide": pos_side, "isCrossMargin": "1",
                            "orderType": "market", "triggerPrice": str(self.current_sl),
                            "mrgPosition": "merge", "tdMode": "cross"
                        })

                    # 如果利润继续扩大，雷达推升开仓均价止损锁润[cite: 2]
                    if self.radar_activated:
                        moved = False
                        if self.current_side == "LONG" and curr_px > self.current_sl:
                            new_sl = max(self.current_sl, curr_px * 0.994)
                            if new_sl > self.current_sl + 0.8: self.current_sl = round(new_sl, 2); moved = True
                        elif self.current_side == "SHORT" and curr_px < self.current_sl:
                            new_sl = min(self.current_sl, curr_px * 1.006)
                            if new_sl < self.current_sl - 0.8: self.current_sl = round(new_sl, 2); moved = True

                        if moved:
                            deepcoin_client.cancel_all_open_orders(self.symbol)
                            time.sleep(0.3)
                            close_side, pos_side = ("sell", "long") if self.current_side == "LONG" else ("buy", "short")
                            
                            # 重新补上限价微利单并平移条件硬止损[cite: 2]
                            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.fee_cover_price, actual_qty, reduce_only=True)
                            
                            res = deepcoin_client._request("POST", "/trade/trigger-order", {
                                "instId": self.symbol, "productGroup": "Swap", "sz": str(int(actual_qty)),
                                "side": close_side, "posSide": pos_side, "isCrossMargin": "1",
                                "orderType": "market", "triggerPrice": str(self.current_sl),
                                "mrgPosition": "merge", "tdMode": "cross"
                            })
                            if res and str(res.get("code", "")) == "0": dingtalk.report_radar_move(self.current_side, self.current_sl)
                finally:
                    self._lock.release()

            except Exception as e: logger.error(f"雷达异常: {e}")
            time.sleep(3.5)

    # ================= 🚀 V9.7 6轮防漏阶梯核武平仓防线 =================
    def _close_all(self, reason=""):
        logger.warning(f"🔨 启动原子全平扫尾: {reason}")
        
        # 强力清空盘口挂单，释放仓位冻结锁定状态[cite: 2]
        for clear_attempt in range(2):
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4) 
        
        # 阶梯式 6 轮彻底强平循环，给足部分成交物理恢复缓冲期[cite: 9]
        for round_num in range(6):
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0: 
                break 
                
            qty = int(pos['size'])
            logger.info(f"🔨 第 {round_num+1} 轮清场: 剩余 {qty} 张，双向持仓强行爆破")
            
            # 第一重：原生批量全平清场[cite: 7]
            res = deepcoin_client._request("POST", "/trade/batch-close-position", {
                "productGroup": "SwapU", 
                "instId": self.symbol
            })
            
            # 第二重：极端网络状态下的市价单对冲平仓兜底[cite: 2]
            if not res or str(res.get("code", "")) != "0":
                pos_side = pos['posSide'] 
                close_side = "sell" if pos_side == "long" else "buy"
                deepcoin_client.place_market_order(self.symbol, close_side, pos_side, qty, reduce_only=True)
            
            # 阶梯休眠，专门解决极端行情下的 Partial Fill[cite: 9]
            time.sleep(1.8 if round_num < 3 else 2.5) 
                
        deepcoin_client.cancel_all_open_orders(self.symbol) 
        time.sleep(0.5)
        
        final_pos = self._get_active_position()
        self.monitoring, self.radar_activated, self.watched_qty = False, False, 0
        self._save_state()
        
        if not final_pos or final_pos.get('size', 0) == 0:
            if reason: dingtalk.report_deepcoin_clear(reason, "✅ 最终全平成功，阵地已绝对净空")
        else:
            dingtalk.report_system_alert("⚠️ 清仓失败", f"多次尝试后仍双向残留 {final_pos.get('size')} 张，建议人工介入！")

    def recover_state_on_startup(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    s = json.load(f)
                    self.last_tv_side = s.get("last_tv_side")
                    self.local_tp1 = s.get("local_tp1", 0.0) 
            pos = self._get_active_position()
            if pos and pos['size'] > 0:
                self.current_side = "LONG" if pos.get('posSide') == "long" else "SHORT"
                if not self.last_tv_side: self.last_tv_side = self.current_side
                self.watched_qty, self.watched_entry, self.monitoring = pos['size'], pos['entry_price'], True
                threading.Thread(target=self._radar_loop, daemon=True).start()
        except: pass

position_supervisor = PositionSupervisor()
deepcoin_processor = position_supervisor
