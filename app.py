#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, threading, json, logging
from flask import Flask, request, jsonify
from position_supervisor_deepcoin import position_supervisor

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Flask: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(force=True, silent=True)
    if not data:
        try:
            data = json.loads(request.get_data(as_text=True))
        except:
            return jsonify({"status": "error", "message": "无效JSON"}), 400

    secret = str(data.get("secret", "")).strip()
    if secret != os.getenv("WEBHOOK_SECRET", "528586"):
        logger.warning("Secret 校验失败")
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    action = data.get("action", "UNKNOWN")
    logger.info(f"[Webhook] 收到信号 → {action}")

    try:
        threading.Thread(target=position_supervisor.handle_signal, args=(data,), daemon=True).start()
    except Exception as e:
        logger.error(f"处理线程启动失败: {e}")
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "success"}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "deepcoin_webhook_v2"}), 200

if __name__ == '__main__':
    logger.info("🚀 深币 Webhook 服务启动 (最终版)")
    app.run(host='127.0.0.1', port=5004, debug=False)
