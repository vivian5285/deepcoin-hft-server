# ==================== 🚀 V9.2 智能重试核武清场 ====================
    def _close_all(self, reason=""):
        logger.warning(f"🔨 启动核武级全平: {reason}")
        
        # 第一波：激进清场 (带退避保护的撤单)
        deepcoin_client.cancel_all_open_orders(self.symbol)
        time.sleep(0.6) # 给深币服务器同步订单状态的时间
        
        for attempt in range(5):
            pos = self._get_active_position()
            if not pos or pos.get('size', 0) == 0: 
                break # 干净了，退出爆破
                
            qty = int(pos['size'])
            pos_side = pos['posSide'] 
            close_side = "sell" if pos_side == "long" else "buy"
            
            logger.info(f"🔨 第 {attempt+1} 次物理全平: {close_side} {qty}张")
            
            # 强杀前，保险起见再撤一次单，防止雷达残留
            deepcoin_client.cancel_all_open_orders(self.symbol)
            time.sleep(0.3)
            
            deepcoin_client.place_market_order(self.symbol, close_side, pos_side, qty, reduce_only=True)
            # 随着重试次数增加，给足 API 喘息和同步的时间
            time.sleep(1.5 + attempt * 0.5) 
                
        # 终极扫尾
        deepcoin_client.cancel_all_open_orders(self.symbol) 
        final_pos = self._get_active_position()
        self.monitoring, self.radar_activated, self.watched_qty = False, False, 0
        self._save_state()
        
        if not final_pos or final_pos.get('size', 0) == 0:
            if reason: dingtalk.report_deepcoin_clear(reason, "✅ 5轮核武器全平成功")
        else:
            dingtalk.report_system_alert("⚠️ 清仓失败", f"已执行5次爆破对冲，仍有残留: {final_pos.get('size')} 张，建议人工介入！")
