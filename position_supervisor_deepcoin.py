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
        self.fee_cover_margin = 0.0015          # 核心：0.15% 覆盖手续费
        
        self.current_atr = 30.0
        self.sl_mult = 1.03
        
        self.regime = 3
        self.tv_price = 0.0
        self.last_tv_side = None
        
        self.initial_qty = 0.0
        self.watched_qty = 0.0
        self.watched_entry = 0.0
        self.current_side = None
        self.current_sl = 0.0

        self.daily_start_date = ""
        self.daily_start_balance = 0.0
        self.cb_level1_pct = -5.0
        self.cb_level2_pct = -10.0

        logger.info("🧠 深币 [极致刷单返佣版] 大脑已加载（目标：0.15% 极速覆盖手续费）")

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
            logger.info(f"📅 新交易日基线已更新: {current_balance:.2f} USDT")
        return self.daily_start_balance

    def process_signal(self, payload: dict):
        action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        self.tv_price = float(payload.get("price", 0.0))
        self.current_atr = float(payload.get("atr", 30.0))
        self.sl_mult = float(payload.get("sl_m", 1.03))

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

                # 防追高
                if self.tv_price > 0 and abs(curr_px - self.tv_price) > 5.0:
                    dingtalk.report_system_alert("防追高拦截", f"现价 {curr_px} vs TV {self.tv_price}，放弃刷单")
                    return

                # 强制清理旧仓位（加强版）
                self._close_all("新信号到达，强制清理旧阵地")
                time.sleep(1.2)

                # 二次确认仓位是否真的归零
                final_check = self._get_active_position()
                if final_check and final_check.get('size', 0) > 0:
                    dingtalk.report_system_alert("严重异常", "多次平仓后仍残留仓位，拒绝开新仓！")
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

    def _calc_tight_tp_sl(self, entry_price):
        tp_offset = entry_price * self.fee_cover_margin
        if self.current_side == "LONG":
            tp_px = round(entry_price + tp_offset, 2)
            sl_px = round(entry_price - self.current_atr * self.sl_mult, 2)
            return tp_px, sl_px
        else:
            tp_px = round(entry_price - tp_offset, 2)
            sl_px = round(entry_price + self.current_atr * self.sl_mult, 2)
            return tp_px, sl_px

    def _protect_and_monitor(self, qty, entry_price):
        tp_px, sl_px = self._calc_tight_tp_sl(entry_price)
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"

        # 100% 仓位一波流挂限价单
        deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_px, int(qty))

        self.best_price = entry_price
        self.current_sl = sl_px
        self.watched_qty = qty
        self.watched_entry = entry_price
        self.initial_qty = qty
        self.monitoring = True

        # 钉钉报告（已匹配最新 dingtalk.py）
        dingtalk.report_deepcoin_open(
            side=self.current_side,
            entry_price=entry_price,
            qty=int(qty),
            tp_price=tp_px,
            sl_price=self.current_sl,
            atr=self.current_atr,
            old_qty=0,
            tv_price=self.tv_price,
            regime=self.regime
        )

        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                pos = self._get_active_position()
                actual_qty = int(pos['size']) if pos else 0

                # 仓位归零 = 刷单成功
                if actual_qty == 0:
                    self._close_all("✅ 刷单完成（手续费已覆盖）")
                    break

                actual_side = pos.get('posSide', '').upper() or ("LONG" if actual_qty > 0 else "SHORT")

                # 方向对齐检查
                if actual_side != self.last_tv_side and actual_side in ["LONG", "SHORT"]:
                    self._close_all("强行对齐")
                    dingtalk.report_force_align(actual_side, self.last_tv_side)
                    break

                curr_px = deepcoin_client.get_current_price(self.symbol)

                # 硬止损兜底
                if (self.current_side == "LONG" and curr_px <= self.current_sl) or \
                   (self.current_side == "SHORT" and curr_px >= self.current_sl):
                    self._close_all("触发极限兜底止损")
                    break

                # 挂单自愈
                pending = deepcoin_client._request("GET", "/trade/orders-pending", {"instType": "SWAP", "instId": self.symbol})
                if pending and isinstance(pending, dict) and len(pending.get('data', [])) == 0 and actual_qty > 0:
                    tp_px, _ = self._calc_tight_tp_sl(self.watched_entry)
                    close_side = "sell" if self.current_side == "LONG" else "buy"
                    pos_side = "long" if self.current_side == "LONG" else "short"
                    logger.warning("挂单丢失，自动重建...")
                    deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_px, actual_qty)

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
                _, self.current_sl = self._calc_tight_tp_sl(self.watched_entry)
                self.monitoring = True
                logger.info("🔄 灾备自愈：刷单系统重启，哨兵已接管")
                threading.Thread(target=self._sentinel_loop, daemon=True).start()
        except Exception as e:
            logger.error(f"灾备恢复失败: {e}")


deepcoin_processor = DeepcoinProcessor()
deepcoin_processor.recover_state_on_startup()
