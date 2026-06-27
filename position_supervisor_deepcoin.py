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

        # 四档资金利用率配置（保留，但入场不再使用）
        self.regime_settings = {
            1: {"margin": 0.15}, 
            2: {"margin": 0.25}, 
            3: {"margin": 0.35}, 
            4: {"margin": 0.50}  
        }

        self.leverage = 20
        self.face_value = 0.1
        
        # 固定微利参数
        self.fee_cover_margin = 0.0015 
        self.micro_profit_usdt = 4.5   
        
        self.radar_activated = False
        self.fee_cover_price = 0.0
        self.local_tp1 = 0.0  
        
        self.regime = 3
        self.current_atr = 30.0
        self.tv_price = 0.0

        self.current_side = None
        self.last_tv_side = None
        self.watched_qty = 0
        self.watched_entry = 0.0
        self.current_sl = 0.0
        
        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [V10.0 智能态势感知版] 已加载：支持人工干预同步、启动自检重构、4.5U绝对收割！")

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

    def _handle_smart_entry(self, action):
        logger.info(f"⚡ 收到建仓信号 [{action}]，启动强制净身流程！")
        
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)

        current_pos = self._get_active_position()
        curr_px = deepcoin_client.get_current_price(self.symbol)

        if current_pos and current_pos.get('size', 0) > 0:
            current_side = "LONG" if current_pos["posSide"] == "long" else "SHORT"
            if current_side == action: 
                self._close_all("同方向新指令到达，强制【先平后开】洗清旧仓！")
            else: 
                self._close_all("反方向指令到达，强制【先平后开】对冲换防！")
            time.sleep(1.2)

        logger.info("🛡️ [战前自检] 正在核查阵地是否 100% 净空...")
        for attempt in range(3):
            pos = self._get_active_position()
            if not pos or int(pos.get('size', 0)) == 0:
                break 
                
            qty = int(pos['size'])
            logger.warning(f"⚠️ [开仓前警报] 监测到残留 {qty} 张，执行战前抹杀 (第{attempt+1}次)！")
            
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4)
            deepcoin_client._request("POST", "/trade/batch-close-position", {"productGroup": "SwapU", "instId": self.symbol})
            time.sleep(1.2)

        self._open_position(action, curr_px)

    def _open_position(self, side, curr_px):
        if curr_px <= 0: return
        
        # ==================== 只修改此处 ====================
        # 固定使用本金的 30% + 20倍杠杆
        MARGIN_RATIO = 0.30
        LEVERAGE = 20
        available_balance = deepcoin_client.get_available_balance()
        qty = max(int((available_balance * MARGIN_RATIO * LEVERAGE) / (curr_px * self.face_value)), 1)
        # =================================================

        open_side, pos_side = ("buy", "long") if side == "LONG" else ("sell", "short")
        
        logger.info(f"🚀 [固定头寸开仓] {open_side} {qty}张 | 使用余额30% + {LEVERAGE}x杠杆")
        deepcoin_client.place_market_order(self.symbol, open_side, pos_side, qty)
        time.sleep(2.0)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self.current_side = side
            self.watched_qty = int(pos['size'])
            self.watched_entry = pos['entry_price']
            self.current_sl = self.watched_entry
            self.radar_activated = False
            
            if self.current_side == "LONG":
                self.fee_cover_price = round(self.watched_entry + self.micro_profit_usdt, 2)
                close_side = "sell"
            else:
                self.fee_cover_price = round(self.watched_entry - self.micro_profit_usdt, 2)
                close_side = "buy"
            
            self._save_state()

            logger.info(f"🎯 [挂出止盈] 全仓 {self.watched_qty} 张布防于 4.5U 绝对微利价: {self.fee_cover_price}")
            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.fee_cover_price, self.watched_qty, reduce_only=True)

            dingtalk.report_deepcoin_open(self.current_side, self.regime, self.current_atr, self.watched_entry, self.tv_price, self.watched_qty, self.watched_qty, self.fee_cover_price)
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

                    if actual_qty > 0 and actual_side != self.last_tv_side:
                        self._close_all("强行对齐方向")
                        dingtalk.report_force_align(actual_side, self.last_tv_side)
                        break

                    if actual_qty == 0:
                        if self.watched_qty > 0: 
                            logger.info("🎯 [态势感知] 实盘仓位归零！可能是微利单成交，或人工介入全平。")
                            self._close_all("🎯 极速微利落袋 / 人工介入全平，完美收网！")
                        else: 
                            self.monitoring = False
                        break

                    if actual_qty != self.watched_qty and actual_qty > 0:
                        logger.warning(f"🔄 [态势感知] 监测到实盘持仓变化 (人工增减/部分成交): {self.watched_qty} -> {actual_qty}张。启动热同步！")
                        self.watched_qty = actual_qty
                        self.watched_entry = pos['entry_price']
                        
                        if self.current_side == "LONG":
                            self.fee_cover_price = round(self.watched_entry + self.micro_profit_usdt, 2)
                            close_side = "sell"
                        else:
                            self.fee_cover_price = round(self.watched_entry - self.micro_profit_usdt, 2)
                            close_side = "buy"
                        
                        self._save_state()
                        
                        deepcoin_client.cancel_all_open_orders(self.symbol)
                        time.sleep(0.4)
                        logger.info(f"🔄 [态势重设] 为全新的 {self.watched_qty} 张重新挂设止盈限价: {self.fee_cover_price}")
                        deepcoin_client.place_limit_order(self.symbol, close_side, pos['posSide'], self.fee_cover_price, self.watched_qty, reduce_only=True)
                        
                        dingtalk.report_system_alert("🔄 态势感知热同步", f"发现阵地张数异动！已接管最新 {self.watched_qty} 张仓位，并将微利目标重新锚定至 {self.fee_cover_price}！")

                    curr_px = deepcoin_client.get_current_price(self.symbol)
                    
                    reached = (self.current_side == "LONG" and curr_px >= self.fee_cover_price) or \
                              (self.current_side == "SHORT" and curr_px <= self.fee_cover_price)

                    if reached and not self.radar_activated:
                        self.radar_activated = True
                        self.current_sl = self.watched_entry
                        dingtalk.report_fee_cover_reached(self.current_side, self.watched_entry, self.fee_cover_price, actual_qty)
                        close_side, pos_side = ("sell", "long") if self.current_side == "LONG" else ("buy", "short")
                        
                        deepcoin_client._request("POST", "/trade/trigger-order", {
                            "instId": self.symbol, "productGroup": "Swap", "sz": str(int(actual_qty)),
                            "side": close_side, "posSide": pos_side, "isCrossMargin": "1",
                            "orderType": "market", "triggerPrice": str(self.current_sl),
                            "mrgPosition": "merge", "tdMode": "cross"
                        })

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

    def _close_all(self, reason=""):
        logger.warning(f"🔨 启动原子全平扫尾: {reason}")
        
        for clear_attempt in range(2):
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4) 
        
        for round_num in range(6):
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0: 
                break 
                
            qty = int(pos['size'])
            logger.info(f"🔨 第 {round_num+1} 轮清场: 剩余 {qty} 张，强制爆破")
            
            res = deepcoin_client._request("POST", "/trade/batch-close-position", {
                "productGroup": "SwapU", 
                "instId": self.symbol
            })
            
            if not res or str(res.get("code", "")) != "0":
                pos_side = pos['posSide'] 
                close_side = "sell" if pos_side == "long" else "buy"
                deepcoin_client.place_market_order(self.symbol, close_side, pos_side, qty, reduce_only=True)
            
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
        logger.info("🔄 [启动自检] VPS拉起，正在直连深币云端同步真实盘口数据...")
        try:
            pos = self._get_active_position()
            
            if not pos or pos.get('size', 0) == 0:
                logger.info("🟢 [启动自检] 当前无实盘持仓，强制扫清历史挂单，随时恭候新信号！")
                deepcoin_client.cancel_all_open_orders(self.symbol)
                self.monitoring = False
                self.watched_qty = 0
                self._save_state()
                return

            actual_qty = int(pos['size'])
            self.current_side = "LONG" if pos.get('posSide') == "long" else "SHORT"
            self.watched_entry = pos['entry_price']
            self.last_tv_side = self.current_side
            self.watched_qty = actual_qty
            self.current_sl = self.watched_entry
            self.radar_activated = False

            if self.current_side == "LONG":
                self.fee_cover_price = round(self.watched_entry + self.micro_profit_usdt, 2)
                close_side = "sell"
            else:
                self.fee_cover_price = round(self.watched_entry - self.micro_profit_usdt, 2)
                close_side = "buy"

            self._save_state()

            logger.info(f"🔄 [接管实盘] 发现已有持仓: {self.current_side} {actual_qty}张 @ {self.watched_entry}。撤销废旧挂单，重新布置 4.5U 战线！")
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.5)

            deepcoin_client.place_limit_order(self.symbol, close_side, pos.get('posSide').lower(), self.fee_cover_price, actual_qty, reduce_only=True)

            self.monitoring = True
            threading.Thread(target=self._radar_loop, daemon=True).start()
            dingtalk.report_system_alert("🔄 VPS 重启同步", f"服务已重启！无缝接管实盘阵地：{self.current_side} {actual_qty} 张。已自动为您重新挂载 4.5U 的止盈护盾！")
            
        except Exception as e:
            logger.error(f"启动状态恢复异常: {e}")

position_supervisor = PositionSupervisor()
deepcoin_processor = position_supervisor

position_supervisor.recover_state_on_startup()
