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

        self.regime_settings = {
            1: {"margin": 0.15}, 
            2: {"margin": 0.25}, 
            3: {"margin": 0.35}, 
            4: {"margin": 0.50}  
        }

        self.leverage = 20
        self.face_value = 0.1
        
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
        logger.info("🧠 深币 VPS [V10.1 高频微利版] 已加载：固定30%头寸 + 4.5U限价止盈")

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    "last_tv_side": self.last_tv_side, 
                    "watched_qty": self.watched_qty,
                    "local_tp1": self.local_tp1
                }, f)
        except:
            pass

    def _get_active_position(self):
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                if int(p.get("pos", 0)) > 0:
                    return {
                        "size": int(p.get("pos")), 
                        "entry_price": round(float(p.get("avgPx", p.get("price", 0))), 2), 
                        "posSide": p.get("posSide", "long").lower()
                    }
        return None

    def process_signal(self, payload):
        self.handle_signal(payload)

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        if self.regime not in self.regime_settings:
            self.regime = 3
        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_price = round(float(payload.get("price", 0.0)), 2)

        if not raw_action:
            return
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
                self._handle_close_command(f"🛡️ 保护性全平")
        finally:
            self._lock.release()

    def _handle_close_command(self, reason):
        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self._close_all(reason)
        else:
            dingtalk.report_deepcoin_clear(f"{reason}", "✅ 提前安全空仓")

    def _handle_smart_entry(self, action):
        logger.info(f"⚡ 收到建仓信号 [{action}]，启动强制净身流程！")
        
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)

        current_pos = self._get_active_position()
        curr_px = deepcoin_client.get_current_price(self.symbol)

        if current_pos and current_pos.get('size', 0) > 0:
            current_side = "LONG" if current_pos["posSide"] == "long" else "SHORT"
            if current_side == action:
                self._close_all("同方向新指令到达，强制【先平后开】")
            else:
                self._close_all("反方向指令到达，强制【先平后开】")
            time.sleep(1.2)

        logger.info("🛡️ [战前自检] 正在核查阵地是否 100% 净空...")
        for attempt in range(3):
            pos = self._get_active_position()
            if not pos or int(pos.get('size', 0)) == 0:
                break
            qty = int(pos['size'])
            logger.warning(f"⚠️ [开仓前警报] 监测到残留 {qty} 张，执行战前抹杀 (第{attempt+1}次)")
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4)
            deepcoin_client._request("POST", "/trade/batch-close-position", {"productGroup": "SwapU", "instId": self.symbol})
            time.sleep(1.2)

        self._open_position(action, curr_px)

    def _open_position(self, side, curr_px):
        if curr_px <= 0:
            return

        # ==================== 固定30%头寸 ====================
        MARGIN_RATIO = 0.30
        LEVERAGE = 20
        available_balance = deepcoin_client.get_available_balance()
        qty = max(int((available_balance * MARGIN_RATIO * LEVERAGE) / (curr_px * self.face_value)), 1)
        # =================================================

        open_side, pos_side = ("buy", "long") if side == "LONG" else ("sell", "short")
        
        logger.info(f"🚀 [固定头寸开仓] {open_side} {qty}张 | 30%余额 + {LEVERAGE}x杠杆")
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

            logger.info(f"🎯 [挂出止盈] 全仓 {self.watched_qty} 张 @ 4.5U微利价: {self.fee_cover_price}")
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

                    # 方向异常检测
                    if actual_qty > 0 and actual_side != self.last_tv_side:
                        self._close_all("强行对齐方向")
                        dingtalk.report_force_align(actual_side, self.last_tv_side)
                        break

                    # 仓位归零检测（优化版）
                    if actual_qty == 0:
                        if self.watched_qty > 0:
                            logger.info("🎯 [态势感知] 实盘仓位归零")
                            self._close_all("🎯 仓位已归零")
                        self.monitoring = False
                        break

                    # 人工增减仓同步
                    if actual_qty != self.watched_qty and actual_qty > 0:
                        logger.warning(f"🔄 [持仓同步] {self.watched_qty} -> {actual_qty}张")
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
                        deepcoin_client.place_limit_order(self.symbol, close_side, pos['posSide'], self.fee_cover_price, actual_qty, reduce_only=True)
                        dingtalk.report_system_alert("持仓同步", f"已同步最新 {actual_qty} 张，并重新挂载4.5U止盈")

                    # 已取消：reached后挂保本止损 + 止损上移逻辑

                finally:
                    self._lock.release()

            except Exception as e:
                logger.error(f"雷达异常: {e}")
            time.sleep(3.5)

    def _close_all(self, reason=""):
        logger.warning(f"🔨 启动全平: {reason}")
        
        for _ in range(2):
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4)

        for round_num in range(6):
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0:
                break

            qty = int(pos['size'])
            logger.info(f"🔨 第{round_num+1}轮清场: 剩余 {qty} 张")

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
        self.monitoring = False
        self.radar_activated = False
        self.watched_qty = 0
        self._save_state()

        if not final_pos or final_pos.get('size', 0) == 0:
            dingtalk.report_deepcoin_clear(reason, "✅ 全平成功")
        else:
            dingtalk.report_system_alert("清仓失败", f"仍残留 {final_pos.get('size')} 张")

    def recover_state_on_startup(self):
        logger.info("🔄 [启动自检] 正在同步实盘状态...")
        try:
            pos = self._get_active_position()

            if not pos or pos.get('size', 0) == 0:
                logger.info("🟢 当前无持仓，清除历史挂单")
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

            logger.info(f"🔄 [接管持仓] {self.current_side} {actual_qty}张 @ {self.watched_entry}")
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.5)
            deepcoin_client.place_limit_order(self.symbol, close_side, pos.get('posSide').lower(), self.fee_cover_price, actual_qty, reduce_only=True)

            self.monitoring = True
            threading.Thread(target=self._radar_loop, daemon=True).start()
            dingtalk.report_system_alert("VPS重启同步", f"已接管实盘 {self.current_side} {actual_qty} 张，并重新挂载4.5U止盈")

        except Exception as e:
            logger.error(f"启动状态恢复异常: {e}")


position_supervisor = PositionSupervisor()
deepcoin_processor = position_supervisor

position_supervisor.recover_state_on_startup()
