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

        # 深币合约参数
        self.leverage = 20
        self.face_value = 0.1
        self.fee_cover_margin = 0.0014
        
        self.radar_activated = False
        self.fee_cover_price = 0.0
        self.tv_tp1 = 0.0

        self.current_side = None
        self.last_tv_side = None
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_sl = 0.0
        
        # 价格偏移滤网：同向信号差价 <= 7 美金时忽略
        self.price_diff_threshold = 7.0 
        self.last_protect_time = 0

        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [双向对冲+智能动态拆分版] 已加载：恢复圣杯级测距分仓！")

    def _get_active_position(self):
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                size = float(p.get("pos", 0))
                if size > 0:
                    return {
                        "size": size, 
                        "entry_price": float(p.get("avgPx", p.get("price", 0))), 
                        "posSide": p.get("posSide", "long").lower()
                    }
        return None

    def process_signal(self, payload):
        """兼容 app.py 中的 deepcoin_processor.process_signal 调用"""
        self.handle_signal(payload)

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        self.tv_tp1 = float(payload.get("tv_tp1", 0.0))

        if not raw_action: return
        if not self._lock.acquire(blocking=False): return

        try:
            if raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self._handle_smart_entry(raw_action)

            elif raw_action == "CLOSE_TP3":
                self._handle_close_command("🎯 策略大波段(TP3)完结，深币同步清场")

            elif raw_action.startswith("CLOSE_PROTECT"):
                reason = payload.get("reason", "TV 图表要求保护性全平")
                self._handle_close_command(f"🛡️ 保护性全平: {reason}")

            elif raw_action == "CLOSE":
                reason = payload.get("reason", "TV 强制平仓")
                self._handle_close_command(f"🧹 强制清仓: {reason}")
        finally:
            self._lock.release()

    def _handle_close_command(self, reason):
        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self._close_all(reason)
        else:
            logger.info(f"[{reason}] 指令到达，但深币实盘已无仓位 (可能已提前双擎止盈)。")
            dingtalk.report_deepcoin_clear(f"{reason} (深币已提前落袋空仓)")

    def _handle_smart_entry(self, action):
        current_pos = self._get_active_position()
        has_position = current_pos and current_pos.get('size', 0) > 0
        curr_px = deepcoin_client.get_current_price(self.symbol)

        if not has_position:
            deepcoin_client.force_cancel_all(self.symbol)
            self._open_position(action, curr_px)
            return

        current_side = "LONG" if current_pos["posSide"] == "long" else "SHORT"
        avg_price = float(current_pos["entry_price"])

        if current_side == action:
            diff = abs(curr_px - avg_price)
            if diff <= self.price_diff_threshold:
                logger.info(f"🛡️ [深币拦截] 同向差异 ${diff:.2f} ≤ ${self.price_diff_threshold}，防震荡忽略！")
                return
            else:
                logger.info(f"🔄 [深币换仓] 同向差异 ${diff:.2f} > ${self.price_diff_threshold}，执行先平后开！")
                self._close_all("同方向大幅推移，更新阵地")
                time.sleep(1.2)
                self._open_position(action, curr_px)
        else:
            logger.info(f"⚔️ [深币反转] 收到反向信号，对冲先平后开")
            self._close_all("反方向对冲换防")
            time.sleep(1.2)
            self._open_position(action, curr_px)

    def _open_position(self, side, curr_px):
        if curr_px <= 0: return

        balance = deepcoin_client.get_available_balance()
        raw_qty = (balance * 0.28 * self.leverage) / (curr_px * self.face_value)
        qty = max(int(raw_qty), 1)

        open_side = "buy" if side == "LONG" else "sell"
        pos_side = "long" if side == "LONG" else "short"

        logger.info(f"🚀 [双向持仓] 开仓: {open_side} {qty}张 (轨号: {pos_side})")
        deepcoin_client.place_market_order(self.symbol, open_side, pos_side, qty)
        time.sleep(2.0)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self.current_side = side
            self.watched_qty = pos['size']
            self.watched_entry = pos['entry_price']
            self.current_sl = self.watched_entry
            self.radar_activated = False
            
            if self.current_side == "LONG":
                self.fee_cover_price = round(self.watched_entry * (1 + self.fee_cover_margin), 2)
            else:
                self.fee_cover_price = round(self.watched_entry * (1 - self.fee_cover_margin), 2)

            # ==================== 🚀 智能动态测距拆分 ====================
            # 以美金绝对差价为判定标准：
            # 如果 TP1 距离保本线 > 10美金，说明肉大，80%重兵保本；
            # 如果距离 > 6美金，65%兵力保本；
            # 如果距离极近(肉小)，50%对半分。
            distance = abs(self.fee_cover_price - self.tv_tp1)
            if distance > 10.0: 
                fee_ratio = 0.80
            elif distance > 6.0: 
                fee_ratio = 0.65
            else: 
                fee_ratio = 0.50

            qty_fee = int(self.watched_qty * fee_ratio)
            qty_tp1 = int(self.watched_qty) - qty_fee

            logger.info(f"📐 [动态拆分] TP1距离保本线 ${distance:.2f} ➔ 分配比例: 手续费 {fee_ratio*100}% ({qty_fee}张), TP1 {100-fee_ratio*100}% ({qty_tp1}张)")

            close_side = "sell" if self.current_side == "LONG" else "buy"
            
            if qty_fee > 0:
                deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.fee_cover_price, qty_fee)
            if qty_tp1 > 0 and self.tv_tp1 > 0:
                deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.tv_tp1, qty_tp1)

            dingtalk.report_deepcoin_open(self.current_side, self.watched_entry, self.watched_qty, self.fee_cover_price, self.tv_tp1)
            self._start_radar_monitor()

    def _start_radar_monitor(self):
        self.monitoring = True
        threading.Thread(target=self._radar_loop, daemon=True).start()

    def _radar_loop(self):
        while self.monitoring:
            try:
                pos = self._get_active_position()
                if not pos or pos.get('size', 0) == 0:
                    self.monitoring = False
                    self._close_all("✅ 隐身雷达：仓位已达 TP1 全部自然归零离场")
                    break

                curr_px = deepcoin_client.get_current_price(self.symbol)
                remaining_qty = int(pos['size'])
                actual_side = "LONG" if pos['posSide'] == "long" else "SHORT"

                if actual_side != self.last_tv_side and actual_side in ["LONG", "SHORT"]:
                    self._close_all("强行对齐方向")
                    dingtalk.report_force_align(actual_side, self.last_tv_side)
                    break

                reached = False
                if self.current_side == "LONG" and curr_px >= self.fee_cover_price: reached = True
                elif self.current_side == "SHORT" and curr_px <= self.fee_cover_price: reached = True

                # 雷达激活：过保本线，挂条件止损
                if reached and not self.radar_activated:
                    self.radar_activated = True
                    self.current_sl = self.watched_entry
                    dingtalk.report_fee_cover_reached(self.current_side, self.watched_entry, self.fee_cover_price, remaining_qty)

                    close_side = "sell" if self.current_side == "LONG" else "buy"
                    pos_side = "long" if self.current_side == "LONG" else "short"
                    
                    deepcoin_client._request("POST", "/trade/order-algo", {
                        "instId": self.symbol, "tdMode": "cross", "side": close_side, "posSide": pos_side,
                        "ordType": "conditional", "sz": str(remaining_qty), "triggerPx": str(self.current_sl), "orderPx": "-1"
                    })

                # 雷达追踪
                if self.radar_activated:
                    moved = False
                    if self.current_side == "LONG" and curr_px > self.current_sl:
                        new_sl = max(self.current_sl, curr_px * 0.994)
                        if new_sl > self.current_sl + 0.8:
                            self.current_sl = round(new_sl, 2)
                            moved = True
                    elif self.current_side == "SHORT" and curr_px < self.current_sl:
                        new_sl = min(self.current_sl, curr_px * 1.006)
                        if new_sl < self.current_sl - 0.8:
                            self.current_sl = round(new_sl, 2)
                            moved = True

                    if moved:
                        deepcoin_client.force_cancel_all(self.symbol)
                        time.sleep(0.3)
                        close_side = "sell" if self.current_side == "LONG" else "buy"
                        pos_side = "long" if self.current_side == "LONG" else "short"
                        
                        if self.tv_tp1 > 0:
                            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.tv_tp1, remaining_qty)

                        res = deepcoin_client._request("POST", "/trade/order-algo", {
                            "instId": self.symbol, "tdMode": "cross", "side": close_side, "posSide": pos_side,
                            "ordType": "conditional", "sz": str(remaining_qty), "triggerPx": str(self.current_sl), "orderPx": "-1"
                        })
                        if res and str(res.get("code", "")) == "0":
                            dingtalk.report_radar_move(self.current_side, self.current_sl)

            except Exception as e:
                logger.error(f"雷达异常: {e}")
            time.sleep(3.5)

    def _close_all(self, reason=""):
        deepcoin_client.force_cancel_all(self.symbol)
        time.sleep(0.5)
        
        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            qty = int(pos['size'])
            pos_side = pos['posSide'] 
            close_side = "sell" if pos_side == "long" else "buy"
            
            logger.info(f"🔨 [双向对冲] 物理全平: {close_side} {qty}张 (轨号: {pos_side})")
            for i in range(4):
                res = deepcoin_client.place_market_order(self.symbol, close_side, pos_side, qty)
                if res and str(res.get("code", "")) == "0":
                    break
                time.sleep(0.6)
                
        time.sleep(0.8)
        deepcoin_client.force_cancel_all(self.symbol)
        
        final_pos = self._get_active_position()
        self.monitoring = False
        self.radar_activated = False
        self.watched_qty = 0.0
        
        if not final_pos or final_pos.get('size', 0) == 0:
            logger.info(f"[全平完成] {reason}")
            if reason: dingtalk.report_deepcoin_clear(reason)

    def recover_state_on_startup(self):
        try:
            pos = self._get_active_position()
            if pos and pos['size'] > 0:
                self.current_side = "LONG" if pos.get('posSide') == "long" else "SHORT"
                self.initial_qty = pos['size']
                self.watched_qty = self.initial_qty
                self.watched_entry = pos['entry_price']
                self.monitoring = True
                logger.info("🔄 灾备自愈：哨兵雷达已强行接管双向持仓实盘！")
                threading.Thread(target=self._radar_loop, daemon=True).start()
        except Exception as e: logger.error(f"灾备恢复失败: {e}")

position_supervisor = PositionSupervisor()
deepcoin_processor = position_supervisor
