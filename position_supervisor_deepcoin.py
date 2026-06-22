#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging, time, threading, os, json
from datetime import datetime
from logging.handlers import RotatingFileHandler
from deepcoin_client import deepcoin_client
import dingtalk

if not os.path.exists('logs'): os.makedirs('logs')
handler = RotatingFileHandler('logs/deepcoin_brain.log', maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Brain: %(message)s', handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)

class DeepcoinProcessor:
    def __init__(self):
        self.symbol = "ETH-USDT-SWAP"
        self.monitoring = False
        self._lock = threading.Lock()
        
        self.leverage = 20
        self.face_value = 0.1
        self.tp_ratios = [0.10, 0.30, 0.60]
        
        self.tp1_mult = 1.28
        self.tp2_mult = 2.45
        self.tp3_mult = 3.45
        self.sl_mult = 1.03
        self.current_trail_factor = 0.50 
        self.current_atr = 30.0
        
        self.regime = 3
        self.tv_price = 0.0
        self.tv_tp1 = 0.0
        self.tv_tp2 = 0.0
        self.tv_tp3 = 0.0
        self.tv_sl = 0.0
        
        self.initial_qty = 0.0
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_side = None
        self.best_price = 0.0
        self.current_sl = 0.0

        # 🛡️ 每日熔断护甲参数
        self.daily_start_date = ""
        self.daily_start_balance = 0.0
        self.cb_level1_pct = -5.0
        self.cb_level2_pct = -10.0

        # ==================== 移动保本止损自适应触发比例 ====================
        self.breakeven_ratios = {
            1: 0.70,   # 极弱 - 最保守
            2: 0.65,   # 弱势
            3: 0.60,   # 中势（默认）
            4: 0.55    # 强势 - 相对积极
        }

        logger.info("🧠 深币 V10.41 最终呼吸空间版大脑加载完毕：硬止损已移除，regime自适应保本已启用！")

    def _get_or_update_daily_baseline(self, current_balance):
        today = datetime.utcnow().strftime('%Y-%m-%d')
        tracker_file = 'deepcoin_risk_tracker.json'
        
        if self.daily_start_date != today:
            try:
                if os.path.exists(tracker_file):
                    with open(tracker_file, 'r') as f:
                        data = json.load(f)
                        if data.get('date') == today:
                            self.daily_start_date = today
                            self.daily_start_balance = float(data.get('balance'))
                            return self.daily_start_balance
            except Exception: pass
                
            self.daily_start_date = today
            self.daily_start_balance = current_balance
            try:
                with open(tracker_file, 'w') as f:
                    json.dump({'date': today, 'balance': current_balance}, f)
            except Exception: pass
            logger.info(f"📅 新的交易日 ({today}) 开启，重置深币本金基线: {current_balance:.2f} USDT")
            
        return self.daily_start_balance

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        self.tv_price = float(payload.get("price", 0.0))
        self.current_atr = float(payload.get("atr", 30.0))
        self.tp1_mult = float(payload.get("tp1_m", 1.28))
        self.tp2_mult = float(payload.get("tp2_m", 2.45))
        self.tp3_mult = float(payload.get("tp3_m", 3.45))
        self.sl_mult  = float(payload.get("sl_m", 1.03)) 
        self.current_trail_factor = float(payload.get("trail_factor", 0.50)) 
        self.tv_tp1 = float(payload.get("tv_tp1", 0.0))
        self.tv_tp2 = float(payload.get("tv_tp2", 0.0))
        self.tv_tp3 = float(payload.get("tv_tp3", 0.0))
        self.tv_sl  = float(payload.get("tv_sl", 0.0))
        
        if not action: return
        if not self._lock.acquire(blocking=False): return
            
        try:
            self.monitoring = False 
            if action == "CLOSE":
                reason = payload.get("reason", "TV 图表要求强制清仓")
                self._close_all(f"TV 终极裁决: {reason}")
                return

            if action in ["LONG", "SHORT"]:
                curr_px = deepcoin_client.get_current_price(self.symbol)
                if self.tv_price > 0 and abs(curr_px - self.tv_price) > 5.0:
                    dingtalk.report_system_alert("防追高拦截", f"偏差过大: 现价 {curr_px} vs TV {self.tv_price}")
                    return

                # 🔄 无论同向还是反向，永远先撤单 + 全平
                deepcoin_client.cancel_all_open_orders(self.symbol)
                time.sleep(0.6)
                self._close_all("新信号到达，强制清理旧仓位与挂单")
                time.sleep(0.8)

                old_pos = self._get_active_position()
                old_qty = int(old_pos['size']) if old_pos else 0

                balance = deepcoin_client.get_available_balance()
                baseline = self._get_or_update_daily_baseline(balance)
                
                daily_pnl_pct = (balance - baseline) / baseline * 100 if baseline > 0 else 0
                
                if daily_pnl_pct <= self.cb_level2_pct:
                    msg = f"今日真实亏损已达 {daily_pnl_pct:.2f}%，触发【🔴 绝对熔断】！系统物理锁死，今日拒绝开新仓！"
                    logger.warning(msg)
                    dingtalk.report_system_alert("🔴 账户物理熔断", msg)
                    return
                
                if self.regime == 1: dynamic_margin = 0.15
                elif self.regime == 2: dynamic_margin = 0.25
                elif self.regime == 3: dynamic_margin = 0.35
                else: dynamic_margin = 0.50
                
                if daily_pnl_pct <= self.cb_level1_pct:
                    dynamic_margin *= 0.5
                    msg = f"今日亏损达 {daily_pnl_pct:.2f}%，触发【🟡 风险降级护甲】，本次开仓军费强制减半至 {dynamic_margin*100}%"
                    logger.warning(msg)
                    dingtalk.report_system_alert("🟡 仓位降级护甲", msg)
                
                target_qty = int((balance * dynamic_margin * self.leverage) / (curr_px * self.face_value))
                if target_qty < 1: return 
                
                logger.info(f"💰 触发档位 {self.regime}，系统最终调拨资金执行 20 倍杠杆！")
                open_side = "buy" if action == "LONG" else "sell"
                open_pos_side = "long" if action == "LONG" else "short"

                for attempt in range(3):
                    res = deepcoin_client.place_market_order(self.symbol, open_side, open_pos_side, target_qty)
                    if res and str(res.get("code")) == "0": break
                    time.sleep(0.5)
                
                pos = None
                for _ in range(5):
                    time.sleep(1)
                    pos = self._get_active_position()
                    if pos and pos['size'] > 0: break

                if pos and pos['size'] > 0:
                    self.current_side = action
                    self.initial_qty = pos['size']
                    self._protect_and_monitor(pos['size'], pos['entry_price'], old_qty)
        finally:
            self._lock.release()

    def _calc_tp_sl(self, entry_price):
        if self.current_side == "LONG":
            return (round(entry_price + self.current_atr * self.tp1_mult, 2), 
                    round(entry_price + self.current_atr * self.tp2_mult, 2), 
                    round(entry_price + self.current_atr * self.tp3_mult, 2), 
                    round(entry_price - self.current_atr * self.sl_mult, 2))
        else:
            return (round(entry_price - self.current_atr * self.tp1_mult, 2), 
                    round(entry_price - self.current_atr * self.tp2_mult, 2), 
                    round(entry_price - self.current_atr * self.tp3_mult, 2), 
                    round(entry_price + self.current_atr * self.sl_mult, 2))

    def _protect_and_monitor(self, qty, entry_price, old_qty=0):
        tp1_px, tp2_px, tp3_px, sl_px = self._calc_tp_sl(entry_price)
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"
        
        qty1 = int(qty * self.tp_ratios[0])
        qty2 = int(qty * self.tp_ratios[1])
        qty3 = int(qty - qty1 - qty2)

        # 注意：已完全移除初始硬止损（place_conditional_order）
        if qty1 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp1_px, qty1)
        if qty2 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp2_px, qty2)
        if qty3 > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp3_px, qty3)
        
        self.best_price = entry_price
        self.current_sl = entry_price   # 初始不设置硬止损

        dingtalk.report_deepcoin_open(
            self.current_side, entry_price, qty, 
            [tp1_px, tp2_px, tp3_px], self.current_sl, self.current_atr, old_qty,
            self.tv_price, [self.tv_tp1, self.tv_tp2, self.tv_tp3], self.tv_sl, self.regime
        )
        self.watched_qty, self.watched_entry, self.monitoring = qty, entry_price, True
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                pos = self._get_active_position()
                actual_qty = int(pos['size']) if pos else 0
                if actual_qty == 0: self._close_all("空仓清场"); break
                    
                actual_entry = pos['entry_price']
                actual_side = pos.get('posSide', '').upper()
                if not actual_side: actual_side = "LONG" if actual_qty > 0 else "SHORT"

                if actual_side != self.current_side and actual_side in ["LONG", "SHORT"]:
                    self._close_all("强行对齐")
                    dingtalk.report_force_align(actual_side, self.current_side)
                    break
                
                curr_px = deepcoin_client.get_current_price(self.symbol)
                if self.current_side == "LONG": self.best_price = max(self.best_price, curr_px)
                else: self.best_price = min(self.best_price, curr_px)

                trail_offset = self.current_atr * self.current_trail_factor * 0.45 
                is_breakeven = actual_qty < (self.initial_qty * 0.95)

                # ==================== regime 自适应移动保本触发 ====================
                activation_ratio = self.breakeven_ratios.get(self.regime, 0.60)
                has_moved_favorably = False
                
                if self.current_side == "LONG":
                    required_price = self.watched_entry + self.current_atr * self.tp1_mult * activation_ratio
                    has_moved_favorably = curr_px >= required_price
                else:
                    required_price = self.watched_entry - self.current_atr * self.tp1_mult * activation_ratio
                    has_moved_favorably = curr_px <= required_price

                if is_breakeven and has_moved_favorably:
                    close_side = "sell" if self.current_side == "LONG" else "buy"
                    pos_side = "long" if self.current_side == "LONG" else "short"
                    
                    if self.current_side == "LONG":
                        calculated_sl = round(self.best_price - trail_offset, 2)
                        new_sl = max(calculated_sl, self.watched_entry, self.current_sl)
                        if new_sl - self.current_sl > 2.0:
                            deepcoin_client.cancel_all_open_orders(self.symbol)
                            time.sleep(0.5)
                            self.current_sl = new_sl
                            _, _, tp3_px, _ = self._calc_tp_sl(actual_entry)
                            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp3_px, actual_qty)
                            deepcoin_client.place_conditional_order(self.symbol, close_side, pos_side, new_sl, actual_qty)
                            dingtalk.report_intervention(actual_qty, actual_entry, tp3_px, new_sl, "🚀 追踪止盈：绝对保本！")
                    else:
                        calculated_sl = round(self.best_price + trail_offset, 2)
                        new_sl = min(calculated_sl, self.watched_entry, self.current_sl)
                        if self.current_sl - new_sl > 2.0:
                            deepcoin_client.cancel_all_open_orders(self.symbol)
                            time.sleep(0.5)
                            self.current_sl = new_sl
                            _, _, tp3_px, _ = self._calc_tp_sl(actual_entry)
                            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp3_px, actual_qty)
                            deepcoin_client.place_conditional_order(self.symbol, close_side, pos_side, new_sl, actual_qty)
                            dingtalk.report_intervention(actual_qty, actual_entry, tp3_px, new_sl, "🚀 追踪止盈：绝对保本！")
                
                elif abs(actual_qty - self.watched_qty) > 0.001 or abs(actual_entry - self.watched_entry) > 0.5:
                    deepcoin_client.cancel_all_open_orders(self.symbol)
                    time.sleep(1)
                    with self._lock:
                        self.watched_qty, self.watched_entry = actual_qty, actual_entry
                        
                    _, _, tp3_px, original_sl_px = self._calc_tp_sl(actual_entry)
                    close_side = "sell" if self.current_side == "LONG" else "buy"
                    pos_side = "long" if self.current_side == "LONG" else "short"
                    
                    sl_safe = round(actual_entry, 2) if is_breakeven else original_sl_px
                    deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp3_px, actual_qty)
                    deepcoin_client.place_conditional_order(self.symbol, close_side, pos_side, sl_safe, actual_qty)
                    dingtalk.report_intervention(actual_qty, actual_entry, tp3_px, sl_safe, "已触发异常自愈重装")

            except Exception as e: logger.error(f"哨兵出错: {e}")
            time.sleep(3)

    def _get_active_position(self) -> dict:
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                size = float(p.get("pos", 0))
                if size > 0: return {"size": size, "entry_price": float(p.get("avgPx", p.get("price", 0))), "posSide": p.get("posSide", "")}
        return None

    def _close_all(self, reason: str):
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        for i in range(8):
            deepcoin_client.close_all_positions(self.symbol)
            time.sleep(0.8) 
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0:
                break 
        self.monitoring = False
        if reason: dingtalk.report_deepcoin_clear(reason)

    def recover_state_on_startup(self):
        try:
            pos = self._get_active_position()
            if pos and pos['size'] > 0:
                actual_side = pos.get('posSide', '').upper()
                if not actual_side: actual_side = "LONG"
                self.current_side = actual_side
                self.initial_qty = pos['size']
                self.watched_qty = self.initial_qty
                self.watched_entry = pos['entry_price']
                self.best_price = self.watched_entry
                self.current_atr = 30.0
                self.regime = 3
                self.monitoring = True
                logger.info(f"🔄 灾备自愈：系统重启！哨兵雷达已强行接管！")
                threading.Thread(target=self._sentinel_loop, daemon=True).start()
        except Exception as e:
            logger.error(f"灾备恢复失败: {e}")

deepcoin_processor = DeepcoinProcessor()
deepcoin_processor.recover_state_on_startup()
