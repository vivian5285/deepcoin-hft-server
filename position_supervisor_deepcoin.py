#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging, time, threading, os, json
from logging.handlers import RotatingFileHandler
from deepcoin_client import deepcoin_client
import dingtalk

if not os.path.exists('logs'): os.makedirs('logs')
handler = RotatingFileHandler('logs/deepcoin_brain.log', maxBytes=5*1024*1024, backupCount=3)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Brain: %(message)s', handlers=[handler, logging.StreamHandler()])
logger = logging.getLogger(__name__)

class PositionSupervisor:
    def __init__(self):
        self.symbol = "ETH-USDT-SWAP"
        self.monitoring = False
        self._lock = threading.Lock()

        # 🚀 对齐150分钟策略比例
        self.regime_settings = {
            1: {"margin": 0.15, "ratios": [0.25, 0.35, 0.40], "trail": 0.55},
            2: {"margin": 0.25, "ratios": [0.20, 0.35, 0.45], "trail": 0.60},
            3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "trail": 0.65},
            4: {"margin": 0.50, "ratios": [0.05, 0.20, 0.75], "trail": 0.70}
        }
        self.leverage = 20
        self.face_value = 0.1 # 深币 ETH 面值通常为 0.1 或类似，请确保资金够下整数张

        self.regime = 3
        self.current_atr = 30.0
        self.best_price = 0.0
        self.current_sl = 0.0
        self.tv_price = 0.0
        self.tv_tps = [0.0, 0.0, 0.0] # 承接 TV 的止盈数据

        self.initial_qty = 0
        self.watched_qty = 0
        self.watched_entry = 0.0
        
        self.current_side = None
        self.last_tv_side = None
        
        self.state_file = 'deepcoin_vps_state.json'
        logger.info("🧠 深币 VPS [绝对服从TV指令版] 已加载：精准挂载TV止盈单！")

    def _save_state(self):
        try:
            with open(self.state_file, 'w') as f: 
                json.dump({"last_tv_side": self.last_tv_side, "current_side": self.current_side, "watched_qty": self.watched_qty, "watched_entry": self.watched_entry, "current_sl": self.current_sl, "monitoring": self.monitoring}, f)
        except: pass

    def _get_active_position(self):
        res = deepcoin_client.get_position_info(self.symbol)
        if res and 'data' in res:
            for p in res['data']:
                if int(p.get("pos", 0)) > 0:
                    return {"size": int(p.get("pos")), "entry_price": round(float(p.get("avgPx", p.get("price", 0))), 2), "posSide": p.get("posSide", "long").lower()}
        return None

    def handle_signal(self, payload):
        raw_action = payload.get("action", "").upper()
        self.regime = int(payload.get("regime", 3))
        if self.regime not in self.regime_settings: self.regime = 3
        
        self.current_atr = float(payload.get("atr", 30.0))
        self.tv_price = float(payload.get("price", 0.0))
        
        # 🚀 核心：精准提取 TV 传来的 3 个止盈位数据
        self.tv_tps = [float(payload.get("tv_tp1", 0)), float(payload.get("tv_tp2", 0)), float(payload.get("tv_tp3", 0))]

        if not raw_action: return
        if not self._lock.acquire(timeout=10.0): return

        try:
            self.monitoring = False
            if raw_action.startswith("CLOSE_PROTECT"):
                reason = raw_action.split("|")[1] if "|" in raw_action else "策略指标反转/波动率安全退出"
                self._close_all(f"🛡️ 保护性全平：{reason}")
            elif raw_action == "CLOSE_TP3": 
                self._close_all("🎯 完美胜利：大趋势吃满，TP3 终极收网")
            elif raw_action == "CLOSE": 
                self._close_all(f"🧹 换防清场：{payload.get('reason', '常规平仓指令')}")
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

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            current_side = "LONG" if pos["posSide"] == "long" else "SHORT"
            if current_side == action:
                self._close_all("同方向新指令到达，触发【先平后开】洗清旧阵地")
            else:
                self._close_all("反方向指令到达，触发【先平后开】原子对冲换防")
            time.sleep(1.2)

        curr_px = deepcoin_client.get_current_price(self.symbol)
        if curr_px > 0:
            self._open_position(action, curr_px)

    def _open_position(self, action, curr_px):
        balance = deepcoin_client.get_available_balance()
        margin_pct = self.regime_settings[self.regime]["margin"]

        # 计算张数 = (余额 * 仓位利用率 * 杠杆) / (价格 * 面值)
        qty = max(int((balance * margin_pct * self.leverage) / (curr_px * self.face_value)), 1)
        
        open_side = "buy" if action == "LONG" else "sell"
        pos_side = "long" if action == "LONG" else "short"
        
        logger.info(f"🚀 极速开仓: {open_side} {qty}张 (持仓方向: {pos_side}) | 档位 {self.regime}")
        deepcoin_client.place_market_order(self.symbol, open_side, pos_side, qty)
        time.sleep(2.0)

        pos = self._get_active_position()
        if pos and pos.get('size', 0) > 0:
            self.current_side = action
            real_qty = int(pos['size'])
            self.initial_qty = real_qty
            self._protect_and_monitor(real_qty, pos['entry_price'])

    def _protect_and_monitor(self, qty, entry_price):
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"
        
        cfg = self.regime_settings[self.regime]
        ratios = cfg["ratios"]

        # 🚀 张数余数吸收机制：确保 qty1+qty2+qty3 绝对等于总张数
        qty1 = int(qty * ratios[0])
        qty2 = int(qty * ratios[1])
        qty3 = int(qty - qty1 - qty2)

        # 🚀 绝对使用 TV 传来的数据作为止盈点！
        tp_pxs = [round(self.tv_tps[0], 2), round(self.tv_tps[1], 2), round(self.tv_tps[2], 2)]

        # 深币挂单要求
        if qty1 > 0 and tp_pxs[0] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[0], qty1, reduce_only=True)
        if qty2 > 0 and tp_pxs[1] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[1], qty2, reduce_only=True)
        if qty3 > 0 and tp_pxs[2] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[2], qty3, reduce_only=True)
        
        # 初始防灾止损单 (Trigger Order)
        sl_price = round(entry_price - self.current_atr * 1.5, 2) if self.current_side == "LONG" else round(entry_price + self.current_atr * 1.5, 2)
        self.current_sl = sl_price
        
        deepcoin_client._request("POST", "/trade/trigger-order", {
            "instId": self.symbol, "productGroup": "Swap", "sz": str(int(qty)),
            "side": close_side, "posSide": pos_side, "isCrossMargin": "1",
            "orderType": "market", "triggerPrice": str(self.current_sl),
            "mrgPosition": "merge", "tdMode": "cross"
        })

        self.best_price = entry_price
        self.watched_qty, self.watched_entry, self.monitoring = qty, entry_price, True
        self._save_state()
        
        # 将 TV 传来的数据打入钉钉战报核对
        dingtalk.report_supervisor_open(self.current_side, entry_price, self.tv_price, qty, tp_pxs, self.current_atr, self.regime, self.tv_tps)
        threading.Thread(target=self._sentinel_loop, daemon=True).start()

    def _sentinel_loop(self):
        while self.monitoring:
            try:
                if not self._lock.acquire(timeout=2.0): continue
                try:
                    pos = self._get_active_position()
                    real_amt = int(pos.get("size", 0)) if pos else 0
                    actual_side = "LONG" if pos and pos.get('posSide') == "long" else "SHORT"
                    
                    if real_amt == 0:
                        if self.watched_qty > 0:
                            self._close_all("仓位归零 (达到目标止盈或人工全平)")
                        break

                    if actual_side != self.last_tv_side:
                        self._close_all(f"致命方向背离：实盘({actual_side}) vs TV({self.last_tv_side})")
                        dingtalk.report_force_align(actual_side, self.last_tv_side)
                        break

                    # 强大的态势感知
                    if abs(real_amt - self.watched_qty) != 0:
                        old_qty = self.watched_qty
                        self.watched_qty = real_amt
                        self.watched_entry = pos['entry_price']
                        
                        logger.info(f"🔄 [智慧大脑] 感知到人工加减仓或吃单: {old_qty} ➔ {real_amt}，重新重构防线！")
                        deepcoin_client.cancel_all_open_orders(self.symbol)
                        time.sleep(0.5)
                        
                        self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=self.current_sl)
                        
                        action_msg = "手动加仓" if real_amt > old_qty else "手动减仓(或部分吃单)"
                        dingtalk.report_manual_position_change(action_msg, old_qty, real_amt, self.watched_entry)

                    curr_px = deepcoin_client.get_current_price(self.symbol)
                    self.best_price = max(self.best_price, curr_px) if self.current_side == "LONG" else min(self.best_price, curr_px)

                    trail_factor = self.regime_settings[self.regime]["trail"]
                    activation_ratio = 0.55 
                    
                    # 以 TV TP1 为基准测算行进距离
                    tp1_dist = abs(self.tv_tps[0] - self.watched_entry)
                    if tp1_dist <= 0: tp1_dist = self.current_atr * 1.5

                    required = self.watched_entry + tp1_dist * activation_ratio if self.current_side == "LONG" else self.watched_entry - tp1_dist * activation_ratio
                    has_moved_favorably = curr_px >= required if self.current_side == "LONG" else curr_px <= required

                    if has_moved_favorably:
                        trail_offset = self.current_atr * trail_factor * 0.45
                        if self.current_side == "LONG":
                            new_sl = max(round(self.best_price - trail_offset, 2), self.watched_entry + 0.5)
                            if new_sl > self.current_sl + 1.0:
                                deepcoin_client.cancel_all_open_orders(self.symbol)
                                time.sleep(0.5)
                                self.current_sl = new_sl
                                self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=new_sl)
                                dingtalk.report_intervention(real_amt, self.watched_entry, new_sl, "🚀 雷达激活：锁润硬防线已物理推升！")
                        else:
                            new_sl = min(round(self.best_price + trail_offset, 2), self.watched_entry - 0.5)
                            if self.current_sl > self.watched_entry or new_sl < self.current_sl - 1.0:
                                deepcoin_client.cancel_all_open_orders(self.symbol)
                                time.sleep(0.5)
                                self.current_sl = new_sl
                                self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=new_sl)
                                dingtalk.report_intervention(real_amt, self.watched_entry, new_sl, "🚀 雷达激活：锁润硬防线已物理下压！")
                finally:
                    self._lock.release()
            except Exception as e: logger.error(f"哨兵异常: {e}")
            time.sleep(4)

    def _rebuild_defenses(self, qty, entry, dynamic_sl=None):
        close_side = "sell" if self.current_side == "LONG" else "buy"
        pos_side = "long" if self.current_side == "LONG" else "short"
        cfg = self.regime_settings[self.regime]
        ratios = cfg["ratios"]

        qty1 = int(qty * ratios[0])
        qty2 = int(qty * ratios[1])
        qty3 = int(qty - qty1 - qty2)

        tp_pxs = [round(self.tv_tps[0], 2), round(self.tv_tps[1], 2), round(self.tv_tps[2], 2)]

        if qty1 > 0 and tp_pxs[0] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[0], qty1, reduce_only=True)
        if qty2 > 0 and tp_pxs[1] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[1], qty2, reduce_only=True)
        if qty3 > 0 and tp_pxs[2] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[2], qty3, reduce_only=True)
        
        if dynamic_sl:
            deepcoin_client._request("POST", "/trade/trigger-order", {
                "instId": self.symbol, "productGroup": "Swap", "sz": str(int(qty)),
                "side": close_side, "posSide": pos_side, "isCrossMargin": "1",
                "orderType": "market", "triggerPrice": str(dynamic_sl),
                "mrgPosition": "merge", "tdMode": "cross"
            })

    def _close_all(self, reason=""):
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.5)
        closed_successfully = False
        
        for _ in range(5):
            pos = self._get_active_position()
            if not pos or int(pos.get("size", 0)) == 0:
                closed_successfully = True
                break
                
            close_side = "sell" if pos["posSide"] == "long" else "buy"
            deepcoin_client.place_market_order(self.symbol, close_side, pos["posSide"], int(pos["size"]), reduce_only=True)
            time.sleep(1.5)
            
        self.monitoring, self.watched_qty = False, 0
        self._save_state()
        deepcoin_client.cancel_all_open_orders(self.symbol) 
        if reason and closed_successfully: dingtalk.report_supervisor_close(reason)

    def recover_state_on_startup(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    s = json.load(f)
                    self.last_tv_side = s.get("last_tv_side")

            pos = self._get_active_position()
            if pos and int(pos.get("size", 0)) != 0:
                real_amt = int(pos["size"])
                self.current_side = "LONG" if pos.get("posSide") == "long" else "SHORT"
                if not self.last_tv_side: self.last_tv_side = self.current_side 
                self.watched_qty = self.initial_qty = real_amt
                self.watched_entry = self.best_price = float(pos["entry_price"])
                self.current_sl = self.watched_entry 
                self.monitoring = True
                threading.Thread(target=self._sentinel_loop, daemon=True).start()
        except: pass

position_supervisor = PositionSupervisor()
position_supervisor.recover_state_on_startup()
