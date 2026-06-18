# strategy_engine.py 核心结构示例
import requests
import json
from deepcoin_client import deepcoin_client

DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"

def send_dingtalk(msg):
    requests.post(DINGTALK_WEBHOOK, json={"msgtype": "text", "text": {"content": f"【战神监控】{msg}"}})

def execute_order(symbol, side, price, amount):
    # 1. 检查当前持仓
    position = deepcoin_client.get_position(symbol) 
    if position > 0 and side == "LONG":
        return "已有持仓，忽略重复开单"
    
    # 2. 执行限价下单
    res = deepcoin_client.place_limit_order(symbol, side, price, amount)
    
    # 3. 钉钉推送
    send_dingtalk(f"执行下单: {side} {amount} 手, 价格: {price}")
    return res
