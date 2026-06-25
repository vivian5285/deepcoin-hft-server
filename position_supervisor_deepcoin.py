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

        # 深币专属：动态四档资金利用率 & TP1 乘数
        self.regime_settings = {
            1: {"margin": 0.15, "tp1_m": 0.75}, # 极弱波段：15%仓位，跑得快
            2: {"margin": 0.25, "tp1_m": 1.10}, # 弱势推升：25%仓位，标准止盈
            3: {"margin": 0.35, "tp1_m": 1.30}, # 中势单边：35%仓位，利润拉大
            4: {"margin": 0.50, "tp1_m": 1.55}  # 强势主升：50%重仓，吃满趋势
        }

        self.leverage = 20
        self.face_value = 0.1
        self.fee_cover_margin = 0.0014 # 保手续费安全距离
        
        self.radar_activated = False
        self.fee_cover_price = 0.0
        self.local_tp1 = 0.0  # VPS自己算出来的实盘 TP1
        
        self.regime = 3
        self.current_atr = 30.0
        self.tv_tp1 = 0.0     # 仅作播报对比
        self.tv_price = 0.0

        self.current_side = None
        self.last_tv_side = None
        self.watched_qty = 0
        self.watched_entry = 0.0
        self.current_sl = 0.0
        
        self.price_diff_threshold = 7.0 
        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [V8.0 参数自治版] 已加载：VPS完全夺回仓位与TP1定价权！")

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
        
        # 接收环境参数
        self.regime = int(payload.get("regime", 3))
        if self.regime not in self.regime_settings: self.regime = 3
        self.current_atr = float(payload.get("atr", 30.0))
        
        # 仅作展示对比
        self.tv_tp1 = round(float(payload.get("tv_tp1", 0.0)), 2)
        self.tv_price = round(float(payload.get("price", 0.0)), 2)

        if not raw_action: return
        if not self._lock.acquire(timeout=10.0): 
            logger.error("⚠️ 系统正忙，指令被丢弃！")
            return

        try:
            if raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self._save_state()
                self._handle_smart_entry(raw_action)

            elif raw_action == "CLOSE_TP3":
                self._handle_close_command("🎯 策略大波段(TP3)完结，深币同步清场")

            elif raw_action.startswith("CLOSE_PROTECT"):
                reason = raw_action.split("|")[1] if "|" in raw_action else "保护性全平"
                self._handle_close_command(f"🛡️ 保护性全平: {reason}")
                
            elif raw_action == "CLOSE":
                self._handle_close_command("🧹 强制清仓")
        finally:
            self._lock.release()

    def _handle_close_command(self, reason):
        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0: self._close_all(reason)
        else: dingtalk.report_deepcoin_clear(f"{reason}", "✅ 提前安全空仓")

    def _handle_smart_entry(self, action):
        current_pos = self._get_active_position()
        curr_px = deepcoin_client.get_current_price(self.symbol)

        if not current_pos:
            deepcoin_client.cancel_all_open_orders(self.symbol)
            self._open_position(action, curr_px)
            return

        current_side = "LONG" if current_pos["posSide"] == "long" else "SHORT"
        if current_side == action:
            diff = abs(curr_px - current_pos["entry_price"])
            if diff <= self.price_diff_threshold:
                logger.info("🛡️ [深币拦截] 震荡区间，防乱动忽略！")
                return
            else:
                self._close_all("同方向大幅推移，更新阵地")
                time.sleep(1.2)
                self._open_position(action, curr_px)
        else:
            self._close_all("反方向指令到达，对冲换防")
            time.sleep(1.2)
            self._open_position(action, curr_px)

    def _open_position(self, side, curr_px):
        if curr_px <= 0: return
        
        # 🚀 提取深币 VPS 内置的动态仓位比例
        dynamic_margin = self.regime_settings[self.regime]["margin"]
        raw_qty = (deepcoin_client.get_available_balance() * dynamic_margin * self.leverage) / (curr_px * self.face_value)
        qty = max(int(raw_qty), 1)

        open_side, pos_side = ("buy", "long") if side == "LONG" else ("sell", "short")
        logger.info(f"🚀 [双向持仓] 开仓: {open_side} {qty}张 (轨号: {pos_side})")
        deepcoin_client.place_market_order(self.symbol, open_side, pos_side, qty)
        time.sleep(2.0)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self.current_side = side
            self.watched_qty = int(pos['size'])
            self.watched_entry = pos['entry_price']
            self.current_sl = self.watched_entry
            self.radar_activated = False
            
            # 🚀 提取深币 VPS 内置的 TP1 乘数，亲手计算实盘 TP1
            tp1_m = self.regime_settings[self.regime]["tp1_m"]
            
            if self.current_side == "LONG":
                self.local_tp1 = round(self.watched_entry + self.current_atr * tp1_m, 2)
                self.fee_cover_price = round(self.watched_entry * (1 + self.fee_cover_margin), 2)
            else:
                self.local_tp1 = round(self.watched_entry - self.current_atr * tp1_m, 2)
                self.fee_cover_price = round(self.watched_entry * (1 - self.fee_cover_margin), 2)
                
            self._save_state()

            # 动态测距分仓 (使用本地计算的 local_tp1 做尺子)
            distance = abs(self.fee_cover_price - self.local_tp1)
            fee_ratio = 0.80 if distance > 10.0 else (0.65 if distance > 6.0 else 0.50)
            
            # 绝对张数防错兜底
            if self.watched_qty == 1: qty_fee, qty_tp1 = 1, 0
            else:
                qty_fee = max(int(self.watched_qty * fee_ratio), 1)
                qty_tp1 = self.watched_qty - qty_fee

            close_side = "sell" if side == "LONG" else "buy"
            
            if qty_fee > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.fee_cover_price, qty_fee, reduce_only=True)
            if qty_tp1 > 0 and self.local_tp1 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.local_tp1, qty_tp1, reduce_only=True)

            dingtalk.report_deepcoin_open(self.current_side, self.regime, self.current_atr, self.watched_entry, self.tv_price, self.watched_qty, qty_fee, self.fee_cover_price, qty_tp1, self.local_tp1, self.tv_tp1)
            self._start_radar_monitor()

    def _start_radar_monitor(self):
        self.monitoring = True
        threading.Thread(target=self._radar_loop, daemon=True).start()

    def _radar_loop(self):
        while self.monitoring:
            try:
                pos = self._get_active_position()
                actual_qty = int(pos['size']) if pos else 0
                actual_side = "LONG" if pos and pos.get('posSide') == "long" else "SHORT"

                if actual_qty > 0 and actual_side != self.last_tv_side:
                    self._close_all("强行对齐方向")
                    dingtalk.report_force_align(actual_side, self.last_tv_side)
                    break

                if actual_qty == 0:
                    if self.watched_qty > 0: self._close_all("🚨 仓位突然归零")
                    else: self.monitoring = False
                    break

                if actual_qty > self.watched_qty:
                    self._close_all("🚨 人工违规加仓，强制对冲！")
                    break

                if actual_qty < self.watched_qty:
                    self.watched_qty = actual_qty
                    self._save_state()

                curr_px = deepcoin_client.get_current_price(self.symbol)
                reached = (self.current_side == "LONG" and curr_px >= self.fee_cover_price) or (self.current_side == "SHORT" and curr_px <= self.fee_cover_price)

                if reached and not self.radar_activated:
                    self.radar_activated = True
                    self.current_sl = self.watched_entry
                    dingtalk.report_fee_cover_reached(self.current_side, self.watched_entry, self.fee_cover_price, actual_qty)
                    close_side, pos_side = ("sell", "long") if self.current_side == "LONG" else ("buy", "short")
                    deepcoin_client._request("POST", "/trade/order-algo", {"instId": self.symbol, "tdMode": "cross", "side": close_side, "posSide": pos_side, "ordType": "conditional", "sz": str(actual_qty), "triggerPx": str(self.current_sl), "orderPx": "-1", "reduceOnly": True})

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
                        # 🚀 锁润后，剩余冲锋残兵依然挂在本地计算的 local_tp1 上
                        if self.local_tp1 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.local_tp1, actual_qty, reduce_only=True)
                        res = deepcoin_client._request("POST", "/trade/order-algo", {"instId": self.symbol, "tdMode": "cross", "side": close_side, "posSide": pos_side, "ordType": "conditional", "sz": str(actual_qty), "triggerPx": str(self.current_sl), "orderPx": "-1", "reduceOnly": True})
                        if res and str(res.get("code", "")) == "0": dingtalk.report_radar_move(self.current_side, self.current_sl)

            except Exception as e: logger.error(f"雷达异常: {e}")
            time.sleep(3.5)

    def _close_all(self, reason=""):
        logger.warning(f"🔨 启动核武级全平: {reason}")
        for attempt in range(5):
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.6)
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0: break
                
            qty = int(pos['size'])
            pos_side = pos['posSide'] 
            close_side = "sell" if pos_side == "long" else "buy"
            
            deepcoin_client.place_market_order(self.symbol, close_side, pos_side, qty, reduce_only=True)
            time.sleep(1.5)
                
        deepcoin_client.cancel_all_open_orders(self.symbol) 
        final_pos = self._get_active_position()
        self.monitoring, self.radar_activated, self.watched_qty = False, False, 0
        self._save_state()
        
        if not final_pos or final_pos.get('size', 0) == 0:
            if reason: dingtalk.report_deepcoin_clear(reason, "✅ 5轮核武器全平成功")
        else:
            dingtalk.report_system_alert("⚠️ 清仓失败", f"已执行5次爆破对冲，仍有残留: {final_pos.get('size')} 张，建议人工介入！")

    def recover_state_on_startup(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    s = json.load(f)
                    self.last_tv_side = s.get("last_tv_side")
                    self.local_tp1 = s.get("local_tp1", 0.0) # 灾备恢复本地计算的TP1
            pos = self._get_active_position()
            if pos and pos['size'] > 0:
                self.current_side = "LONG" if pos.get('posSide') == "long" else "SHORT"
                if not self.last_tv_side: self.last_tv_side = self.current_side
                self.watched_qty, self.watched_entry, self.monitoring = pos['size'], pos['entry_price'], True
                threading.Thread(target=self._radar_loop, daemon=True).start()
        except: pass

position_supervisor = PositionSupervisor()
deepcoin_processor = position_supervisor
