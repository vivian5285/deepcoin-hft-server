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
        logger.info("🧠 深币 VPS [V10.2 智能人工干预版] 已加载")

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
            elif raw_action in ["CLOSE_TP3", "CLOSE"]:
                self._handle_close_command("策略清场指令")
            elif raw_action.startswith("CLOSE_PROTECT"):
                self._handle_close_command("保护性全平")
        finally:
            self._lock.release()

    def _handle_close_command(self, reason):
        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self._close_all(reason)
        else:
            dingtalk.report_deepcoin_clear(reason, "✅ 提前安全空仓")

    def _handle_smart_entry(self, action):
        logger.info(f"⚡ 收到建仓信号 [{action}]，启动强制净身流程")
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)

        current_pos = self._get_active_position()
        curr_px = deepcoin_client.get_current_price(self.symbol)

        if current_pos and current_pos.get('size', 0) > 0:
            current_side = "LONG" if current_pos["posSide"] == "long" else "SHORT"
            if current_side == action:
                self._close_all("同方向强制先平后开")
            else:
                self._close_all("反方向强制先平后开")
            time.sleep(1.2)

        for attempt in range(3):
            pos = self._get_active_position()
            if not pos or int(pos.get('size', 0)) == 0:
                break
            qty = int(pos['size'])
            logger.warning(f"⚠️ 检测到残留 {qty} 张，执行战前抹杀")
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4)
            deepcoin_client._request("POST", "/trade/batch-close-position", {"productGroup": "SwapU", "instId": self.symbol})
            time.sleep(1.2)

        self._open_position(action, curr_px)

    def _open_position(self, side, curr_px):
        if curr_px <= 0:
            return

        # 固定30%头寸
        MARGIN_RATIO = 0.30
        LEVERAGE = 20
        available_balance = deepcoin_client.get_available_balance()
        qty = max(int((available_balance * MARGIN_RATIO * LEVERAGE) / (curr_px * self.face_value)), 1)

        open_side, pos_side = ("buy", "long") if side == "LONG" else ("sell", "short")
        logger.info(f"🚀 固定头寸开仓: {open_side} {qty}张（30% + 20x）")

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

                    # 方向异常检测（保留原有强逻辑）
                    if actual_qty > 0 and actual_side != self.last_tv_side:
                        self._close_all("强行对齐方向")
                        dingtalk.report_force_align(actual_side, self.last_tv_side)
                        break

                    # ==================== 智能人工干预处理（新增） ====================
                    if actual_qty != self.watched_qty and actual_qty > 0:
                        old_qty = self.watched_qty
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

                        if actual_qty > old_qty:
                            dingtalk.report_system_alert("人工加仓同步", f"从 {old_qty} 张 → {actual_qty} 张，已更新并重新挂载4.5U止盈")
                        else:
                            dingtalk.report_system_alert("人工减仓同步", f"从 {old_qty} 张 → {actual_qty} 张，已重新挂载4.5U止盈")

                    # 人工全平检测
                    if actual_qty == 0 and self.watched_qty > 0:
                        logger.info("🎯 检测到人工全平")
                        dingtalk.report_deepcoin_clear("人工全平", "✅ 检测到人工全平，雷达停止监控")
                        self.monitoring = False
                        self.watched_qty = 0
                        self._save_state()
                        break
                    # ============================================================

                    # 普通仓位归零检测
                    if actual_qty == 0 and self.watched_qty > 0:
                        logger.info("🎯 仓位归零")
                        self._close_all("仓位已归零")
                        self.monitoring = False
                        break

                finally:
                    self._lock.release()

            except Exception as e:
                logger.error(f"雷达异常: {e}")
            time.sleep(3.5)

    def _close_all(self, reason=""):
        logger.warning(f"🔨 全平: {reason}")
        for _ in range(2):
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.4)

        for round_num in range(6):
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0:
                break
            qty = int(pos['size'])
            res = deepcoin_client._request("POST", "/trade/batch-close-position", {"productGroup": "SwapU", "instId": self.symbol})
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
        logger.info("🔄 启动自检同步实盘状态...")
        try:
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0:
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
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.5)
            deepcoin_client.place_limit_order(self.symbol, close_side, pos.get('posSide').lower(), self.fee_cover_price, actual_qty, reduce_only=True)

            self.monitoring = True
            threading.Thread(target=self._radar_loop, daemon=True).start()
            dingtalk.report_system_alert("VPS重启同步", f"已接管 {self.current_side} {actual_qty} 张并重新挂载4.5U止盈")
        except Exception as e:
            logger.error(f"启动同步异常: {e}")


position_supervisor = PositionSupervisor()
deepcoin_processor = position_supervisor
position_supervisor.recover_state_on_startup()
