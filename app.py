# -*- coding: utf-8 -*-
import os
import re
import sqlite3
import requests
from datetime import datetime
from flask import Flask, request, jsonify
import google.generativeai as genai

app = Flask(__name__)

# ---------- CONFIG (Environment Variables) ----------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
ORDERS_SECRET = os.getenv("ORDERS_SECRET")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v20.0")

SHOP_NAME = os.getenv("SHOP_NAME", "Khulna Shop")
SHOP_PHONE = os.getenv("SHOP_PHONE", "01XXXXXXXXX")
SHOP_ADDRESS = os.getenv("SHOP_ADDRESS", "খুলনা, বাংলাদেশ")
DB_PATH = os.getenv("DB_PATH", "bot.db")

model = None
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

GREETING_RE = re.compile(r"\b(hi|hello|hey|khulna)\b|হাই|হ্যালো|সালাম", re.IGNORECASE)


# ---------- DATABASE ----------
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT,
                message TEXT,
                date TEXT
            )"""
        )


def save_order(phone, message):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO orders (phone, message, date) VALUES (?,?,?)",
            (phone, message, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )


init_db()


# ---------- WHATSAPP ----------
def wa_post(payload):
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if r.status_code >= 400:
            print("WhatsApp API error:", r.status_code, r.text)
    except requests.RequestException as e:
        print("WhatsApp request failed:", e)


def send_text(to, text):
    wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text[:900]},
    })


def send_welcome(to):
    wa_post({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": f"আসসালামু আলাইকুম! 👋\n*{SHOP_NAME}* এ আপনাকে স্বাগতম।\n\n"
                        "খুলনার সেরা প্রোডাক্ট এখন হাতের মুঠোয়। কীভাবে সাহায্য করতে পারি?"
            },
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": "PRODUCT", "title": "📦 প্রোডাক্ট দেখুন"}},
                {"type": "reply", "reply": {"id": "ORDER", "title": "🛒 অর্ডার করুন"}},
                {"type": "reply", "reply": {"id": "LOCATION", "title": "📍 লোকেশন"}},
            ]},
        },
    })


# ---------- GEMINI ----------
def ask_gemini(prompt):
    fallback = f"আপনার মেসেজ পেয়েছি। বিস্তারিত জানতে কল করুন: {SHOP_PHONE}"
    if model is None:
        return f"ধন্যবাদ! {SHOP_NAME} টিম শীঘ্রই যোগাযোগ করবে। কল: {SHOP_PHONE}"
    try:
        full_prompt = (
            f"You are an assistant for {SHOP_NAME} in Khulna selling kitchen items. "
            f"Reply in Bangla, friendly and short. Shop phone {SHOP_PHONE}, address {SHOP_ADDRESS}.\n"
            f"User: {prompt}"
        )
        res = model.generate_content(full_prompt)
        return (res.text or fallback)[:900]
    except Exception as e:
        print("Gemini error:", e)
        return fallback


# ---------- ROUTES ----------
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    if mode == "subscribe" and VERIFY_TOKEN and token == VERIFY_TOKEN:
        return request.args.get("hub.challenge", ""), 200
    return "Forbidden", 403


def handle_message(msg):
    phone = msg.get("from")
    mtype = msg.get("type")

    if mtype == "interactive":
        interactive = msg.get("interactive", {})
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        bid = reply.get("id")
        if bid == "PRODUCT":
            send_text(phone, "📦 *" + SHOP_NAME + " - ক্যাটাগরি*\n\n1. কিচেন অ্যাপ্লায়েন্স\n2. হোম ডেকোর\n3. ইলেকট্রনিক্স গ্যাজেট\n\nযেটা লাগবে তার নাম লিখুন")
        elif bid == "ORDER":
            save_order(phone, "ORDER button")
            send_text(phone, "🛒 অর্ডার করতে লিখুন:\nনাম:\nঠিকানা:\nপ্রোডাক্ট:\n\nআমরা খুলনা সিটিতে হোম ডেলিভারি দিই।")
        elif bid == "LOCATION":
            send_text(phone, f"📍 *{SHOP_NAME}*\n{SHOP_ADDRESS}\nফোন: {SHOP_PHONE}")
        return

    if mtype == "text":
        txt = msg.get("text", {}).get("body", "")
        if GREETING_RE.search(txt):
            send_welcome(phone)
        else:
            save_order(phone, txt)
            send_text(phone, ask_gemini(txt))


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "ok"}), 200
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    handle_message(msg)
    except Exception as e:
        # Meta-কে সবসময় 200 দিতে হবে, নইলে বারবার retry করবে
        print("Webhook error:", e)
    return jsonify({"status": "ok"}), 200


@app.route("/")
def home():
    return f"{SHOP_NAME} Bot is Running!"


@app.route("/orders")
def orders():
    if not ORDERS_SECRET or request.args.get("key") != ORDERS_SECRET:
        return "Unauthorized", 401
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify(rows)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
