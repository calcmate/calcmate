"""
modules/telegram_notifier.py — 텔레그램 알림 발송 (v12.1, cfg 참조 방식 수정)
"""
import os
import requests
from .logger import get_logger

LOG = get_logger()

def _send_telegram(cfg: dict, message: str):
    token = cfg.get('TELEGRAM_BOT_TOKEN')
    chat_id = cfg.get('TELEGRAM_CHAT_ID')

    if not token or not chat_id:
        if os.getenv("TELEGRAM_DEBUG") == "1":
            instance_id = cfg.get("_instance_id", "unknown") if cfg else "unknown"
            config_source = cfg.get("_config_source", "unknown") if cfg else "unknown"
            LOG.debug("Telegram runtime cfg pid=%d instance=%s source=%s token_present=%s chat_id_present=%s",
                      os.getpid(), instance_id, config_source,
                      "true" if token else "false", "true" if chat_id else "false")
        LOG.warning("Telegram configuration missing (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID).")
        return

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {'chat_id': chat_id, 'text': f"[블로그자동화]\n{message}"}
        response = requests.post(url, json=payload, timeout=10)
        if not response.ok:
            LOG.warning("Telegram API error (HTTP %s): %s", response.status_code, response.text[:200])
    except Exception as e:
        LOG.warning("Failed to send Telegram message: %s", e)

def send(cfg: dict, message: str):
    _send_telegram(cfg, message)

def send_message(cfg: dict, text: str):
    _send_telegram(cfg, text)

def send_success(cfg: dict, summary: str):
    _send_telegram(cfg, f"✅ SUCCESS: {summary}")

def send_failure(cfg: dict, summary: str):
    _send_telegram(cfg, f"❌ FAILURE: {summary}")

def send_warning(cfg: dict, summary: str):
    _send_telegram(cfg, f"⚠️ WARNING: {summary}")
