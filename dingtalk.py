#!/usr/bin/env python3
# dingtalk.py（Deepcoin V7.0 专属战报推送模块）
import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

DINGTALK_WEBHOOK = os.getenv("DINGTALK_WEBHOOK", "")
DINGTALK_SECRET = os.getenv("DINGTALK_SECRET", "")

def _generate_sign(secret: str) -> tuple:
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode('utf-8')
    string_to_sign = f'{timestamp}\n{secret}'
    string_to_sign_enc = string_to_sign.encode('utf-8')
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign

def _get_signed_url() -> str:
    if not DINGTALK_WEBHOOK: return ""
    if DINGTALK_SECRET:
        timestamp, sign = _generate_sign(DINGTALK_SECRET)
        return f"{DINGTALK_WEBHOOK}&timestamp={timestamp}&sign={sign}"
    return DINGTALK_WEBHOOK

def send_markdown_message(title: str, text: str, is_at_all: bool = False):
    if not DINGTALK_WEBHOOK:
        logger.warning("[DingTalk] 未配置 Webhook，跳过战报发送")
        return False

    try:
        url = _get_signed_url()
        if not url: return False

        full_text = f"### {title}\n> **⏱ 战报生成**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n{text}\n---\n*🤖 深币(Deepcoin) V7.0 · 高频微利剥头皮引擎*"

        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": full_text
            },
            "at": {"isAtAll": is_at_all}
        }

        resp = requests.post(url, json=data, timeout=8)
        if resp.status_code == 200 and resp.json().get("errcode") == 0:
            logger.info(f"[DingTalk] 战报发送成功: {title}")
            return True
        else:
            logger.error(f"[DingTalk] 发送失败: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"[DingTalk] 发送异常: {e}", exc_info=True)
        return False
