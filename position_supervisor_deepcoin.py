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

        # 🚀 资金比例与智慧雷达矩阵（融合了双轨保本与分寸感机制，与币安完全同频）
        self.regime_settings = {
            1: {"margin": 0.15, "ratios": [0.25, 0.35, 0.40], "activation": 0.40, "trail_offset": 0.40},
            2: {"margin": 0.25, "ratios": [0.20, 0.35, 0.45], "activation": 0.50, "trail_offset": 0.60},
            3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "activation": 0.60, "trail_offset": 0.90},
            4: {"margin": 0.50, "ratios": [0.05, 0.20, 0.75], "activation": 0.70, "trail_offset": 1.30}
        }
        self.leverage = 15  
        self.face_value = 0.1

        self.regime, self.current_atr, self.tv_price = 3, 30.0, 0.0
        self.tv_tps = [0.0, 0.0, 0.0]  
        self.current_side, self.last_tv_side = None, None
        self.watched_qty, self.watched_entry, self.current_sl = 0, 0.0, 0.0
        self.initial_qty, self.best_price = 0, 0.0
        
        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [军师托管版] 已加载：双轨智慧雷达部署完毕！")

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump({
                    "last_tv_side": self.last_tv_side, 
                    "current_side": self.current_side, 
                    "watched_qty": self.watched_qty, 
                    "watched_entry": self.watched_entry, 
                    "current_sl": self.current_sl, 
                    "monitoring": self.monitoring,
                    "tv_tps": self.tv_tps  
                }, f)
        except Exception as e:
            logger.error(f"保存状态失败: {e}")

    def _get_active_position(self):
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                if int(p.get("pos", 0)) > 0:
                    return {"size": int(p.get("pos")), "entry_price": round(float(p.get("avgPx", p.get("price", 0))), 2), "posSide": p.get("posSide", "long").lower()}
        return None

    def _calculate_tp_quantities(self, total_qty: int, ratios: list) -> tuple:
        if total_qty <= 0: return 0, 0, 0
        q1 = max(1, round(total_qty * ratios[0]))
        remaining = total_qty - q1
        if remaining <= 0: return q1, 0, 0
        ratio_sum_23 = ratios[1] + ratios[2]
        if ratio_sum_23 <= 0: return q1, 0, remaining
        q2 = max(0, round(remaining * (ratios[1] / ratio_sum_23)))
        q3 = remaining - q2
        if q3 < 0: q3, q2 = 0, remaining
        if q2 == 0 and remaining >= 2: q2, q3 = 1, remaining - 1
        if q3 == 0 and remaining >= 2 and q2 > 1: q3, q2 = 1, remaining - 1
        return q1, q2, q3

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        if self.regime not in self.regime_settings: self.regime = 3
        
        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_price = round(float(payload.get("price", 0.0)), 2)
        
        self.tv_tps = [
            float(payload.get("tv_tp1", 0)), 
            float(payload.get("tv_tp2", 0)), 
            float(payload.get("tv_tp3", 0))
        ]
        close_reason = payload.get("reason", "策略指标反转/波动率安全退出")

        if not raw_action or not self._lock.acquire(timeout=10.0): return
        try:
            self.monitoring = False
            if raw_action.startswith("CLOSE_PROTECT"):
                self._close_all(f"🛡️ 保护性全平：{close_reason}")
            elif raw_action == "CLOSE_TP3": 
                self._close_all("🎯 完美胜利：大趋势吃满，TP3 终极收网")
            elif raw_action == "CLOSE": 
                self._close_all(f"🧹 换防清场：{close_reason}")
            elif raw_action in ["LONG", "SHORT"]:
                self.last_tv_side = raw_action
                self._save_state()
                self._handle_smart_entry(raw_action)
        finally:
            self._lock.release()

    def _handle_smart_entry(self, action):
        logger.info(f"⚡ 收到建仓信号 [{action}]，启动绝对先平后开机制")
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)

        current_pos = self._get_active_position()
        if current_pos and current_pos.get('size', 0) > 0:
            current_side = "LONG" if current_pos["posSide"] == "long" else "SHORT"
            self._close_all("同方向新指令到达，触发【先平后开】洗清旧阵地" if current_side == action else "反方向指令到达，触发【先平后开】原子对冲换防")
            time.sleep(1.2)

        for _ in range(3):
            pos = self._get_active_position()
            if not pos or int(pos.get('size', 0)) == 0: break
            deepcoin_client.cancel_all_open_orders(self.symbol)
            deepcoin_client._request("POST", "/trade/batch-close-position", {"productGroup": "SwapU", "instId": self.symbol})
            time.sleep(1.2)

        curr_px = deepcoin_client.get_current_price(self.symbol)
        if curr_px > 0: self._open_position(action, curr_px)

    def _open_position(self, side, curr_px):
        cfg = self.regime_settings[self.regime]
        qty = max(int((deepcoin_client.get_available_balance() * cfg["margin"] * self.leverage) / (curr_px * self.face_value)), 1)

        open_side, pos_side = ("buy", "long") if side == "LONG" else ("sell", "short")
        logger.info(f"🚀 [唯一主仓] 开仓: {open_side} {qty}张 | Regime {self.regime}")
        deepcoin_client.place_market_order(self.symbol, open_side, pos_side, qty)
        time.sleep(2.0)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self.current_side = side
            self.initial_qty = self.watched_qty = int(pos['size'])
            self.best_price = self.watched_entry = pos['entry_price']
            self._protect_and_monitor(self.watched_qty, self.watched_entry)

    def _protect_and_monitor(self, qty, entry_price):
        cfg = self.regime_settings[self.regime]
        close_side, pos_side = ("sell", "long") if self.current_side == "LONG" else ("buy", "short")
        qty1, qty2, qty3 = self._calculate_tp_quantities(qty, cfg["ratios"])

        tp_pxs = self.tv_tps 
        self.current_sl = entry_price 

        if qty1 > 0 and tp_pxs[0] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[0], qty1, reduce_only=True)
        if qty2 > 0 and tp_pxs[1] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[1], qty2, reduce_only=True)
        if qty3 > 0 and tp_pxs[2] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[2], qty3, reduce_only=True)

        self.monitoring = True
        self._save_state()
        dingtalk.report_supervisor_open(self.current_side, entry_price, self.tv_price, qty, tp_pxs, self.current_atr, self.regime)
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                if not self._lock.acquire(timeout=2.0): continue
                try:
                    pos = self._get_active_position()
                    actual_qty = int(pos['size']) if pos else 0
                    actual_side = "LONG" if pos and pos.get('posSide') == "long" else "SHORT"
                    
                    if actual_qty == 0:
                        if self.watched_qty > 0: self._close_all("仓位归零 (达到目标止盈或人工全平)")
                        break

                    if actual_side != self.last_tv_side:
                        self._close_all(f"致命方向背离：实盘({actual_side}) vs TV({self.last_tv_side})")
                        dingtalk.report_force_align(actual_side, self.last_tv_side)
                        break

                    if actual_qty != self.watched_qty and actual_qty > 0:
                        old_qty = self.watched_qty
                        self.watched_qty = actual_qty
                        self.watched_entry = pos['entry_price']
                        logger.info(f"🔄 [智慧大脑] 感知到仓位变化: {old_qty} ➔ {actual_qty}，重新重构防线！")
                        self._save_state()
                        
                        deepcoin_client.cancel_all_open_orders(self.symbol)
                        time.sleep(0.5)
                        sl_to_pass = self.current_sl if (self.current_side == "LONG" and self.current_sl > self.watched_entry) or (self.current_side == "SHORT" and self.current_sl < self.watched_entry) else None
                        self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=sl_to_pass)
                        dingtalk.report_manual_position_change("手动加仓" if actual_qty > old_qty else "部分止盈吃单 / 手动减仓", old_qty, actual_qty, self.watched_entry)

                    curr_px = deepcoin_client.get_current_price(self.symbol)
                    self.best_price = max(self.best_price, curr_px) if self.current_side == "LONG" else min(self.best_price, curr_px)
                    
                    # ========================================================
                    # 🎯 智慧雷达触发计算 (双轨保本锁润机制)
                    # ========================================================
                    tp1_dist = abs(self.tv_tps[0] - self.watched_entry) if self.tv_tps[0] > 0 else self.current_atr * 1.5
                    
                    cfg = self.regime_settings[self.regime]
                    activation_ratio = cfg["activation"]
                    trail_atr_multiplier = cfg["trail_offset"]

                    required = self.watched_entry + (tp1_dist * activation_ratio) if self.current_side == "LONG" else self.watched_entry - (tp1_dist * activation_ratio)
                    has_moved_favorably = curr_px >= required if self.current_side == "LONG" else curr_px <= required

                    if has_moved_favorably:
                        trail_offset = self.current_atr * trail_atr_multiplier
                        fee_buffer = self.watched_entry * 0.0015 

                        if self.current_side == "LONG":
                            # 🚀 保险升级：保本底线强制 2 位小数
                            breakeven_floor = round(self.watched_entry + fee_buffer, 2)
                            new_sl = max(round(self.best_price - trail_offset, 2), breakeven_floor) 
                            
                            if new_sl > self.current_sl + 1.0:
                                deepcoin_client.cancel_all_open_orders(self.symbol)
                                time.sleep(0.5)
                                self.current_sl = new_sl
                                self._save_state()
                                self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=new_sl)
                                dingtalk.report_intervention(actual_qty, self.watched_entry, new_sl, f"🚀 档位{self.regime} 雷达激活：保本盾升起，锁润底线物理推升！")
                        else:
                            # 🚀 保险升级：保本底线强制 2 位小数
                            breakeven_floor = round(self.watched_entry - fee_buffer, 2)
                            new_sl = min(round(self.best_price + trail_offset, 2), breakeven_floor)
                            
                            if self.current_sl >= self.watched_entry or new_sl < self.current_sl - 1.0:
                                deepcoin_client.cancel_all_open_orders(self.symbol)
                                time.sleep(0.5)
                                self.current_sl = new_sl
                                self._save_state()
                                self._rebuild_defenses(actual_qty, self.watched_entry, dynamic_sl=new_sl)
                                dingtalk.report_intervention(actual_qty, self.watched_entry, new_sl, f"🚀 档位{self.regime} 雷达激活：保本盾降下，锁润顶线物理下压！")
                finally:
                    self._lock.release()
            except Exception as e: logger.error(f"哨兵异常: {e}")
            time.sleep(6) 

    def _rebuild_defenses(self, qty, entry, dynamic_sl=None):
        close_side, pos_side = ("sell", "long") if self.current_side == "LONG" else ("buy", "short")
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.4)

        qty1, qty2, qty3 = self._calculate_tp_quantities(qty, self.regime_settings[self.regime]["ratios"])
        tp_pxs = self.tv_tps 

        if qty1 > 0 and tp_pxs[0] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[0], qty1, reduce_only=True)
        if qty2 > 0 and tp_pxs[1] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[1], qty2, reduce_only=True)
        if qty3 > 0 and tp_pxs[2] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[2], qty3, reduce_only=True)
        
        if dynamic_sl: deepcoin_client.place_stop_market_order(self.symbol, close_side, pos_side, dynamic_sl)

    def _close_all(self, reason=""):
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        for _ in range(5):
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0: break
            deepcoin_client._request("POST", "/trade/batch-close-position", {"productGroup": "SwapU", "instId": self.symbol})
            time.sleep(1.5)

        self.monitoring, self.watched_qty = False, 0
        self._save_state()
        deepcoin_client.cancel_all_open_orders(self.symbol)
        dingtalk.report_supervisor_close(reason)

    def recover_state_on_startup(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f: 
                    s = json.load(f)
                    self.last_tv_side = s.get("last_tv_side")
                    self.tv_tps = s.get("tv_tps", [0.0, 0.0, 0.0])
            pos = self._get_active_position()
            if pos and pos.get('size', 0) > 0:
                self.current_side = "LONG" if pos.get('posSide') == "long" else "SHORT"
                if not self.last_tv_side: self.last_tv_side = self.current_side
                self.watched_qty = self.initial_qty = int(pos['size'])
                self.watched_entry = self.best_price = self.current_sl = pos['entry_price']
                self.monitoring = True
                threading.Thread(target=self._sentinel_loop, daemon=True).start()
        except: pass

position_supervisor = PositionSupervisor()
position_supervisor.recover_state_on_startup()
