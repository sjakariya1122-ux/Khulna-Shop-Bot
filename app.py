python
import google.generativeai
import os, sqlite3, requests, threading
from flask import Flask, request, jsonify
from datetime import datetime
from google import genai
from google.genai import types

app = Flask(__name__)

# --- CONFIG ---
TOKEN = os.getenv("WA_TOKEN")
PHONE_NUMBER_ID = os.getenv("WA_PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "khulnashop123")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GRAPH_API_VERSION = "v20.0"
ORDERS_SECRET = os.getenv("ORDERS_SECRET", "khulnashop2026")

ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

SHOP_NAME = "Khulna Shop"
SHOP_ADDRESS = "খুলনা নিউ মার্কেট, খুলনা"
SHOP_PHONE = "+8801XXXXXXXXX"

# --- DB ---
def init_db():
    with sqlite3.connect('bot.db') as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS orders
                     (id INTEGER PRIMARY KEY, phone TEXT, message TEXT, date TEXT)''')
init_db()

def save_order(phone, message):
    with sqlite3.connect('bot.db') as conn:
        conn.execute("INSERT INTO orders (phone, message, date) VALUES (?,?,?)",
                     (phone, message, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

# --- WHATSAPP ---
def wa_post(payload):
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    requests.post(url, json=payload, headers=headers, timeout=10)

def send_text(to, text):
    wa_post({"messaging_product":"whatsapp","to":to,"type":"text","text":{"body":text}})

def send_welcome(to):
    wa_post({
        "messaging_product":"whatsapp","to":to,"type":"interactive",
        "interactive":{
            "type":"button",
            "body":{"text": f"আসসালামু আলাইকুম! 👋\n*Khulna Shop* এ আপনাকে স্বাগতম।\n\nখুলনার সেরা প্রোডাক্ট এখন হাতের মুঠোয়। কীভাবে সাহায্য করতে পারি?"},
            "action":{"buttons":[
                {"type":"reply","reply":{"id":"PRODUCT","title":"📦 প্রোডাক্ট দেখুন"}},
                {"type":"reply","reply":{"id":"ORDER","title":"🛒 অর্ডার করুন"}},
                {"type":"reply","reply":{"id":"LOCATION","title":"📍 লোকেশন"}}
            ]}
        }
    })

def ask_gemini(prompt):
    if not ai_client:
        return f"ধন্যবাদ! {SHOP_NAME} টিম শীঘ্রই যোগাযোগ করবে। কল: {SHOP_PHONE}"
    try:
        res = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=f"You are assistant for Khulna Shop, a shop in Khulna, Bangladesh selling kitchen & home appliances. Always reply in Bangla, friendly, short. Shop phone {SHOP_PHONE}, address {SHOP_ADDRESS}. Encourage order."
            )
        )
        return res.text[:900]
    except:
        return f"আপনার মেসেজ পেয়েছি। বিস্তারিত জানতে কল করুন: {SHOP_PHONE}"

# --- ROUTES ---
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data: return jsonify({"status":"ok"}), 200

    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if "messages" not in value: continue
            msg = value["messages"][0]
            phone = msg["from"]

            if msg.get("type") == "interactive":
                bid = msg["interactive"]["button_reply"]["id"]
                if bid == "PRODUCT":
                    send_text(phone, "📦 *Khulna Shop - ক্যাটাগরি*\n\n1. কিচেন অ্যাপ্লায়েন্স\n2. হোম ডেকোর\n3. ইলেকট্রনিক্স গ্যাজেট\n\nযেটা লাগবে তার নাম লিখুন, যেমন: 'রাইস কুকার দাম কত?'")
                elif bid == "ORDER":
                    save_order(phone, "ORDER button click")
                    send_text(phone, f"🛒 অর্ডার করতে লিখুন:\nনাম:\nঠিকানা:\nপ্রোডাক্ট:\n\nআমরা খুলনা সিটিতে হোম ডেলিভারি দিই।")
                elif bid == "LOCATION":
                    send_text(phone, f"📍 *{SHOP_NAME}*\n{SHOP_ADDRESS}\nফোন: {SHOP_PHONE}\n\nগুগল ম্যাপ: https://maps.google.com/?q=Khulna+New+Market")
                continue

            if msg.get("type") == "text":
                txt = msg["text"]["body"]
                if any(w in txt.lower() for w in ["hi", "hello", "হাই", "সালাম", "khulna"]):
                    send_welcome(phone)
                else:
                    save_order(phone, txt)
                    send_text(phone, ask_gemini(txt))

    return jsonify({"status":"ok"}), 200

@app.route("/")
def home():
    return f"{SHOP_NAME} Bot is Running!"

@app.route("/orders")
def orders():
    if request.args.get("key")!= ORDERS_SECRET: return "Unauthorized", 401
    with sqlite3.connect('bot.db') as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify(rows)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
