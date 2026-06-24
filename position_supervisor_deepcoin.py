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
        self.fee_cover_margin = 0.0015
        
        self.current_atr = 30.0
        self.sl_mult = 1.03
        
        self.regime = 3
        self.tv_price = 0.0
        self.tv_tp1 = 0.0
        self.last_tv_side = None
        
        self.initial_qty = 0.0
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_side = None
        self.current_sl = 0.0
        self.fee_cover_price = 0.0

        self.daily_start_date = ""
        self.daily_start_balance = 0.0
        self.cb_level1_pct = -5.0
        self.cb_level2_pct = -10.0

        logger.info("🧠 深币 [智能保本+轻追踪版] 大脑已加载")

    def _get_or_update_daily_baseline(self, current_balance):
        today = datetime.utcnow().strftime('%Y-%m-%d')
        tracker_file = 'deepcoin_risk_tracker.json'
        if self.daily_start_date != today:
            self.daily_start_date = today
            self.daily_start_balance = current_balance
            try:
                with open(tracker_file, 'w') as f:
                    json.dump({'date': today, 'balance': current_balance}, f)
            except: pass
        return self.daily_start_balance

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        self.tv_price = float(payload.get("price", 0.0))
        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_tp1 = float(payload.get("tv_tp1", 0.0))

        if not action: return
        if not self._lock.acquire(blocking=False): return

        try:
            self.monitoring = False

            if action == "CLOSE":
                reason = payload.get("reason", "TV 强制清仓")
                self._close_all(f"TV 指令: {reason}")
                return

            if action in ["LONG", "SHORT"]:
                self.last_tv_side = action
                curr_px = deepcoin_client.get_current_price(self.symbol)

                if self.tv_price > 0 and abs(curr_px - self.tv_price) > 5.0:
                    dingtalk.report_system_alert("防追高拦截", f"现价 {curr_px} vs TV {self.tv_price}")
                    return

                deepcoin_client.force_cancel_all(self.symbol)
                time.sleep(0.7)
                self._close_all("新信号到达，强制清理旧阵地")
                time.sleep(1.0)

                final_check = self._get_active_position()
                if final_check and final_check.get('size', 0) > 0:
                    dingtalk.report_system_alert("严重异常", "多次强制平仓后仍残留仓位，拒绝开新仓！")
                    return

                balance = deepcoin_client.get_available_balance()
                baseline = self._get_or_update_daily_baseline(balance)
                daily_pnl_pct = (balance - baseline) / baseline * 100 if baseline > 0 else 0

                if daily_pnl_pct <= self.cb_level2_pct:
                    return

                if self.regime == 1: dynamic_margin = 0.15
                elif self.regime == 2: dynamic_margin = 0.25
                elif self.regime == 3: dynamic_margin = 0.35
                else: dynamic_margin = 0.50

                if daily_pnl_pct <= self.cb_level1_pct:
                    dynamic_margin *= 0.5

                target_qty = int((balance * dynamic_margin * self.leverage) / (curr_px * self.face_value))
                if target_qty < 1: return

                open_side = "buy" if action == "LONG" else "sell"
                open_pos_side = "long" if action == "LONG" else "short"

                for attempt in range(3):
                    res = deepcoin_client.place_market_order(self.symbol, open_side, open_pos_side, target_qty)
                    if res and str(res.get("code", "")) == "0": break
                    time.sleep(0.5)

                pos = None
                for _ in range(6):
                    time.sleep(0.8)
                    pos = self._get_active_position()
                    if pos and pos['size'] > 0: break

                if pos and pos['size'] > 0:
                    self.current_side = action
                    self.initial_qty = pos['size']
                    self._protect_and_monitor(pos['size'], pos['entry_price'])
        finally:
            self._lock.release()

    def _calc_fee_cover_price(self, entry_price):
        if self.current_side == "LONG":
            return round(entry_price + entry_price * self.fee_cover_margin, 2)
        else:
            return round(entry_price - entry_price * self.fee_cover_margin, 2)

    def _protect_and_monitor(self, qty, entry_price):
        self.fee_cover_price = self._calc_fee_cover_price(entry_price)
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"

        # 动态拆分挂单
        distance = abs(self.fee_cover_price - self.tv_tp1)
        if distance > 0.10:
            fee_ratio = 0.80
        elif distance > 0.06:
            fee_ratio = 0.65
        else:
            fee_ratio = 0.50

        qty_fee = int(qty * fee_ratio)
        qty_tp1 = qty - qty_fee

        if qty_fee > 0:
            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.fee_cover_price, qty_fee)
        if qty_tp1 > 0 and self.tv_tp1 > 0:
            deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, self.tv_tp1, qty_tp1)

        self.best_price = entry_price
        self.watched_qty = qty
        self.watched_entry = entry_price
        self.initial_qty = qty
        self.monitoring = True

        # 已同步更新为新版 dingtalk 参数
        dingtalk.report_deepcoin_open(
            side=self.current_side,
            entry_price=entry_price,
            qty=qty,
            fee_cover_price=self.fee_cover_price,
            tv_tp1=self.tv_tp1,
            atr=self.current_atr,
            old_qty=0,
            tv_price=self.tv_price,
            regime=self.regime
        )

        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        breakeven_activated = False

        while self.monitoring:
            try:
                pos = self._get_active_position()
                actual_qty = int(pos['size']) if pos else 0

                if actual_qty == 0:
                    self._close_all("✅ 刷单完成")
                    break

                actual_side = pos.get('posSide', '').upper() or ("LONG" if actual_qty > 0 else "SHORT")

                if actual_side != self.last_tv_side and actual_side in ["LONG", "SHORT"]:
                    self._close_all("强行对齐")
                    dingtalk.report_force_align(actual_side, self.last_tv_side)
                    break

                curr_px = deepcoin_client.get_current_price(self.symbol)

                if self.current_side == "LONG":
                    self.best_price = max(self.best_price, curr_px)
                else:
                    self.best_price = min(self.best_price, curr_px)

                # 移动保本激活
                if not breakeven_activated:
                    activation_dist = abs(self.fee_cover_price - self.watched_entry) * 0.55
                    has_moved = False

                    if self.current_side == "LONG":
                        has_moved = (curr_px - self.watched_entry) >= activation_dist
                    else:
                        has_moved = (self.watched_entry - curr_px) >= activation_dist

                    if has_moved:
                        breakeven_activated = True
                        logger.info("雷达启动移动保本止损")

                # 轻追踪
                if breakeven_activated:
                    trail_offset = abs(self.fee_cover_price - self.watched_entry) * 0.42
                    if self.current_side == "LONG":
                        new_level = self.best_price - trail_offset
                        if new_level > self.fee_cover_price:
                            self.fee_cover_price = round(new_level, 2)
                    else:
                        new_level = self.best_price + trail_offset
                        if new_level < self.fee_cover_price:
                            self.fee_cover_price = round(new_level, 2)

            except Exception as e:
                logger.error(f"哨兵异常: {e}")
            time.sleep(2.5)

    def _get_active_position(self):
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                size = float(p.get("pos", 0))
                if size > 0:
                    return {"size": size, "entry_price": float(p.get("avgPx", p.get("price", 0))), "posSide": p.get("posSide", "")}
        return None

    def _close_all(self, reason: str):
        try:
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.5)

            pos = self._get_active_position()
            if pos and pos.get('size', 0) > 0:
                qty = int(pos['size'])
                close_side = "sell" if self.current_side == "LONG" else "buy"
                pos_side = "long" if self.current_side == "LONG" else "short"

                for i in range(4):
                    res = deepcoin_client.place_market_order(self.symbol, close_side, pos_side, qty)
                    if res and str(res.get("code", "")) == "0": break
                    time.sleep(0.7)

            deepcoin_client.cancel_all_open_orders(self.symbol)
        except Exception as e:
            logger.error(f"_close_all 异常: {e}")

        self.monitoring = False
        self.current_side = None
        self.watched_qty = 0
        self.watched_entry = 0
        self.initial_qty = 0

        if reason:
            dingtalk.report_deepcoin_clear(reason)

    def recover_state_on_startup(self):
        try:
            pos = self._get_active_position()
            if pos and pos['size'] > 0:
                self.current_side = pos.get('posSide', '').upper() or "LONG"
                self.initial_qty = pos['size']
                self.watched_qty = self.initial_qty
                self.watched_entry = pos['entry_price']
                self.best_price = self.watched_entry
                self.fee_cover_price = self._calc_fee_cover_price(self.watched_entry)
                self.monitoring = True
                logger.info("🔄 灾备自愈：刷单系统重启")
                threading.Thread(target=self._sentinel_loop, daemon=True).start()
        except Exception as e:
            logger.error(f"灾备恢复失败: {e}")


deepcoin_processor = DeepcoinProcessor()
deepcoin_processor.recover_state_on_startup()
