#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# position_supervisor_deepcoin.py (终极雷达接管+最小1张优化版)
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

        # 🚀 对齐150分钟策略比例[cite: 19]
        self.regime_settings = {
            1: {"margin": 0.15, "ratios": [0.25, 0.35, 0.40], "trail": 0.55},
            2: {"margin": 0.25, "ratios": [0.20, 0.35, 0.45], "trail": 0.60},
            3: {"margin": 0.35, "ratios": [0.18, 0.32, 0.50], "trail": 0.65},
            4: {"margin": 0.50, "ratios": [0.05, 0.20, 0.75], "trail": 0.70}
        }
        self.leverage = 20[cite: 19]
        self.face_value = 0.1[cite: 19] 

        self.regime = 3[cite: 19]
        self.current_atr = 30.0[cite: 19]
        self.best_price = 0.0[cite: 19]
        self.current_sl = 0.0[cite: 19]
        self.tv_price = 0.0[cite: 19]
        self.tv_tps = [0.0, 0.0, 0.0][cite: 19]

        self.initial_qty = 0[cite: 19]
        self.watched_qty = 0[cite: 19]
        self.watched_entry = 0.0[cite: 19]
        
        self.current_side = None[cite: 19]
        self.last_tv_side = None[cite: 19]
        
        self.state_file = 'deepcoin_vps_state.json'[cite: 19]
        logger.info("🧠 深币 VPS [无硬止损-雷达智能闪电接管版] 已加载！")

    def _save_state(self):
        """全面增强状态留存，确保重启后雷达能完美复原上下文"""
        try:
            with open(self.state_file, 'w') as f: 
                json.dump({
                    "last_tv_side": self.last_tv_side, 
                    "current_side": self.current_side, 
                    "watched_qty": self.watched_qty, 
                    "watched_entry": self.watched_entry, 
                    "current_sl": self.current_sl, 
                    "monitoring": self.monitoring,
                    "regime": self.regime,
                    "current_atr": self.current_atr,
                    "tv_tps": self.tv_tps,
                    "best_price": self.best_price
                }, f)
        except: pass

    def _get_active_position(self):[cite: 19]
        res = deepcoin_client.get_position_info(self.symbol)[cite: 19]
        if res and 'data' in res:[cite: 19]
            for p in res['data']:[cite: 19]
                if int(p.get("pos", 0)) > 0:[cite: 19]
                    return {"size": int(p.get("pos")), "entry_price": round(float(p.get("avgPx", p.get("price", 0))), 2), "posSide": p.get("posSide", "long").lower()}[cite: 19]
        return None[cite: 19]

    def _calculate_tp_quantities(self, total_qty: int, ratios: list) -> tuple:
        """核心修复：解决深币最小1张挂单限制造成的丢单漏单问题"""
        if total_qty <= 0: return 0, 0, 0
        
        # 强制第一档至少分配 1 张
        qty1 = max(1, round(total_qty * ratios[0]))
        remaining = total_qty - qty1
        
        if remaining <= 0: return qty1, 0, 0
        
        ratio_sum_23 = ratios[1] + ratios[2]
        if ratio_sum_23 <= 0: return qty1, 0, remaining
        
        qty2 = max(0, round(remaining * (ratios[1] / ratio_sum_23)))
        qty3 = remaining - qty2
        
        if qty3 < 0: qty3, qty2 = 0, remaining
        
        # 边界微调：防止因四舍五入造成中后档位出现 0 张情况
        if qty2 == 0 and remaining >= 2: qty2, qty3 = 1, remaining - 1
        if qty3 == 0 and remaining >= 2 and qty2 > 1: qty3, qty2 = 1, remaining - 1
        
        return qty1, qty2, qty3

    def handle_signal(self, payload):[cite: 19]
        raw_action = payload.get("action", "").upper()[cite: 19]
        self.regime = int(payload.get("regime", 3))[cite: 19]
        if self.regime not in self.regime_settings: self.regime = 3[cite: 19]
        
        self.current_atr = float(payload.get("atr", 30.0))[cite: 19]
        self.tv_price = float(payload.get("price", 0.0))[cite: 19]
        self.tv_tps = [float(payload.get("tv_tp1", 0)), float(payload.get("tv_tp2", 0)), float(payload.get("tv_tp3", 0))][cite: 19]

        if not raw_action: return[cite: 19]
        if not self._lock.acquire(timeout=10.0): return[cite: 19]

        try:
            self.monitoring = False[cite: 19]
            if raw_action.startswith("CLOSE_PROTECT"):[cite: 19]
                reason = raw_action.split("|")[1] if "|" in raw_action else "策略指标反转/波动率安全退出"[cite: 19]
                self._close_all(f"🛡️ 保护性全平：{reason}")[cite: 19]
            elif raw_action == "CLOSE_TP3":[cite: 19]
                self._close_all("🎯 完美胜利：大趋势吃满，TP3 终极收网")[cite: 19]
            elif raw_action == "CLOSE":[cite: 19]
                self._close_all(f"🧹 换防清场：{payload.get('reason', '常规平仓指令')}")[cite: 19]
            elif raw_action in ["LONG", "SHORT"]:[cite: 19]
                self.last_tv_side = raw_action[cite: 19]
                self._save_state()[cite: 19]
                self._handle_smart_entry(raw_action)[cite: 19]
        finally:
            self._lock.release()[cite: 19]

    def _handle_smart_entry(self, action):[cite: 19]
        logger.info(f"⚡ 收到建仓信号 [{action}]，启动绝对先平后开机制")[cite: 19]
        deepcoin_client.cancel_all_open_orders(self.symbol)[cite: 19]
        time.sleep(0.5)[cite: 19]

        pos = self._get_active_position()[cite: 19]
        if pos and pos.get('size', 0) > 0:[cite: 19]
            current_side = "LONG" if pos["posSide"] == "long" else "SHORT"[cite: 19]
            if current_side == action:[cite: 19]
                self._close_all("同方向新指令到达，触发【先平后开】洗清旧阵地")[cite: 19]
            else:[cite: 19]
                self._close_all("反方向指令到达，触发【先平后开】原子对冲换防")[cite: 19]
            time.sleep(1.2)[cite: 19]

        curr_px = deepcoin_client.get_current_price(self.symbol)[cite: 19]
        if curr_px > 0:[cite: 19]
            self._open_position(action, curr_px)[cite: 19]

    def _open_position(self, action, curr_px):[cite: 19]
        balance = deepcoin_client.get_available_balance()[cite: 19]
        margin_pct = self.regime_settings[self.regime]["margin"][cite: 19]

        qty = max(int((balance * margin_pct * self.leverage) / (curr_px * self.face_value)), 1)[cite: 19]
        open_side = "buy" if action == "LONG" else "sell"[cite: 19]
        pos_side = "long" if action == "LONG" else "short"[cite: 19]
        
        logger.info(f"🚀 极速开仓: {open_side} {qty}张 (持仓方向: {pos_side}) | 档位 {self.regime}")[cite: 19]
        deepcoin_client.place_market_order(self.symbol, open_side, pos_side, qty)[cite: 19]
        time.sleep(2.0)[cite: 19]

        pos = self._get_active_position()[cite: 19]
        if pos and pos.get('size', 0) > 0:[cite: 19]
            self.current_side = action[cite: 19]
            real_qty = int(pos['size'])[cite: 19]
            self.initial_qty = real_qty[cite: 19]
            self._protect_and_monitor(real_qty, pos['entry_price'])[cite: 19]

    def _protect_and_monitor(self, qty, entry_price):[cite: 19]
        close_side = "sell" if self.current_side == "LONG" else "buy"[cite: 19]
        pos_side = "long" if self.current_side == "LONG" else "short"[cite: 19]
        
        # 使用防漏单算法切分张数
        qty1, qty2, qty3 = self._calculate_tp_quantities(qty, self.regime_settings[self.regime]["ratios"])
        tp_pxs = [round(self.tv_tps[0], 2), round(self.tv_tps[1], 2), round(self.tv_tps[2], 2)][cite: 19]

        # 严格执行挂限价单止盈
        if qty1 > 0 and tp_pxs[0] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[0], qty1, reduce_only=True)[cite: 19]
        if qty2 > 0 and tp_pxs[1] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[1], qty2, reduce_only=True)[cite: 19]
        if qty3 > 0 and tp_pxs[2] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[2], qty3, reduce_only=True)[cite: 19]
        
        # 🚀 核心对齐：遵循全域无初始硬止损战略，不挂物理触发单，以成本价初始化雷达标尺
        self.current_sl = entry_price

        self.best_price = entry_price[cite: 19]
        self.watched_qty, self.watched_entry, self.monitoring = qty, entry_price, True[cite: 19]
        self._save_state()[cite: 19]
        
        dingtalk.report_supervisor_open(self.current_side, entry_price, self.tv_price, qty, tp_pxs, self.current_atr, self.regime, self.tv_tps)[cite: 19]
        threading.Thread(target=self._sentinel_loop, daemon=True).start()[cite: 19]

    def _sentinel_loop(self):[cite: 19]
        while self.monitoring:[cite: 19]
            try:
                if not self._lock.acquire(timeout=2.0): continue[cite: 19]
                try:
                    pos = self._get_active_position()[cite: 19]
                    real_amt = int(pos.get("size", 0)) if pos else 0[cite: 19]
                    actual_side = "LONG" if pos and pos.get('posSide') == "long" else "SHORT"[cite: 19]
                    
                    if real_amt == 0:[cite: 19]
                        if self.watched_qty > 0:[cite: 19]
                            self._close_all("仓位归零 (达到目标止盈或人工全平)")[cite: 19]
                        break[cite: 19]

                    if actual_side != self.last_tv_side:[cite: 19]
                        self._close_all(f"致命方向背离：实盘({actual_side}) vs TV({self.last_tv_side})")[cite: 19]
                        dingtalk.report_force_align(actual_side, self.last_tv_side)[cite: 19]
                        break[cite: 19]

                    # 🚀 人工异动正行为处理（人工加减仓或全平后挂单重建）
                    if abs(real_amt - self.watched_qty) != 0:[cite: 19]
                        old_qty = self.watched_qty[cite: 19]
                        self.watched_qty = real_amt[cite: 19]
                        self.watched_entry = pos['entry_price'][cite: 19]
                        
                        logger.info(f"🔄 [智慧大脑] 感知到阵地数量变化: {old_qty} ➔ {real_amt}，打扫战场并重新挂单！")[cite: 19]
                        deepcoin_client.cancel_all_open_orders(self.symbol)[cite: 19]
                        time.sleep(0.5)[cite: 19]
                        
                        # 重新计算是否需要维持已经推升的雷达止损
                        sl_to_pass = self.current_sl if (self.current_side == "LONG" and self.current_sl > self.watched_entry) or (self.current_side == "SHORT" and self.current_sl < self.watched_entry) else None
                        self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=sl_to_pass)[cite: 19]
                        
                        action_msg = "手动加仓" if real_amt > old_qty else "手动减仓(或部分吃单)"[cite: 19]
                        dingtalk.report_manual_position_change(action_msg, old_qty, real_amt, self.watched_entry)[cite: 19]

                    curr_px = deepcoin_client.get_current_price(self.symbol)[cite: 19]
                    self.best_price = max(self.best_price, curr_px) if self.current_side == "LONG" else min(self.best_price, curr_px)[cite: 19]

                    trail_factor = self.regime_settings[self.regime]["trail"][cite: 19]
                    activation_ratio = 0.55[cite: 19] 
                    
                    # 以 TV TP1 为基准测算行进距离[cite: 19]
                    tp1_dist = abs(self.tv_tps[0] - self.watched_entry) if self.tv_tps[0] > 0 else self.current_atr * 1.5[cite: 19]

                    required = self.watched_entry + tp1_dist * activation_ratio if self.current_side == "LONG" else self.watched_entry - tp1_dist * activation_ratio[cite: 19]
                    has_moved_favorably = curr_px >= required if self.current_side == "LONG" else curr_px <= required[cite: 19]

                    if has_moved_favorably:[cite: 19]
                        trail_offset = self.current_atr * trail_factor * 0.45[cite: 19]
                        if self.current_side == "LONG":[cite: 19]
                            new_sl = max(round(self.best_price - trail_offset, 2), self.watched_entry + 0.5)[cite: 19]
                            # 确保激活条件顺畅触发（首次激活由于 current_sl == entry_price 必然触发）
                            if new_sl > self.current_sl + 1.0 or self.current_sl == self.watched_entry:[cite: 19]
                                binance_open_orders_dummy = deepcoin_client.cancel_all_open_orders(self.symbol)[cite: 19]
                                time.sleep(0.5)[cite: 19]
                                self.current_sl = new_sl[cite: 19]
                                self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=new_sl)[cite: 19]
                                self._save_state()
                                dingtalk.report_intervention(real_amt, self.watched_entry, new_sl, "🚀 雷达激活：锁润硬防线已物理推升！")[cite: 19]
                        else:[cite: 19]
                            new_sl = min(round(self.best_price + trail_offset, 2), self.watched_entry - 0.5)[cite: 19]
                            if self.current_sl >= self.watched_entry or new_sl < self.current_sl - 1.0:[cite: 19]
                                deepcoin_client.cancel_all_open_orders(self.symbol)[cite: 19]
                                time.sleep(0.5)[cite: 19]
                                self.current_sl = new_sl[cite: 19]
                                self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=new_sl)[cite: 19]
                                self._save_state()
                                dingtalk.report_intervention(real_amt, self.watched_entry, new_sl, "🚀 雷达激活：锁润硬防线已物理下压！")[cite: 19]
                finally:
                    self._lock.release()[cite: 19]
            except Exception as e: logger.error(f"哨兵异常: {e}")[cite: 19]
            time.sleep(4)[cite: 19]

    def _rebuild_defenses(self, qty, entry, dynamic_sl=None):[cite: 19]
        close_side = "sell" if self.current_side == "LONG" else "buy"[cite: 19]
        pos_side = "long" if self.current_side == "LONG" else "short"[cite: 19]
        
        # 使用防丢单分配数量
        qty1, qty2, qty3 = self._calculate_tp_quantities(qty, self.regime_settings[self.regime]["ratios"])
        tp_pxs = [round(self.tv_tps[0], 2), round(self.tv_tps[1], 2), round(self.tv_tps[2], 2)][cite: 19]

        if qty1 > 0 and tp_pxs[0] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[0], qty1, reduce_only=True)[cite: 19]
        if qty2 > 0 and tp_pxs[1] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[1], qty2, reduce_only=True)[cite: 19]
        if qty3 > 0 and tp_pxs[2] > 0: deepcoin_client.place_limit_order(self.symbol, close_side, pos_side, tp_pxs[2], qty3, reduce_only=True)[cite: 19]
        
        # 仅当雷达确切激活并传递保本点时，才物理挂出止损单
        if dynamic_sl and dynamic_sl != entry:
            deepcoin_client._request("POST", "/trade/trigger-order", {
                "instId": self.symbol, "productGroup": "Swap", "sz": str(int(qty)),
                "side": close_side, "posSide": pos_side, "isCrossMargin": "1",
                "orderType": "market", "triggerPrice": str(dynamic_sl),
                "mrgPosition": "merge", "tdMode": "cross"
            })

    def _close_all(self, reason=""):[cite: 19]
        deepcoin_client.cancel_all_open_orders(self.symbol)[cite: 19]
        time.sleep(0.5)[cite: 19]
        closed_successfully = False[cite: 19]
        
        for _ in range(5):[cite: 19]
            pos = self._get_active_position()[cite: 19]
            if not pos or int(pos.get("size", 0)) == 0:[cite: 19]
                closed_successfully = True[cite: 19]
                break[cite: 19]
                
            close_side = "sell" if pos["posSide"] == "long" else "buy"[cite: 19]
            deepcoin_client.place_market_order(self.symbol, close_side, pos["posSide"], int(pos["size"]), reduce_only=True)[cite: 19]
            time.sleep(1.5)[cite: 19]
            
        self.monitoring, self.watched_qty = False, 0[cite: 19]
        self._save_state()[cite: 19]
        deepcoin_client.cancel_all_open_orders(self.symbol)[cite: 19]
        if reason and closed_successfully: dingtalk.report_supervisor_close(reason)[cite: 19]

    def recover_state_on_startup(self):
        """🚀 闪电接管逻辑：部署重启后立即清点实盘阵地，补齐未挂的止盈止损单并启动哨兵雷达"""
        try:
            # 1. 完整恢复上次存储的全部上下文
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    s = json.load(f)
                    self.last_tv_side = s.get("last_tv_side")
                    self.current_side = s.get("current_side")
                    self.current_sl = s.get("current_sl", 0.0)
                    self.regime = s.get("regime", 3)
                    self.current_atr = s.get("current_atr", 30.0)
                    self.tv_tps = s.get("tv_tps", [0.0, 0.0, 0.0])
                    self.best_price = s.get("best_price", 0.0)

            # 2. 物理探查当前交易所真实持仓
            pos = self._get_active_position()
            if pos and int(pos.get("size", 0)) != 0:
                real_amt = int(pos["size"])
                self.current_side = "LONG" if pos.get("posSide") == "long" else "SHORT"
                if not self.last_tv_side: self.last_tv_side = self.current_side 
                
                self.watched_qty = self.initial_qty = real_amt
                self.watched_entry = float(pos["entry_price"])
                if self.best_price == 0.0: self.best_price = self.watched_entry
                if self.current_sl == 0.0: self.current_sl = self.watched_entry

                logger.info(f"🔄 [系统重启点火] 触发立即接管！检测到实盘持仓: {self.current_side} {real_amt}张。正在强制刷新盘口防御机制...")
                
                # 3. 立即打碎一切挂单，重新以当前持仓为基准拉起限价止盈网与移动保本单
                deepcoin_client.cancel_all_open_orders(self.symbol)
                time.sleep(0.5)
                
                # 判断重启时，价格是否已经拉开过保本区
                sl_to_pass = None
                if self.current_side == "LONG" and self.current_sl > self.watched_entry:
                    sl_to_pass = self.current_sl
                elif self.current_side == "SHORT" and self.current_sl < self.watched_entry:
                    sl_to_pass = self.current_sl

                self._rebuild_defenses(real_amt, self.watched_entry, dynamic_sl=sl_to_pass)
                self.monitoring = True
                
                # 4. 无缝拉起哨兵监视线程
                threading.Thread(target=self._sentinel_loop, daemon=True).start()
                logger.info("  -> 🎉 实盘阵地接管完毕，TP123及雷达移动保本系统正常复位就绪。")
            else:
                logger.info("🔄 [系统重启点火] 经检查盘口干净无任何持仓，账本复位为空仓待命。")
                self.monitoring = False
                self.watched_qty = 0
                self._save_state()
        except Exception as e: 
            logger.error(f"❌ 闪电接管过程触发异常: {e}")

position_supervisor = PositionSupervisor()
position_supervisor.recover_state_on_startup()
