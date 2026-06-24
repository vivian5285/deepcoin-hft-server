#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import threading
import json
import logging
from flask import Flask, request, jsonify
from position_supervisor_deepcoin import position_supervisor

# ==================== 日志配置 ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] Flask: %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ==================== Webhook 入口 ====================
@app.route('/webhook', methods=['POST'])
def webhook():
    # 1. 尝试解析 JSON
    data = request.get_json(force=True, silent=True)

    if not data:
        try:
            raw_data = request.get_data(as_text=True)
            data = json.loads(raw_data)
        except Exception as e:
            logger.warning(f"[Webhook] JSON 解析失败: {e}")
            return jsonify({"status": "error", "message": "无效的 JSON 数据"}), 400

    # 2. 校验密钥
    secret = str(data.get("secret", "")).strip()
    expected_secret = os.getenv("WEBHOOK_SECRET", "528586")

    if secret != expected_secret:
        logger.warning("[Webhook] Secret 校验失败！")
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    action = data.get("action", "UNKNOWN")
    regime = data.get("regime", "N/A")
    tv_tp1 = data.get("tv_tp1", "N/A")

    logger.info(f"[Webhook] 收到信号 → Action: {action} | Regime: {regime} | TV_TP1: {tv_tp1}")

    # 3. 异步交给大脑处理
    try:
        threading.Thread(
            target=position_supervisor.handle_signal,
            args=(data,),
            daemon=True
        ).start()
    except Exception as e:
        logger.error(f"[Webhook] 启动处理线程失败: {e}")
        return jsonify({"status": "error", "message": "内部执行错误"}), 500

    return jsonify({
        "status": "success",
        "message": "Signal received and processing started",
        "action": action,
        "regime": regime
    }), 200


# ==================== 健康检查接口 ====================
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "service": "deepcoin_webhook",
        "version": "v2.0-two-stage-radar",
        "description": "深币两道平仓 + 雷达移动保本版"
    }), 200


if __name__ == '__main__':
    logger.info("🚀 深币 Webhook 服务启动中... (两道平仓 + 雷达版)")
    app.run(host='127.0.0.1', port=5004, debug=False)
