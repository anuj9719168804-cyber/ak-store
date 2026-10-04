"""Gateway webhooks. The signature is checked on the RAW body before anything else is read.

  POST /webhook/razorpay      event payment_link.paid        (X-Razorpay-Signature)
  POST /webhook/nowpayments   payment_status == finished     (x-nowpayments-sig)

Answers: 200 = handled (also for duplicates and events we ignore, so the gateway stops retrying),
400 = bad signature / body, 500 = we could not give the goods yet, please retry.
"""
import json

from quart import current_app, request

from config import LOGGER
from helper import payments
from web import web
from web.auth import client_key

log = LOGGER("pay_web", "web")


def _bot():
    return current_app.config["BOT"]


@web.route("/webhook/razorpay", methods=["POST"])
async def razorpay_webhook():
    if not payments.razorpay_on():
        return "disabled", 404
    raw = await request.get_data()
    if not payments.verify_razorpay(raw, request.headers.get("X-Razorpay-Signature", "")):
        log.warning("Razorpay webhook with a bad signature from %s", client_key())
        return "bad signature", 400
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        return "bad body", 400
    parsed = payments.parse_razorpay_event(body)
    if not parsed:
        return "ignored", 200
    event, order_id, amount, payment_id = parsed
    if event != "payment_link.paid":      # partially_paid / expired / cancelled give nothing
        return "ignored", 200
    result = await payments.process_paid(_bot(), order_id, amount, "INR", payment_id)
    return ("retry", 500) if result == "retry" else ("ok", 200)


@web.route("/webhook/nowpayments", methods=["POST"])
async def nowpayments_webhook():
    if not payments.crypto_on():
        return "disabled", 404
    raw = await request.get_data()
    if not payments.verify_nowpayments(raw, request.headers.get("x-nowpayments-sig", "")):
        log.warning("NOWPayments webhook with a bad signature from %s", client_key())
        return "bad signature", 400
    try:
        parsed = payments.parse_nowpayments_event(json.loads(raw.decode("utf-8")))
    except ValueError:
        return "bad body", 400
    if not parsed:
        return "ignored", 200
    status, order_id, price_amount, price_currency, payment_id = parsed
    if status != "finished":              # waiting / confirming / partially_paid / failed / expired
        return "ignored", 200
    result = await payments.process_paid(_bot(), order_id, price_amount, price_currency, payment_id)
    return ("retry", 500) if result == "retry" else ("ok", 200)
