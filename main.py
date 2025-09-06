import os
import asyncio
import base64
import json
import time
import traceback
import uuid
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime, date
from urllib.parse import quote
import pytz

import httpx
import pandas as pd
import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import (Body, FastAPI, File, HTTPException, Request, UploadFile,
                     WebSocket)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from requests.auth import HTTPBasicAuth
from starlette.websockets import WebSocketDisconnect

# Load environment variables at the very beginning
load_dotenv()

# IST timezone setup
IST = pytz.timezone('Asia/Kolkata')

def get_ist_timestamp():
    """Get current timestamp in IST"""
    return datetime.now(IST)

def format_ist_datetime(dt):
    """Format datetime object to IST string"""
    if dt is None:
        return None
    
    # Handle date objects (convert to datetime first)
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time())
    
    # Handle timezone-naive datetime objects
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    
    return dt.astimezone(IST).isoformat()

# Import project-specific modules
from database.schemas import (CallStatus, Customer,
                              db_manager, init_database, update_call_status, get_call_session_by_sid,
                              update_customer_call_status_by_phone, update_customer_call_status)
from sqlalchemy.orm import joinedload
from services.call_management import call_service
from utils import bedrock_client
from utils.agent_transfer import trigger_exotel_agent_transfer
from utils.logger import setup_application_logging, logger
from utils.production_asr import ProductionSarvamHandler
from utils.redis_session import (init_redis, redis_manager,
                                 generate_websocket_session_id)

import httpx
import asyncio
from datetime import datetime

import httpx
import asyncio

from fastapi import FastAPI, WebSocket, Request
import httpx, sqlite3

# Initialize FastAPI
app = FastAPI()
active_connections = []


# Exotel Configuration
EXOTEL_SID="intalksai31"
EXOTEL_TOKEN="9ef71049188a5a603a0dbd9fd4c3f151de39443458add480"
EXOTEL_API_KEY="ce1c503fc544b72c570e0f56cd9f7dcffd85d24121ecc421"
EXOTEL_VIRTUAL_NUMBER="09513886363"
EXOTEL_FLOW_APP_ID="1067306"
AGENT_PHONE_NUMBER="9384531725"


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    active_connections.append(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive
    except:
        active_connections.remove(ws)

# -------------------------------
# Trigger call to Exotel
# -------------------------------
@app.post("/make_call")
async def make_call(number: str):
    BASE_URL = os.getenv("BASE_URL", "https://350e5942b7c6.ngrok-free.app")

    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"https://api.exotel.com/v1/Accounts/{EXOTEL_SID}/Calls/connect",
            auth=(EXOTEL_SID, EXOTEL_TOKEN),
            data={
                "From": number,   # customer number
                "CallerId": EXOTEL_VIRTUAL_NUMBER,   # your Exotel virtual number
                "Url": f"{BASE_URL}/exotel-callback",          # handles XML flow
                "StatusCallback": f"{BASE_URL}/passthru-handler"  # ✅ final status updates
            }
        )

    return {
        "message": "Call triggered",
        "response": res.text
    }


# -------------------------------
# Callback from Exotel
# -------------------------------
import asyncio
import threading
from fastapi.responses import PlainTextResponse

@app.post("/exotel-callback", response_class=PlainTextResponse)
async def exotel_callback(request: Request):
    """
    Unified Exotel callback handler.
    Handles both:
      - Passthru Applet callbacks (field = 'Status')
      - Call API StatusCallbacks (field = 'CallStatus')
    Updates DB and broadcasts to frontend.
    """

    logger.websocket.info("✅ /exotel-callback hit")

    data = await request.form()
    form_dict = dict(data)
    logger.websocket.info(f"📨 FULL Exotel payload: {form_dict}")

    call_sid = data.get("CallSid")
    # Accept either "Status" (Passthru) or "CallStatus" (API)
    raw_status = data.get("Status") or data.get("CallStatus")
    custom_field = data.get("CustomField")

    if not call_sid:
        logger.error.error("❌ Exotel callback called without a CallSid.")
        return "OK"

    logger.websocket.info(f"📞 CallSid={call_sid}, RawStatus={raw_status}")
    logger.websocket.info(f"📦 CustomField={custom_field}")

    # --- Parse custom field if present ---
    customer_data = {}
    if custom_field:
        try:
            pairs = custom_field.split('|')
            for pair in pairs:
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    customer_data[key.strip()] = value.strip()
            logger.websocket.info(f"📊 Parsed Custom Fields: {customer_data}")
        except Exception as e:
            logger.error.error(f"❌ Failed to parse CustomField: {e}")

    temp_call_id = customer_data.get("temp_call_id")

    # --- Redis Caching ---
    if temp_call_id:
        redis_manager.link_session_to_sid(temp_call_id, call_sid)
    else:
        redis_manager.create_call_session(call_sid, customer_data)

    # --- Map Exotel raw status → internal status ---
    status_map = {
        "queued": "initiated",
        "in-progress": "call_in_progress",
        "answered": "call_in_progress",
        "ringing": "call_in_progress",   # 🔹 normalize ringing
        "completed": "call_completed",
        "busy": "call_failed",
        "failed": "call_failed",
        "no-answer": "call_failed",
        "not-answered": "call_failed",
        "cancelled": "call_failed",
        "canceled": "call_failed",
    }
    status = status_map.get(raw_status.lower() if raw_status else "", "call_failed")

    # --- Database Update ---
    try:
        logger.database.info(f"✍️ Updating database for CallSid={call_sid} with status={status}")
        session = db_manager.get_session()
        try:
            update_call_status(
                session=session,
                call_sid=call_sid,
                status=status,
                message=f"Exotel callback update (raw={raw_status}, temp_call_id={temp_call_id})"
            )
            session.commit()
            logger.database.info(f"✅ Database updated for CallSid={call_sid}")

            # 🔹 Auto-mark ringing → failed after 30s if no update
            if status == "call_in_progress":
                def mark_call_failed_if_still_in_progress(call_sid, customer_id):
                    s = db_manager.get_session()
                    try:
                        call_session = get_call_session_by_sid(s, call_sid)
                        if call_session and call_session.status == "call_in_progress":
                            update_call_status(
                                s,
                                call_sid,
                                "call_failed",
                                "Auto-marked after 30s with no further updates"
                            )
                            s.commit()
                            logger.database.info(f"⏱️ Auto-marked CallSid={call_sid} as call_failed")

                            # Broadcast safely
                            try:
                                loop = asyncio.get_event_loop()
                                loop.create_task(
                                    broadcast_status_update(call_sid, "call_failed", customer_id)
                                )
                            except RuntimeError:
                                asyncio.run(broadcast_status_update(call_sid, "call_failed", customer_id))
                    finally:
                        s.close()

                threading.Timer(
                    30,
                    mark_call_failed_if_still_in_progress,
                    args=[call_sid, customer_data.get("customer_id")]
                ).start()
        finally:
            session.close()
    except Exception as e:
        logger.error.error(f"❌ Database update failed for CallSid {call_sid}: {e}")

    # --- Broadcast to frontend immediately ---
    try:
        await broadcast_status_update(call_sid, status, customer_data.get("customer_id"))
    except Exception as e:
        logger.error.error(f"❌ Failed to broadcast status update: {e}")

    # Always return OK so Exotel doesn’t retry
    return "OK"

# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    # Initialize logging system first
    setup_application_logging()
    logger.app.info("🚀 Starting Voice Assistant Application...")
    
    # Initialize database
    if init_database():
        logger.app.info("✅ Database initialized successfully")
        logger.database.info("Database connection established")
    else:
        logger.error.error("❌ Database initialization failed")
        logger.database.error("Failed to establish database connection")
    
    # Initialize Redis
    if init_redis():
        logger.app.info("✅ Redis initialized successfully")
    else:
        logger.app.warning("❌ Redis initialization failed - running without session management")
    
    logger.app.info("🎉 Application startup complete!")
    
    yield
    
    # Shutdown
    logger.app.info("🛑 Shutting down Voice Assistant Application...")

app = FastAPI(
    title="Voice Assistant Call Management System",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
sarvam_handler = ProductionSarvamHandler(SARVAM_API_KEY)

# --- Constants ---
BUFFER_DURATION_SECONDS = 1.0
AGENT_RESPONSE_BUFFER_DURATION = 3.0  # Wait longer for user to answer agent connect question
MIN_AUDIO_BYTES = 3200  # ~0.2s at 8kHz 16-bit mono; ignore too-short buffers

# --- Multilingual Prompt Templates with SSML and Pauses ---
GREETING_TEMPLATE = {
    "en-IN": "Hello, this is Priya, calling on behalf of South India Finvest Bank. Am I speaking with Mr. {name}?",
    "hi-IN": "नमस्ते, मैं प्रिया हूं, और साउथ इंडिया फिनवेस्ट बैंक की ओर से बात कर रही हूं। क्या मैं श्री/सुश्री {name} से बात कर रही हूं?",
    "ta-IN": "வணக்கம், நான் பிரியா, இது சவுத் இந்தியா ஃபின்வெஸ்ட் வங்கியிலிருந்து அழைப்பு. திரு/திருமதி {name} பேசுகிறீர்களா?",
    "te-IN": "హలో, నేను ప్రియ మాట్లాడుతున్నాను, ఇది సౌత్ ఇండియా ఫిన్‌వెస్ట్ బ్యాంక్ నుండి కాల్. మిస్టర్/మిసెస్ {name} మాట్లాడుతున్నారా?",
    "ml-IN": "നമസ്കാരം, ഞാൻ പ്രിയയാണ്, സൗത്ത് ഇന്ത്യ ഫിൻവെസ്റ്റ് ബാങ്കിന്റെ ഭാഗമായാണ് വിളിച്ചത്. {name} ആണോ സംസാരിക്കുന്നത്?",
    "gu-IN": "નમસ્તે, હું પ્રિયા છું, સાઉથ ઇન્ડિયા ફિનવેસ્ટ બેંક તરફથી બોલી રહી છું. શું હું શ્રી {name} સાથે વાત કરી રહી છું?",
    "mr-IN": "नमस्कार, मी प्रिया बोलत आहे, साउथ इंडिया फिनवेस्ट बँकेकडून. मी श्री {name} शी बोलत आहे का?",
    "bn-IN": "নমস্কার, আমি প্রিয়া, সাউথ ইন্ডিয়া ফিনভেস্ট ব্যাংকের পক্ষ থেকে ফোন করছি। আমি কি {name} এর সাথে কথা বলছি?",
    "kn-IN": "ನಮಸ್ಕಾರ, ನಾನು ಪ್ರಿಯಾ, ಸೌತ್ ಇಂಡಿಯಾ ಫಿನ್‌ವೆಸ್ಟ್ ಬ್ಯಾಂಕ್‌ನಿಂದ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ. ನಾನು ಶ್ರಿ {name} ಅವರೊಂದಿಗೆ ಮಾತನಾಡುತ್ತಿದ್ದೇನೆವಾ?",
    "pa-IN": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਮੈਂ ਪ੍ਰਿਆ ਹਾਂ, ਸਾਊਥ ਇੰਡੀਆ ਫਿਨਵੈਸਟ ਬੈਂਕ ਵੱਲੋਂ ਗੱਲ ਕਰ ਰਹੀ ਹਾਂ। ਕੀ ਮੈਂ ਸ੍ਰੀ {name} ਨਾਲ ਗੱਲ ਕਰ ਰਹੀ ਹਾਂ?",
    "or-IN": "ନମସ୍କାର, ମୁଁ ପ୍ରିୟା, ସାଉଥ୍ ଇଣ୍ଡିଆ ଫିନଭେଷ୍ଟ ବ୍ୟାଙ୍କରୁ କଥାହୁଁଛି। ମୁଁ {name} ସହିତ କଥାହୁଁଛି କି?",
}

EMI_DETAILS_PART1_TEMPLATE = {
    "en-IN": "Thank you. I am calling about your loan ending in {loan_id}, which has an outstanding EMI of ₹{amount} due on {due_date}. I understand payments can be delayed. I am here to help you avoid any further impact.",
    "hi-IN": "धन्यवाद। मैं आपके लोन (अंतिम चार अंक {loan_id}) के बारे में कॉल कर रही हूँ, जिसकी बकाया ईएमआई ₹{amount} है, जो {due_date} को देय है। मैं समझती हूँ कि भुगतान में देरी हो सकती है। मैं आपकी मदद के लिए यहाँ हूँ ताकि आगे कोई समस्या न हो।",
    "ta-IN": "நன்றி. உங்கள் கடன் (கடைசி நான்கு இலக்கங்கள் {loan_id}) குறித்து அழைக்கிறேன், அதற்கான நிலுவை EMI ₹{amount} {due_date} அன்று செலுத்த வேண்டியது உள்ளது. தாமதம் ஏற்படலாம் என்பதை புரிந்துகொள்கிறேன். மேலும் பாதிப்பு ஏற்படாமல் உதவ நான் இங்கே இருக்கிறேன்.",
    "te-IN": "ధన్యవాదాలు. మీ రుణం ({loan_id} తో ముగిసే) గురించి కాల్ చేస్తున్నాను, దీనికి ₹{amount} EMI {due_date} నాటికి బాకీగా ఉంది. చెల్లింపులు ఆలస్యం కావచ్చు. మరింత ప్రభావం లేకుండా మీకు సహాయం చేయడానికి నేను ఇక్కడ ఉన్నాను.",
    "ml-IN": "നന്ദി. നിങ്ങളുടെ വായ്പ ({loan_id} അവസാനിക്കുന്ന) സംബന്ധിച്ച് വിളിക്കുന്നു, അതിന് ₹{amount} EMI {due_date} ന് ബാക്കി ഉണ്ട്. പണമടയ്ക്കുന്നതിൽ വൈകിപ്പോകാം. കൂടുതൽ പ്രശ്നങ്ങൾ ഒഴിവാക്കാൻ ഞാൻ സഹായിക്കാൻ ഇവിടെ ഉണ്ട്.",
    "gu-IN": "આભાર. હું તમારા લોન ({loan_id}) વિશે કોલ કરી રહી છું, જેમાં ₹{amount} EMI {due_date} સુધી બાકી છે. ચુકવણીમાં વિલંબ થઈ શકે છે. વધુ અસરથી બચવા માટે હું અહીં છું.",
    "mr-IN": "धन्यवाद. मी तुमच्या कर्ज ({loan_id}) विषयी कॉल करत आहे, ज्याची ₹{amount} EMI {due_date} रोजी बाकी आहे. पेमेंटमध्ये उशीर होऊ शकतो. पुढील परिणाम टाळण्यासाठी मी मदतीसाठी येथे आहे.",
    "bn-IN": "ধন্যবাদ. আমি আপনার ঋণ ({loan_id}) সম্পর্কে ফোন করছি, যার ₹{amount} EMI {due_date} তারিখে বাকি আছে। পেমেন্টে দেরি হতে পারে। আরও সমস্যা এড়াতে আমি সাহায্য করতে এখানে আছি।",
    "kn-IN": "ಧನ್ಯವಾದಗಳು. ನಿಮ್ಮ ಸಾಲ ({loan_id}) ಬಗ್ಗೆ ಕರೆ ಮಾಡುತ್ತಿದ್ದೇನೆ, ಇದಕ್ಕೆ ₹{amount} EMI {due_date} ರಂದು ಬಾಕಿ ಇದೆ. ಪಾವತಿಯಲ್ಲಿ ವಿಳಂಬವಾಗಬಹುದು. ಹೆಚ್ಚಿನ ಪರಿಣಾಮ ತಪ್ಪಿಸಲು ನಾನು ಸಹಾಯ ಮಾಡಲು ಇಲ್ಲಿದ್ದೇನೆ.",
    "pa-IN": "ਧੰਨਵਾਦ. ਮੈਂ ਤੁਹਾਡੇ ਲੋਨ ({loan_id}) ਬਾਰੇ ਕਾਲ ਕਰ ਰਹੀ ਹਾਂ, ਜਿਸ ਵਿੱਚ ₹{amount} EMI {due_date} ਤੱਕ ਬਕਾਇਆ ਹੈ। ਭੁਗਤਾਨ ਵਿੱਚ ਦੇਰੀ ਹੋ ਸਕਦੀ ਹੈ. ਹੋਰ ਪ੍ਰਭਾਵ ਤੋਂ ਬਚਣ ਲਈ ਮੈਂ ਇੱਥੇ ਹਾਂ।",
    "or-IN": "ଧନ୍ୟବାଦ. ମୁଁ ଆପଣଙ୍କର ଋଣ ({loan_id}) ବିଷୟରେ କଥାହୁଁଛି, ଯାହାର ₹{amount} EMI {due_date} ରେ ବକାୟା ଅଛି। ଦେୟ ଦେବାରେ ବିଳମ୍ବ ହେବା ସମ୍ଭବ. ଅଧିକ ସମସ୍ୟା ରୋକିବା ପାଇଁ ମୁଁ ଏଠାରେ ଅଛି।"
}

EMI_DETAILS_PART2_TEMPLATE = {
    "en-IN": "Please note. If this EMI remains unpaid, it may be reported to the credit bureau, which can affect your credit score. Continued delay may also classify your account as delinquent, leading to penalty charges or collection notices.",
    "hi-IN": "कृपया ध्यान दें। यदि यह ईएमआई बकाया रहती है, तो इसे क्रेडिट ब्यूरो को रिपोर्ट किया जा सकता है, जिससे आपका क्रेडिट स्कोर प्रभावित हो सकता है। लगातार देरी से आपका खाता डिफॉल्टर घोषित हो सकता है, जिससे पेनल्टी या कलेक्शन नोटिस आ सकते हैं।",
    "ta-IN": "தயவு செய்து கவனிக்கவும். இந்த EMI செலுத்தப்படவில்லை என்றால், அது கிரெடிட் ப்யூரோவுக்கு தெரிவிக்கப்படலாம், இது உங்கள் கிரெடிட் ஸ்கோருக்கு பாதிப்பை ஏற்படுத்தும். தொடர்ந்த தாமதம் உங்கள் கணக்கை குற்றவாளியாக வகைப்படுத்தும், அபராதம் அல்லது வசூல் நோட்டீஸ் வரலாம்.",
    "te-IN": "దయచేసి గమనించండి. ఈ EMI చెల్లించకపోతే, అది క్రెడిట్ బ్యూరోకు నివేదించబడవచ్చు, ఇది మీ క్రెడిట్ స్కోర్‌ను ప్రభావితం చేయవచ్చు. కొనసాగుతున్న ఆలస్యం వల్ల మీ ఖాతా డిఫాల్ట్‌గా పరిగణించబడుతుంది, జరిమానాలు లేదా వసూలు నోటీసులు రావచ్చు.",
    "ml-IN": "ദയവായി ശ്രദ്ധിക്കുക. ഈ EMI അടയ്ക്കപ്പെടാതെ പോയാൽ, അത് ക്രെഡിറ്റ് ബ്യൂറോയ്ക്ക് റിപ്പോർട്ട് ചെയ്യപ്പെടാം, ഇത് നിങ്ങളുടെ ക്രെഡിറ്റ് സ്കോറിനെ ബാധിക്കും. തുടർച്ചയായ വൈകിപ്പിക്കൽ നിങ്ങളുടെ അക്കൗണ്ടിനെ ഡിഫോൾട്ട് ആയി കണക്കാക്കും, പിഴയോ കലക്ഷൻ നോട്ടീസോ വരാം.",
    "gu-IN": "મહેરબાની કરીને નોંધો. જો આ EMI બાકી રહેશે, તો તે ક્રેડિટ બ્યુરોને રિપોર્ટ થઈ શકેછે, જે તમારા ક્રેડિટ સ્કોરને અસર કરી શકેછે. સતત વિલંબથી તમારું ખાતું ડિફોલ્ટ તરીકે ગણાય શકેછે, દંડ અથવા વસૂલાત નોટિસ આવી શકેછે.",
    "mr-IN": "कृपया लक्षात घ्या. ही EMI बकाया राहिल्यास, ती क्रेडिट ब्युरोला रिपोर्ट केली जाऊ शकते, ज्यामुळे तुमचा क्रेडिट स्कोर प्रभावित होऊ शकतो. सततच्या विलंबामुळे तुमचे खाते डिफॉल्टर म्हणून घोषित केले जाऊ शकते, दंड किंवा वसुली नोटीस येऊ शकते.",
    "bn-IN": "দয়া করে লক্ষ্য করুন. এই EMI বকেয়া থাকলে, এটি ক্রেডিট ব্যুরোতে রিপোর্ট করা হতে পারে, যা আপনার ক্রেডিট স্কোরকে প্রভাবিত করতে পারে। ক্রমাগত দেরিতে আপনার অ্যাকাউন্ট ডিফল্ট হিসাবে বিবেচিত হতে পারে, জরিমানা বা সংগ্রহের নোটিশ আসতে পারে।",
    "kn-IN": "ದಯವಿಟ್ಟು ಗಮನಿಸಿ. ಈ EMI ಪಾವತಿಯಾಗದೆ ಇದ್ದರೆ, ಅದು ಕ್ರೆಡಿಟ್ ಬ್ಯೂರೋಗೆ ವರದಿ ಮಾಡಬಹುದು, ಇದು ನಿಮ್ಮ ಕ್ರೆಡಿಟ್ ಸ್ಕೋರ್‌ಗೆ ಪರಿಣಾಮ ಬೀರುತ್ತದೆ. ನಿರಂತರ ವಿಳಂಬದಿಂದ ನಿಮ್ಮ ಖಾತೆಯನ್ನು ಡಿಫಾಲ್ಟ್ ಎಂದು ಪರಿಗಣಿಸಬಹುದು, ದಂಡ ಅಥವಾ ಸಂಗ್ರಹಣಾ ಸೂಚನೆಗಳು ಬರಬಹುದು.",
    "pa-IN": "ਕਿਰਪਾ ਕਰਕੇ ਧਿਆਨ ਦਿਓ. ਜੇ ਇਹ EMI ਬਕਾਇਆ ਰਹੰਦੀ ਹੈ, ਤਾਂ ਇਹਨੂੰ ਕਰੈਡਿਟ ਬਿਊਰੋ ਨੂੰ ਰਿਪੋਰਟ ਕੀਤਾ ਜਾ ਸਕਦਾ ਹੈ, ਜੁਰਮਾਨਾ ਨਾਲ ਤੁਹਾਡਾ ਕਰੈਡਿਟ ਸਕੋਰ ਪ੍ਰਭਾਵਿਤ ਹੋ ਸਕਦਾ ਹੈ। ਲਗਾਤਾਰ ਦੇਰੀ ਨਾਲ ਤੁਹਾਡਾ ਖਾਤਾ ਡਿਫੌਲਟਰ ਘੋਸ਼ਿਤ ਕੀਤਾ ਜਾ ਸਕਦਾ ਹੈ, ਜੁਰਮਾਨਾ ਜਾਂ ਕਲੈਕਸ਼ਨ ਨੋਟਿਸ ਆ ਸਕਦੇ ਹਨ।",
    "or-IN": "ଦୟାକରି ଧ୍ୟାନ ଦିଅନ୍ତୁ. ଏହି EMI ବକାୟା ରହିଲେ, ଏହା କ୍ରେଡିଟ୍ ବ୍ୟୁରୋକୁ ରିପୋର୍ଟ କରାଯାଇପାରେ, ଯାହା ଆପଣଙ୍କର କ୍ରେଡିଟ୍ ସ୍କୋରକୁ ପ୍ରଭାବିତ କରିପାରେ। ଲଗାତାର ବିଳମ୍ବ ଆପଣଙ୍କର ଖାତାକୁ ଡିଫଲ୍ଟ୍ ଭାବରେ ଘୋଷଣା କରିପାରେ, ଜରିମାନା କିମ୍ବା କଲେକ୍ସନ୍ ନୋଟିସ୍ ଆସିପାରେ।"
}

AGENT_CONNECT_TEMPLATE = {
    "en-IN": "If you are facing difficulties, we have options like part payments or revised EMI plans. Would you like me to connect you to one of our agents to assist you better?",
    "hi-IN": "यदि आपको कठिनाई हो रही है, तो हमारे पास आंशिक भुगतान या संशोधित ईएमआई योजनाओं जैसे विकल्प हैं। क्या आप चाहेंगे कि मैं आपको हमारे एजेंट से जोड़ दूं, ताकि वे आपकी मदद कर सकें?",
    "ta-IN": "உங்களுக்கு சிரமம் இருந்தால், பகுதி கட்டணம் அல்லது திருத்தப்பட்ட EMI திட்டங்கள் போன்ற விருப்பங்கள் உள்ளன. உங்களுக்கு உதவ எங்கள் ஏஜெண்டுடன் இணைக்க விரும்புகிறீர்களா?",
    "te-IN": "మీకు ఇబ్బంది ఉంటే, భాగ చెల్లింపులు లేదా సవరించిన EMI ప్లాన్‌లు వంటి ఎంపికలు ఉన్నాయి. మీకు సహాయం చేయడానికి మా ఏజెంట్‌ను కలిపించాలా?",
    "ml-IN": "നിങ്ങൾക്ക് ബുദ്ധിമുട്ട് ഉണ്ടെങ്കിൽ, ഭാഗിക പണമടയ്ക്കൽ അല്ലെങ്കിൽ പുതുക്കിയ EMI പദ്ധതികൾ പോലുള്ള ഓപ്ഷനുകൾ ഞങ്ങൾക്കുണ്ട്. നിങ്ങളെ സഹായിക്കാൻ ഞങ്ങളുടെ ഏജന്റുമായി ബന്ധിപ്പിക്കണോ?",
    "gu-IN": "જો તમને મુશ્કેલી હોય, તો અમારી પાસે ભાગ ચુકવણી અથવા સુધારેલી EMI યોજનાઓ જેવા વિકલ્પો છે. શું હું તમને અમારા એજન્ટ સાથે જોડું?",
    "mr-IN": "तुम्हाला अडचण असल्यास, आमच्याकडे भाग पेमेन्ट किंवा सुधारित EMI योजना आहेत. मी तुम्हाला आमच्या एजंटशी जोडू का?",
    "bn-IN": "আপনার অসুবিধা হলে, আমাদের কাছে আংশিক পেমেন্ট বা সংশোধিত EMI প্ল্যানের মতো বিকল্প রয়েছে। আপনাকে সাহায্য করতে আমাদের এজেন্টের সাথে সংযোগ করব?",
    "kn-IN": "ನಿಮಗೆ ತೊಂದರೆ ಇದ್ದರೆ, ಭಾಗ ಪಾವತಿ ಅಥವಾ ಪರಿಷ್ಕೃತ EMI ಯೋಜನೆಗಳೂ ನಮ್ಮ ಬಳಿ ಇವೆ. ನಿಮಗೆ ಸಹಾಯ ಮಾಡಲು ನಮ್ಮ ಏಜೆಂಟ್‌ಗೆ ಸಂಪರ್ಕ ಮಾಡಬೇಕೆ?",
    "pa-IN": "ਜੇ ਤੁਹਾਨੂੰ ਮੁਸ਼ਕਲ ਆ ਰਹੀ ਹੈ, ਤਾਂ ਸਾਡੇ ਕੋਲ ਹਿੱਸਾ ਭੁਗਤਾਨ ਜਾਂ ਸੋਧੀ EMI ਯੋਜਨਾਵਾਂ ਵਰਗੇ ਵਿਕਲਪ ਹਨ। ਕੀ ਮੈਂ ਤੁਹਾਨੂੰ ਸਾਡੇ ਏਜੰਟ ਨਾਲ ਜੋੜਾਂ?",
    "or-IN": "ଯଦି ଆପଣଙ୍କୁ ସମସ୍ୟା ହେଉଛି, ଆମ ପାଖରେ ଅଂଶିକ ପେମେଣ୍ଟ କିମ୍ବା ସଂଶୋଧିତ EMI ଯୋଜନା ଅଛି। ଆପଣଙ୍କୁ ସହଯୋଗ କରିବା ପାଇଁ ଆମ ଏଜେଣ୍ଟ ସହିତ ଯୋଗାଯୋଗ କରିବି?"
}

GOODBYE_TEMPLATE = {
    "en-IN": "I understand. If you change your mind, please call us back. Thank you. Goodbye.",
    "hi-IN": "मैं समझती हूँ। यदि आप अपना विचार बदलते हैं, तो कृपया हमें वापस कॉल करें। धन्यवाद। अलविदा।",
    "ta-IN": "நான் புரிந்துகொள்கிறேன். நீங்கள் உங்கள் மனதை மாற்றினால், தயவுசெய்து எங்களை மீண்டும் அழைக்கவும். நன்றி. விடைபெறுகிறேன்.",
    "te-IN": "నాకు అర్థమైంది. మీరు మీ అభిప్రాయాన్ని మార్చుకుంటే, దయచేసి మమ్మల్ని తిరిగి కాల్ చేయండి. ధన్యవాదాలు. వీడ్కోలు.",
    "ml-IN": "ഞാൻ മനസ്സിലാക്കുന്നു. നിങ്ങൾ അഭിപ്രായം മാറ്റിയാൽ, ദയവായി ഞങ്ങളെ വീണ്ടും വിളിക്കുക. നന്ദി. വിട.",
    "gu-IN": "હું સમજું છું. જો તમે તમારો મન બદલો, તો કૃપા કરીને અમને પાછા કોલ કરો. આભાર. અલવિદા.",
    "mr-IN": "मी समजते. तुम्ही तुमचा निर्णय बदलल्यास, कृपया आम्हाला पुन्हा कॉल करा. धन्यवाद. गुडबाय.",
    "bn-IN": "আমি বুঝতে পারছি. আপনি যদি মত পরিবর্তন করেন, দয়া করে আমাদের আবার কল করুন। ধন্যবাদ। বিদায়।",
    "kn-IN": "ನಾನು ಅರ್ಥಮಾಡಿಕೊಂಡೆ. ನೀವು ನಿಮ್ಮ ಅಭిಪ్ರಾಯವನ್ನು ಬದಲಾಯಿಸಿದರೆ, ದಯವಿಟ್ಟು ನಮಗೆ ಮತ್ತೆ ಕರೆ ಮಾಡಿ. ಧನ್ಯವಾದಗಳು. ವಿದಾಯ.",
    "pa-IN": "ਧੰਨਵਾਦ. ਮੈਂ ਤੁਹਾਡੇ ਲੋਨ ({loan_id}) ਬਾਰੇ ਕਾਲ ਕਰ ਰਹੀ ਹਾਂ, ਜਿਸ ਵਿੱਚ ₹{amount} EMI {due_date} ਤੱਕ ਬਕਾਇਆ ਹੈ। ਭੁਗਤਾਨ ਵਿੱਚ ਦੇਰੀ ਹੋ ਸਕਦੀ ਹੈ. ਹੋਰ ਪ੍ਰਭਾਵ ਤੋਂ ਬਚਣ ਲਈ ਮੈਂ ਇੱਥੇ ਹਾਂ।",
    "or-IN": "ଧନ୍ୟବାଦ. ମୁଁ ଆପଣଙ୍କର ଋଣ ({loan_id}) ବିଷୟରେ କଥାହୁଁଛି, ଯାହାର ₹{amount} EMI {due_date} ରେ ବକାୟା ଅଛି। ଦେୟ ଦେବାରେ ବିଳମ୍ବ ହେବା ସମ୍ଭବ. ଅଧିକ ସମସ୍ୟା ରୋକିବା ପାଇଁ ମୁଁ ଏଠାରେ ଅଛି।"
}

# --- TTS & Audio Helper Functions ---

async def play_transfer_to_agent(websocket, customer_number: str):
    logger.tts.info("play_transfer_to_agent")
    transfer_text = (
        "Please wait, we are transferring the call to an agent."
    )
    logger.tts.info("🔁 Converting agent transfer prompt")
    # Using 'en-IN' for transfer prompt for consistency, but could be `call_detected_lang`
    audio_bytes = await sarvam_handler.synthesize_tts("Please wait, we are transferring the call to an agent.", "en-IN")
    logger.tts.info("📢 Agent transfer audio generated")

    await stream_audio_to_websocket(websocket, audio_bytes)

    logger.websocket.info("📞 Initiating agent call transfer")
    # The AGENT_NUMBER should be loaded from environment variables
    agent_number = os.getenv("AGENT_PHONE_NUMBER")
    if customer_number and agent_number:
        await trigger_exotel_agent_transfer(customer_number, agent_number)
    else:
        logger.error.error("Could not initiate agent transfer. Missing customer_number or agent_number.")

CHUNK_SIZE = 1600
async def stream_audio_to_websocket(websocket, audio_bytes):
    print("stream_audio_to_websocket")
    if not audio_bytes:
        print("[stream_audio_to_websocket] ❌ No audio bytes to stream.")
        return
    #CHUNK_SIZE=1600
    duration_ms = len(audio_bytes) / 16000 * 1000  # 16kBps → ~8kHz mono SLIN
    for i in range(0, len(audio_bytes), CHUNK_SIZE):
        chunk = audio_bytes[i:i + CHUNK_SIZE]
        if not chunk:
            continue
        b64_chunk = base64.b64encode(chunk).decode("utf-8")
        response_msg = {
            "event": "media",
            "media": {"payload": b64_chunk}
        }
        # Guard against sending after close
        try:
            state = getattr(getattr(websocket, 'client_state', None), 'name', 'CONNECTED')
            if state not in ['CONNECTED', 'CONNECTING']:
                print(f"[stream_audio_to_websocket] WebSocket not connected (state={state}). Stopping stream.")
                break
            await websocket.send_json(response_msg)
        except Exception as _e:
            print(f"[stream_audio_to_websocket] Send failed: {_e}")
            break
        await asyncio.sleep(0.02)  # simulate real-time playback
    # Provide a tiny cushion only; chunk pacing already matched duration
    print(f"[stream_audio_to_websocket] Streamed ~{duration_ms:.0f}ms of audio (paced)")
    await asyncio.sleep(0.1)

async def stream_audio_to_websocket_not_working(websocket, audio_bytes):
    CHUNK_SIZE = 8000  # Send 1 second of audio at a time
    if not audio_bytes:
        logger.error.warning("No audio bytes to stream.")
        return
    
    # Check if WebSocket is still connected before streaming
    if websocket.client_state.name not in ['CONNECTED', 'CONNECTING']:
        logger.error.warning(f"WebSocket not connected (state: {websocket.client_state.name}). Skipping audio stream.")
        return
    
    try:
        logger.websocket.info(f"📡 Starting audio stream: {len(audio_bytes)} bytes in {len(audio_bytes)//CHUNK_SIZE + 1} chunks")
        
        for i in range(0, len(audio_bytes), CHUNK_SIZE):
            # Check connection state before each chunk
            if websocket.client_state.name != 'CONNECTED':
                logger.error.warning(f"WebSocket disconnected during streaming (state: {websocket.client_state.name}). Stopping audio stream.")
                break
                
            chunk = audio_bytes[i:i + CHUNK_SIZE]
            if not chunk:
                continue
            b64_chunk = base64.b64encode(chunk).decode("utf-8")
            response_msg = {
                "event": "media",
                "media": {"payload": b64_chunk}
            }
            await websocket.send_json(response_msg)
            await asyncio.sleep(float(CHUNK_SIZE) / 16000.0) # Sleep for the duration of the audio chunk
            
        logger.websocket.info("✅ Audio stream completed successfully")
    except Exception as e:
        logger.error.error(f"Error streaming audio to WebSocket: {e}")
        raise

async def greeting_template_play(websocket, customer_info, lang: str):
    """Plays the personalized greeting in the detected language."""
    logger.tts.info("greeting_template_play")
    greeting = GREETING_TEMPLATE.get(lang, GREETING_TEMPLATE["en-IN"]).format(name=customer_info.get('name', 'there'))
    logger.tts.info(f"🔁 Converting personalized greeting: {greeting}")
    
    # Use new TTS method that handles rate limiting and error recovery
    audio_bytes = await sarvam_handler.synthesize_tts(greeting, lang)
    await stream_audio_to_websocket(websocket, audio_bytes)

async def play_did_not_hear_response(websocket, lang: str):
    """Plays a prompt when the initial response is not heard."""
    prompt_text = "I'm sorry, I didn't hear your response. This call is regarding your loan account. If this is a convenient time to talk, please say 'yes'."
    logger.tts.info(f"🔁 Converting 'didn't hear' prompt: {prompt_text}")
    # Use regular TTS with translation since this is English text
    audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
    await stream_audio_to_websocket(websocket, audio_bytes)

async def play_emi_details_part1(websocket, customer_info, lang: str):
    """Plays the first part of EMI details."""
    try:
        prompt_text = EMI_DETAILS_PART1_TEMPLATE.get(
            lang, EMI_DETAILS_PART1_TEMPLATE["en-IN"]
        ).format(
            loan_id=customer_info.get('loan_id', 'XXXX'),
            amount=customer_info.get('amount', 'a certain amount'),
            due_date=customer_info.get('due_date', 'a recent date')
        )
        logger.tts.info(f"🔁 Converting EMI part 1: {prompt_text}")
        audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
        await stream_audio_to_websocket(websocket, audio_bytes)
    except Exception as e:
        logger.tts.error(f"❌ Error in EMI part 1: {e}")
        raise

async def play_emi_details_part2(websocket, customer_info, lang: str):
    """Plays the second part of EMI details."""
    try:
        prompt_text = EMI_DETAILS_PART2_TEMPLATE.get(lang, EMI_DETAILS_PART2_TEMPLATE["en-IN"])
        logger.tts.info(f"🔁 Converting EMI part 2: {prompt_text}")
        audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
        await stream_audio_to_websocket(websocket, audio_bytes)
    except Exception as e:
        logger.tts.error(f"❌ Error in EMI part 2: {e}")
        raise

async def play_agent_connect_question(websocket, lang: str):
    """Asks the user if they want to connect to a live agent."""
    prompt_text = AGENT_CONNECT_TEMPLATE.get(lang, AGENT_CONNECT_TEMPLATE["en-IN"])
    logger.tts.info(f"🔁 Converting agent connect question: {prompt_text}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
    await stream_audio_to_websocket(websocket, audio_bytes)

async def play_goodbye_after_decline(websocket, lang: str):
    """Plays a goodbye message if the user declines agent connection."""
    prompt_text = GOODBYE_TEMPLATE.get(lang, GOODBYE_TEMPLATE["en-IN"])
    logger.tts.info(f"🔁 Converting goodbye after decline: {prompt_text}")
    audio_bytes = await sarvam_handler.synthesize_tts(prompt_text, lang)
    await stream_audio_to_websocket(websocket, audio_bytes)

# --- Language and Intent Detection ---
def _is_devanagari(text): return any('\u0900' <= ch <= '\u097F' for ch in text)
def _is_tamil(text): return any('\u0B80' <= ch <= '\u0BFF' for ch in text)
def _is_telugu(text): return any('\u0C00' <= ch <= '\u0C7F' for ch in text)
def _is_kannada(text): return any('\u0C80' <= ch <= '\u0CFF' for ch in text)
def _is_malayalam(text): return any('\u0D00' <= ch <= '\u0D7F' for ch in text)
def _is_gujarati(text): return any('\u0A80' <= ch <= '\u0AFF' for ch in text)
def _is_marathi(text): return any('\u0900' <= ch <= '\u097F' for ch in text)
def _is_bengali(text): return any('\u0980' <= ch <= '\u09FF' for ch in text)
def _is_punjabi(text): return any('\u0A00' <= ch <= '\u0A7F' for ch in text)
def _is_oriya(text): return any('\u0B00' <= ch <= '\u0B7F' for ch in text)

def _is_gurmukhi(text):
    """Checks if the text contains any Gurmukhi characters (for Punjabi)."""
    return any('\u0A00' <= char <= '\u0A7F' for char in text)

def detect_language(text):
    text = text.strip().lower()
    
    # Enhanced English detection - check for common English words first
    english_words = [
        "yes", "yeah", "yep", "sure", "okay", "ok", "alright", "right", 
        "no", "nah", "nope", "not", "never",
        "hello", "hi", "hey", "good", "morning", "afternoon", "evening",
        "please", "thank", "thanks", "welcome", "sorry", "excuse",
        "what", "where", "when", "why", "how", "who", "which",
        "can", "could", "would", "should", "will", "shall", "may", "might",
        "i", "me", "my", "you", "your", "we", "our", "they", "their",
        "speak", "talk", "call", "phone", "agent", "person", "someone",
        "help", "support", "assistance", "service", "transfer", "connect"
    ]
    
    # Check if text contains primarily English words
    words = text.split()
    english_word_count = sum(1 for word in words if word in english_words)
    
    # If majority of words are English, return English
    if words and english_word_count >= len(words) * 0.5:  # At least 50% English words
        return "en-IN"
    
    # Check for specific language indicators
    if any(word in text for word in ["नमस्ते", "हां", "नहीं", "हाँ", "जी", "अच्छा"]) or _is_devanagari(text): 
        return "hi-IN"
    if any(word in text for word in ["வணக்கம்", "ஆம்", "இல்லை"]) or _is_tamil(text): 
        return "ta-IN"
    if any(word in text for word in ["హాయ్", "అవును", "కాదు"]) or _is_telugu(text): 
        return "te-IN"
    if any(word in text for word in ["ಹೆಲೋ", "ಹೌದು", "ಇಲ್ಲ"]) or _is_kannada(text): 
        return "kn-IN"
    if any(word in text for word in ["നമസ്കാരം", "അതെ", "ഇല്ല"]) or _is_malayalam(text): 
        return "ml-IN"
    if any(word in text for word in ["નમસ્તે", "હા", "ના"]) or _is_gujarati(text): 
        return "gu-IN"
    if any(word in text for word in ["नमस्कार", "होय", "नाही"]) or _is_marathi(text): 
        return "mr-IN"
    if any(word in text for word in ["নমস্কার", "হ্যাঁ", "না"]) or _is_bengali(text): 
        return "bn-IN"
    if any(word in text for word in ["ਸਤ ਸ੍ਰੀ ਅਕਾਲ", "ਹਾਂ", "ਨਹੀਂ"]) or _is_punjabi(text): 
        return "pa-IN"
    if any(word in text for word in ["ନମସ୍କାର", "ହଁ", "ନା"]) or _is_oriya(text): 
        return "or-IN"
    
    # Default to English if no specific language detected
    return "en-IN"

def detect_intent_with_claude(transcript: str, lang: str) -> str:
    """Detect intent for agent handoff using Claude via Bedrock. Returns 'affirmative'|'negative'|'unclear'."""
    logger.websocket.info(f"Getting intent for: '{transcript}'")
    try:
        # Build a precise, deterministic prompt for agent-handoff classification
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "You are classifying a user's short reply to this question: "
                            "'Would you like me to connect you to one of our agents to assist you better?'\n\n"
                            f"User reply (language={lang}): '{transcript}'\n\n"
                            "Classify strictly into one of: affirmative, negative, unclear.\n"
                            "- affirmative: yes/okay/sure/हाँ/ஆம்/etc (wants connection)\n"
                            "- negative: no/not now/नहीं/இல்லை/etc (does not want)\n"
                            "- unclear: ambiguous filler or unrelated\n\n"
                            "Respond with only one word: affirmative | negative | unclear"
                        ),
                    }
                ],
            }
        ]

        # bedrock_client.invoke_claude_model returns a plain string
        response_text = bedrock_client.invoke_claude_model(messages)
        intent = (response_text or "").strip().lower()

        # Normalize and validate
        if intent in ("affirmative", "negative", "unclear"):
            logger.websocket.info(f"Detected intent: {intent}")
            return intent
        # Try to infer if Claude returned a phrase
        if "affirmative" in intent:
            logger.websocket.info("Detected intent (normalized): affirmative")
            return "affirmative"
        if "negative" in intent:
            logger.websocket.info("Detected intent (normalized): negative")
            return "negative"
        logger.websocket.warning(f"Claude returned unexpected text: {intent}; defaulting to 'unclear'")
        return "unclear"
    except Exception as e:
        logger.websocket.error(f"❌ Error detecting intent with Claude: {e}")
        return "unclear"

def detect_intent_fur(text: str, lang: str) -> str:
    """A fallback intent detection function (a more descriptive name for the original detect_intent)."""
    return detect_intent(text)


def detect_intent(text):
    text = text.lower()
    if any(word in text for word in ["agent", "live agent", "speak to someone", "transfer", "help desk"]): return "agent_transfer"
    if any(word in text for word in ["yes", "yeah", "sure", "okay", "haan", "ஆம்", "அவுனு", "हॉं", "ಹೌದು", "please"]): return "affirmative"
    if any(word in text for word in ["no", "not now", "later", "nah", "nahi", "இல்லை", "காது", "ನಹಿ"]): return "negative"
    if any(word in text for word in ["what", "who", "why", "repeat", "pardon"]): return "confused"
    return "unknown"

# --- State to Language Mapping ---
STATE_TO_LANGUAGE = {
    'andhra pradesh': 'te-IN',
    'arunachal pradesh': 'hi-IN',
    'assam': 'hi-IN',
    'bihar': 'hi-IN',
    'chhattisgarh': 'hi-IN',
    'goa': 'hi-IN',
    'gujarat': 'gu-IN',
    'haryana': 'hi-IN',
    'himachal pradesh': 'hi-IN',
    'jharkhand': 'hi-IN',
    'karnataka': 'kn-IN',
    'kerala': 'ml-IN',
    'madhya pradesh': 'hi-IN',
    'maharashtra': 'mr-IN',
    'manipur': 'hi-IN',
    'meghalaya': 'hi-IN',
    'mizoram': 'hi-IN',
    'nagaland': 'hi-IN',
    'odisha': 'or-IN',
    'punjab': 'pa-IN',
    'rajasthan': 'hi-IN',
    'sikkim': 'hi-IN',
    'tamil nadu': 'ta-IN',
    'telangana': 'te-IN',
    'tripura': 'hi-IN',
    'uttar pradesh': 'hi-IN',
    'uttarakhand': 'hi-IN',
    'west bengal': 'bn-IN',
    'delhi': 'hi-IN',
    'puducherry': 'ta-IN',
    'chandigarh': 'hi-IN',
    'andaman and nicobar islands': 'hi-IN',
    'dadra and nagar haveli and daman and diu': 'hi-IN',
    'jammu and kashmir': 'hi-IN',
    'ladakh': 'hi-IN',
    'lakshadweep': 'ml-IN',
}

def get_initial_language_from_state(state: str) -> str:
    """Get the initial language based on customer's state."""
    if not state:
        return 'en-IN'
    return STATE_TO_LANGUAGE.get(state.strip().lower(), 'en-IN')


# --- Static Files and Templates ---
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="static")

# --- HTML Endpoints ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """
    Serves the improved dashboard HTML file at the root URL.
    """
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/original", response_class=HTMLResponse)
async def get_original_dashboard(request: Request):
    """
    Serves the original dashboard HTML file for backward compatibility.
    """
    return templates.TemplateResponse("index.html", {"request": request})

# --- WebSocket URL Generator for Exotel Flow ---
@app.get("/ws-url", response_class=PlainTextResponse)
async def generate_websocket_url(request: Request):
    """
    Generates the correct WebSocket URL for Exotel flow to connect to.
    This endpoint is called by Exotel flow to get the WebSocket URL dynamically.
    """
    logger.websocket.info("🔗 /ws-url endpoint hit")
    
    params = request.query_params
    call_sid = params.get("CallSid")
    custom_field = params.get("CustomField")
    from_number = params.get("From")
    
    logger.websocket.info(f"🔗 WebSocket URL request - CallSid: {call_sid}")
    logger.websocket.info(f"🔗 WebSocket URL request - CustomField: {custom_field}")
    logger.websocket.info(f"🔗 WebSocket URL request - From: {from_number}")
    
    # Parse temp_call_id from CustomField
    temp_call_id = None
    if custom_field:
        try:
            pairs = custom_field.split('|')
            for pair in pairs:
                if '=' in pair and pair.startswith('temp_call_id='):
                    temp_call_id = pair.split('=', 1)[1]
                    break
        except Exception as e:
            logger.error.error(f"🔗 Failed to parse temp_call_id from CustomField: {e}")
    
    # Use CallSid as session_id if available, otherwise use temp_call_id
    session_id = call_sid or temp_call_id or generate_websocket_session_id()
    
    # Get the base URL (ngrok URL)
    base_url = os.getenv('BASE_URL', 'http://localhost:8000')
    # Convert http to ws
    ws_base_url = base_url.replace('http://', 'ws://').replace('https://', 'wss://')
    
    # Generate the WebSocket URL with query parameters
    websocket_url = f"{ws_base_url}/ws/voicebot/{session_id}"
    
    # Add query parameters
    query_params = []
    if temp_call_id:
        query_params.append(f"temp_call_id={temp_call_id}")
    if call_sid:
        query_params.append(f"call_sid={call_sid}")
    if from_number:
        query_params.append(f"phone={from_number}")
    
    if query_params:
        websocket_url += "?" + "&".join(query_params)
    
    logger.websocket.info(f"🔗 Generated WebSocket URL: {websocket_url}")
    
    # Return the WebSocket URL as plain text for Exotel to use
    return websocket_url

# --- Exotel Passthru Handler ---
from fastapi.responses import PlainTextResponse

import threading

import asyncio
import threading
from fastapi.responses import PlainTextResponse

@app.post("/passthru-handler", response_class=PlainTextResponse)
async def handle_passthru(request: Request):
    """
    Handles Exotel's Passthru applet status callbacks.
    Exotel will POST form-encoded data (CallSid, Status, etc.).
    """
    logger.websocket.info("✅ /passthru-handler hit")

    # Read Exotel payload
    data = await request.form()
    form_dict = dict(data)
    logger.websocket.info(f"📨 FULL Exotel payload: {form_dict}")

    call_sid = data.get("CallSid")
    raw_status = data.get("Status")   # Exotel final status
    custom_field = data.get("CustomField")

    if not call_sid:
        logger.error.error("❌ Passthru handler called without a CallSid.")
        return "OK"

    logger.websocket.info(f"📞 Passthru: CallSid={call_sid}, Status={raw_status}")
    logger.websocket.info(f"📦 Passthru: CustomField={custom_field}")

    # --- Parse custom field if present ---
    customer_data = {}
    if custom_field:
        try:
            pairs = custom_field.split('|')
            for pair in pairs:
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    customer_data[key.strip()] = value.strip()
            logger.websocket.info(f"📊 Parsed Custom Fields: {customer_data}")
        except Exception as e:
            logger.error.error(f"❌ Failed to parse CustomField: {e}")

    temp_call_id = customer_data.get("temp_call_id")

    # --- Redis Caching ---
    if temp_call_id:
        redis_manager.link_session_to_sid(temp_call_id, call_sid)
    else:
        redis_manager.create_call_session(call_sid, customer_data)

    # --- Map Exotel raw status → internal status ---
    status_map = {
        "in-progress": "call_in_progress",
        "completed": "call_completed",
        "ringing": "ringing",
        "busy": "call_failed",
        "failed": "call_failed",
        "no-answer": "call_failed",
        "not-answered": "call_failed",
        "cancelled": "call_failed",
    }
    status = status_map.get(raw_status.lower() if raw_status else "", "call_failed")

    # --- Database Update ---
    try:
        logger.database.info(f"✍️ Updating database for CallSid={call_sid} with status={status}")
        session = db_manager.get_session()
        try:
            update_call_status(
                session=session,
                call_sid=call_sid,
                status=status,
                message=f"Passthru update - temp_call_id: {temp_call_id}"
            )
            session.commit()
            logger.database.info(f"✅ Database updated for CallSid={call_sid}")

            # 🔹 Auto-mark ringing → failed after 30s if no update
            if status == "ringing":
                def mark_call_failed_if_still_ringing(call_sid, customer_id):
                    s = db_manager.get_session()
                    try:
                        call_session = get_call_session_by_sid(s, call_sid)
                        if call_session and call_session.status == "ringing":
                            update_call_status(
                                s,
                                call_sid,
                                "call_failed",
                                "Auto-marked after ringing timeout"
                            )
                            s.commit()
                            logger.database.info(f"⏱️ Auto-marked CallSid={call_sid} as call_failed")

                            # Broadcast safely from thread
                            try:
                                loop = asyncio.get_event_loop()
                                loop.create_task(
                                    broadcast_status_update(call_sid, "call_failed", customer_id)
                                )
                            except RuntimeError:
                                asyncio.run(broadcast_status_update(call_sid, "call_failed", customer_id))
                    except Exception as e:
                        logger.error.error(f"❌ Auto-fail check failed for {call_sid}: {e}")
                    finally:
                        s.close()

                threading.Timer(30, mark_call_failed_if_still_ringing, args=[call_sid, customer_data.get("customer_id")]).start()

        finally:
            session.close()
    except Exception as e:
        logger.error.error(f"❌ Database update failed for CallSid {call_sid}: {e}")

    # --- Broadcast to frontend immediately ---
    try:
        await broadcast_status_update(call_sid, status, customer_data.get("customer_id"))
    except Exception as e:
        logger.error.error(f"❌ Failed to broadcast status update: {e}")

    # Always return OK so Exotel doesn’t retry
    return "OK"


@app.post("/flow-status", response_class=PlainTextResponse)
async def handle_flow_status(request: Request):
    """
    Handles status updates from ExoML flow.
    This endpoint receives status updates during the call flow execution.
    """
    logger.websocket.info("✅ /flow-status endpoint hit")

    # Read payload from Exotel
    data = await request.form()
    form_dict = dict(data)
    logger.websocket.info(f"📨 Flow status payload: {form_dict}")

    call_sid = form_dict.get("CallSid")
    status = form_dict.get("Status", "unknown")
    message = form_dict.get("Message", "")
    
    if call_sid:
        try:
            # Save status to call_status_updates table
            session = db_manager.get_session()
            try:
                from database.schemas import CallStatusUpdate, get_call_session_by_sid
                
                # Get the call session
                call_session = get_call_session_by_sid(session, call_sid)
                if call_session:
                    # Create status update record
                    status_update = CallStatusUpdate(
                        call_session_id=call_session.id,
                        status=status,
                        message=message,
                        extra_data=form_dict
                    )
                    session.add(status_update)
                    session.commit()
                    
                    logger.database.info(f"✅ Flow status saved: CallSid={call_sid}, Status={status}")
                    
                    # Broadcast to UI
                    await broadcast_status_update(call_sid, status, call_session.customer_id)
                else:
                    logger.database.warning(f"⚠️ Call session not found for CallSid: {call_sid}")
                    
            finally:
                session.close()
                
        except Exception as e:
            logger.error.error(f"❌ Failed to save flow status: {e}")

    return "OK"


EXOTEL_API_TOKEN="9ef71049188a5a603a0dbd9fd4c3f151de39443458add480"
EXOTEL_API_KEY="ce1c503fc544b72c570e0f56cd9f7dcffd85d24121ecc421"


# --- WebSocket Endpoint for Voicebot ---
async def handle_voicebot_websocket(websocket: WebSocket, session_id: str, temp_call_id: str = None, call_sid: str = None, phone: str = None):
    """
    Core voicebot WebSocket handling logic - extracted to be reusable.
    """
    logger.websocket.info(f"✅ Connected to Exotel Voicebot for session: {session_id}")

    # Initialize variables from parameters
    if not call_sid:
        call_sid = session_id  # Use session_id as a fallback for call_sid

    logger.websocket.info(f"Session params: temp_call_id={temp_call_id}, call_sid={call_sid}, phone={phone}")

    # State variable for the conversation stage
    conversation_stage = "INITIAL_GREETING" # States: INITIAL_GREETING, WAITING_FOR_LANG_DETECT, PLAYING_PERSONALIZED_GREETING, PLAYING_EMI_PART1, PLAYING_EMI_PART2, ASKING_AGENT_CONNECT, WAITING_AGENT_RESPONSE, TRANSFERRING_TO_AGENT, GOODBYE_DECLINE
    call_detected_lang = "en-IN" # Default language, will be updated after first user response
    audio_buffer = bytearray()
    last_transcription_time = time.time()
    interaction_complete = False # Flag to stop processing media after the main flow ends
    customer_info = None # Will be set when we get customer data
    initial_greeting_played = False # Track if initial greeting was played
    agent_question_repeat_count = 0 # Track how many times agent question was repeated

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            logger.log_websocket_message("Received message", msg)

            if msg.get("event") == "start":
                logger.websocket.info("🔁 Got start event")
                
                # Try to get customer info from multiple sources
                if not customer_info:
                    # 1. Try to get from Redis using temp_call_id or call_sid
                    if temp_call_id:
                        logger.database.info(f"Looking up customer data by temp_call_id: {temp_call_id}")
                        redis_data = redis_manager.get_call_session(temp_call_id)
                        if redis_data:
                            customer_info = {
                                'name': redis_data.get('name'),
                                'loan_id': redis_data.get('loan_id'),
                                'amount': redis_data.get('amount'),
                                'due_date': redis_data.get('due_date'),
                                'lang': redis_data.get('language_code', 'en-IN'),
                                'phone': redis_data.get('phone_number', ''),
                                'state': redis_data.get('state', '')
                            }
                            print(f"[WebSocket] ✅ Found customer data in Redis: {customer_info['name']}")
                    
                    elif call_sid:
                        print(f"[WebSocket] Looking up customer data by call_sid: {call_sid}")
                        redis_data = redis_manager.get_call_session(call_sid)
                        if redis_data:
                            customer_info = {
                                'name': redis_data.get('name'),
                                'loan_id': redis_data.get('loan_id'),
                                'amount': redis_data.get('amount'),
                                'due_date': redis_data.get('due_date'),
                                'lang': redis_data.get('language_code', 'en-IN'),
                                'phone': redis_data.get('phone_number', ''),
                                'state': redis_data.get('state', '')
                            }
                            print(f"[WebSocket] ✅ Found customer data in Redis: {customer_info['name']}")
                    
                    elif phone:
                        print(f"[WebSocket] Looking up customer data by phone: {phone}")
                        # Clean phone number for lookup
                        clean_phone = phone.replace('+', '').replace('-', '').replace(' ', '')
                        phone_key = f"customer_phone_{clean_phone}"
                        redis_data = redis_manager.get_temp_data(phone_key)
                        if redis_data:
                            customer_info = {
                                'name': redis_data.get('name'),
                                'loan_id': redis_data.get('loan_id'),
                                'amount': redis_data.get('amount'),
                                'due_date': redis_data.get('due_date'),
                                'lang': redis_data.get('language_code', 'en-IN'),
                                'phone': redis_data.get('phone_number', ''),
                                'state': redis_data.get('state', '')
                            }
                            print(f"[WebSocket] ✅ Found customer data by phone in Redis: {customer_info['name']}")
                
                # 2. Try to parse CustomField data from Exotel start message (if available)
                if not customer_info and 'customField' in msg:
                    print("[WebSocket] Parsing CustomField from Exotel start message")
                    try:
                        custom_field = msg['customField']
                        # Parse the CustomField format: "customer_id=|customer_name=Name|loan_id=LOAN123|..."
                        parts = custom_field.split('|')
                        custom_data = {}
                        for part in parts:
                            if '=' in part:
                                key, value = part.split('=', 1)
                                custom_data[key] = value
                        
                        customer_info = {
                            'name': custom_data.get('customer_name'),
                            'loan_id': custom_data.get('loan_id'),
                            'amount': custom_data.get('amount'),
                            'due_date': custom_data.get('due_date'),
                            'lang': custom_data.get('language_code', 'en-IN'),
                            'phone': '',
                            'state': custom_data.get('state', '')
                        }
                        print(f"[WebSocket] ✅ Parsed customer data from CustomField: {customer_info['name']}")
                    except Exception as e:
                        print(f"[WebSocket] ❌ Error parsing CustomField: {e}")
                
                # 3. Try to get customer data from database by phone number (if available)
                if not customer_info and phone:
                    print(f"[WebSocket] Looking up customer in database by phone: {phone}")
                    try:
                        from database.schemas import get_customer_by_phone
                        session = db_manager.get_session()
                        
                        # Clean phone number for database lookup - more comprehensive approach
                        clean_phone = phone.replace('+', '').replace('-', '').replace(' ', '')
                        
                        # Extract just the 10-digit number if it's an Indian number
                        if len(clean_phone) >= 10:
                            last_10_digits = clean_phone[-10:]
                        else:
                            last_10_digits = clean_phone
                        
                        # Try multiple phone number formats that might be in the database
                        possible_phones = [
                            phone,                      # Original format
                            clean_phone,               # Cleaned format
                            f"+{clean_phone}",         # With + prefix
                            f"+91{last_10_digits}",    # With +91 prefix
                            f"91{last_10_digits}",     # With 91 prefix (no +)
                            last_10_digits             # Just 10 digits
                        ]
                        
                        # Remove duplicates and empty values
                        possible_phones = list(set([p for p in possible_phones if p]))
                        print(f"[WebSocket] Trying phone formats: {possible_phones}")
                        
                        db_customer = None
                        for phone_variant in possible_phones:
                            db_customer = get_customer_by_phone(session, phone_variant)
                            if db_customer:
                                print(f"[WebSocket] ✅ Found customer with phone variant: {phone_variant}")
                                break
                        
                        if db_customer:
                            # Get the first loan for this customer
                            loan = db_customer.loans[0] if db_customer.loans else None
                            customer_info = {
                                'name': db_customer.full_name,
                                'loan_id': loan.loan_id if loan else 'N/A',
                                'amount': float(loan.outstanding_amount) if loan and loan.outstanding_amount else 0,
                                'due_date': loan.next_due_date.isoformat() if loan and loan.next_due_date else None,
                                'lang': 'en-IN',  # Default language
                                'phone': db_customer.primary_phone,
                                'state': db_customer.state or ''
                            }
                            print(f"[WebSocket] ✅ Found customer in database: {customer_info['name']} (Phone: {customer_info['phone']})")
                        else:
                            print(f"[WebSocket] ❌ Customer not found in database for phone: {phone}")
                        
                        session.close()
                    except Exception as e:
                        print(f"[WebSocket] ❌ Error looking up customer in database: {e}")
                
                # 4. If no customer found anywhere, throw an error instead of using fallback data
                if not customer_info:
                    print("[WebSocket] ❌ No customer data found - cannot proceed without real customer information")
                    await websocket.send_text(json.dumps({
                        "event": "error",
                        "message": "Customer data not found. Please ensure customer information is uploaded and call is triggered properly."
                    }))
                    return
                
                # 5. Validate customer data has required fields
                required_fields = ['name', 'loan_id', 'amount', 'due_date']
                missing_fields = [field for field in required_fields if not customer_info.get(field)]
                if missing_fields:
                    print(f"[WebSocket] ❌ Customer data missing required fields: {missing_fields}")
                    await websocket.send_text(json.dumps({
                        "event": "error",
                        "message": f"Customer data incomplete. Missing fields: {', '.join(missing_fields)}"
                    }))
                    return
                
                print(f"[WebSocket] ✅ Customer data validated: {customer_info['name']} - Loan: {customer_info['loan_id']}, Amount: ₹{customer_info['amount']}")
                
                # Determine initial language: prioritize state-based language over CSV language
                customer_state = customer_info.get('state', '').strip()
                state_based_language = get_initial_language_from_state(customer_state)
                csv_language = customer_info.get('lang', 'en-IN')
                
                # Use state language for initial greeting as requested
                initial_greeting_language = state_based_language
                logger.websocket.info(f"State: {customer_state}, State Language: {state_based_language}, CSV Language: {csv_language}")
                logger.websocket.info(f"Using state-based language for initial greeting: {initial_greeting_language}")
                
                # Play initial greeting immediately when WebSocket starts
                if conversation_stage == "INITIAL_GREETING":
                    logger.websocket.info(f"1. Playing initial greeting for {customer_info['name']} in {initial_greeting_language} (state-based)")
                    try:
                        # Use the working template approach with state-based language
                        await greeting_template_play(websocket, customer_info, lang=initial_greeting_language)
                        logger.websocket.info(f"✅ Initial greeting played successfully in {initial_greeting_language}")
                        initial_greeting_played = True
                        conversation_stage = "WAITING_FOR_LANG_DETECT"
                    except Exception as e:
                        logger.websocket.error(f"❌ Error playing initial greeting: {e}")
                        # Try fallback simple greeting in English
                        try:
                            simple_greeting = f"Hello, this is South India Finvest Bank calling. Am I speaking with {customer_info['name']}?"
                            audio_bytes = await sarvam_handler.synthesize_tts_end(simple_greeting, "en-IN")
                            await stream_audio_to_websocket(websocket, audio_bytes)
                            logger.websocket.info("✅ Fallback greeting sent successfully")
                            initial_greeting_played = True
                            conversation_stage = "WAITING_FOR_LANG_DETECT"
                        except Exception as fallback_e:
                            logger.websocket.error(f"❌ Error sending fallback greeting: {fallback_e}")
                continue

            if msg.get("event") == "media":
                payload_b64 = msg["media"]["payload"]
                raw_audio = base64.b64decode(payload_b64)

                if interaction_complete:
                    continue

                if raw_audio and any(b != 0 for b in raw_audio):
                    audio_buffer.extend(raw_audio)
                
                now = time.time()

                # Stage-specific buffer timeout: wait longer for agent response
                buffer_timeout = AGENT_RESPONSE_BUFFER_DURATION if conversation_stage == "WAITING_AGENT_RESPONSE" else BUFFER_DURATION_SECONDS

                if now - last_transcription_time >= buffer_timeout:
                    if len(audio_buffer) == 0:
                        if conversation_stage == "WAITING_FOR_LANG_DETECT":
                            logger.websocket.info("No audio received during language detection stage. Playing 'didn't hear' prompt.")
                            logger.log_call_event("NO_AUDIO_LANG_DETECT", call_sid, customer_info['name'])
                            await play_did_not_hear_response(websocket, call_detected_lang)
                            # Reset the timer to wait for user response
                            last_transcription_time = time.time()
                        elif conversation_stage == "WAITING_AGENT_RESPONSE":
                            agent_question_repeat_count += 1
                            if agent_question_repeat_count <= 2:  # Limit to 2 repeats
                                logger.websocket.info(f"No audio received during agent question stage. Repeating question (attempt {agent_question_repeat_count}/2).")
                                logger.log_call_event("AGENT_QUESTION_REPEAT", call_sid, customer_info['name'], {"attempt": agent_question_repeat_count})
                                await play_agent_connect_question(websocket, call_detected_lang)
                                # Reset the timer to wait for user response
                                last_transcription_time = time.time()
                            else:
                                logger.websocket.info("Too many no-audio responses. Assuming user wants agent transfer.")
                                logger.log_call_event("AUTO_AGENT_TRANSFER_NO_AUDIO", call_sid, customer_info['name'])
                                customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
                                await play_transfer_to_agent(websocket, customer_number=customer_number) 
                                conversation_stage = "TRANSFERRING_TO_AGENT"
                                interaction_complete = True
                                # Wait for transfer message to be sent before ending loop
                                await asyncio.sleep(2)
                                break
                        audio_buffer.clear()
                        last_transcription_time = now
                        continue

                    try:
                        # Ignore too-short buffers that yield empty transcripts
                        if len(audio_buffer) < MIN_AUDIO_BYTES:
                            audio_buffer.clear()
                            last_transcription_time = now
                            continue
                        transcript = await sarvam_handler.transcribe_from_payload(audio_buffer)
                        if isinstance(transcript, tuple):
                            transcript_text, detected_language = transcript
                            # Update the detected language if it was determined during transcription
                            if detected_language and detected_language != "en-IN":
                                call_detected_lang = detected_language
                                logger.websocket.info(f"🌐 Language updated from transcription: {call_detected_lang}")
                            transcript = transcript_text
                        elif isinstance(transcript, str):
                            # Fallback for older handler compatibility
                            pass
                        else:
                            transcript = ""
                        logger.websocket.info(f"📝 Transcript: {transcript}")
                        logger.log_call_event("TRANSCRIPT_RECEIVED", call_sid, customer_info['name'], {"transcript": transcript, "stage": conversation_stage})

                        if transcript:
                            if conversation_stage == "WAITING_FOR_LANG_DETECT":
                                # Detect user's preferred language from their response
                                user_detected_lang = detect_language(transcript)
                                logger.websocket.info(f"🎯 User Response Language Detection:")
                                logger.websocket.info(f"   📍 State-mapped language: {initial_greeting_language}")
                                logger.websocket.info(f"   🗣️  User detected language: {user_detected_lang}")
                                logger.websocket.info(f"   📄 CSV language: {csv_language}")
                                logger.log_call_event("LANGUAGE_DETECTED", call_sid, customer_info['name'], {
                                    "detected_lang": user_detected_lang, 
                                    "state_lang": initial_greeting_language,
                                    "csv_lang": csv_language,
                                    "transcript": transcript
                                })
                                
                                # Enhanced Language Switching Logic
                                if user_detected_lang != initial_greeting_language:
                                    logger.websocket.info(f"🔄 Language Mismatch Detected!")
                                    logger.websocket.info(f"   Initial greeting was in: {initial_greeting_language}")
                                    logger.websocket.info(f"   User responded in: {user_detected_lang}")
                                    logger.websocket.info(f"   🔄 Switching entire conversation to: {user_detected_lang}")
                                    logger.log_call_event("LANGUAGE_SWITCH_DETECTED", call_sid, customer_info['name'], {
                                        "from_lang": initial_greeting_language,
                                        "to_lang": user_detected_lang,
                                        "reason": "user_preference"
                                    })
                                    
                                    # Replay greeting in user's preferred language
                                    try:
                                        logger.websocket.info(f"🔁 Replaying greeting in user's language: {user_detected_lang}")
                                        await greeting_template_play(websocket, customer_info, lang=user_detected_lang)
                                        logger.websocket.info(f"✅ Successfully replayed greeting in {user_detected_lang}")
                                        logger.log_call_event("GREETING_REPLAYED_NEW_LANG", call_sid, customer_info['name'], {"new_lang": user_detected_lang})
                                        
                                        # Update the conversation language to user's preference
                                        call_detected_lang = user_detected_lang
                                        
                                        # Give user a moment to acknowledge the language switch
                                        await asyncio.sleep(1)
                                        
                                    except Exception as e:
                                        logger.websocket.error(f"❌ Error replaying greeting in {user_detected_lang}: {e}")
                                        logger.log_call_event("GREETING_REPLAY_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                                        # Fallback to user's detected language anyway
                                        call_detected_lang = user_detected_lang
                                        
                                else:
                                    logger.websocket.info(f"✅ Language Consistency Confirmed!")
                                    logger.websocket.info(f"   User responded in same language as greeting: {user_detected_lang}")
                                    logger.log_call_event("LANGUAGE_CONSISTENT", call_sid, customer_info['name'], {"language": user_detected_lang})
                                    call_detected_lang = user_detected_lang
                                
                                # Final language confirmation
                                logger.websocket.info(f"🎉 Final Conversation Language: {call_detected_lang}")
                                logger.log_call_event("FINAL_LANGUAGE_SET", call_sid, customer_info['name'], {"final_lang": call_detected_lang})
                                
                                # Play EMI details in final determined language
                                try:
                                    await play_emi_details_part1(websocket, customer_info or {}, call_detected_lang)
                                    await play_emi_details_part2(websocket, customer_info or {}, call_detected_lang)
                                    await play_agent_connect_question(websocket, call_detected_lang)
                                    conversation_stage = "WAITING_AGENT_RESPONSE"
                                    logger.tts.info(f"✅ EMI details and agent question sent successfully in {call_detected_lang}")
                                    logger.log_call_event("EMI_DETAILS_SENT", call_sid, customer_info['name'], {"language": call_detected_lang})
                                except Exception as e:
                                    logger.tts.error(f"❌ Error playing EMI details: {e}")
                                    logger.log_call_event("EMI_DETAILS_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                            
                            elif conversation_stage == "WAITING_AGENT_RESPONSE":
                                # Use Claude for intent detection
                                try:
                                    intent = detect_intent_with_claude(transcript, call_detected_lang)
                                    logger.websocket.info(f"Claude detected intent: {intent}")
                                    logger.log_call_event("INTENT_DETECTED_CLAUDE", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript})
                                except Exception as e:
                                    logger.websocket.error(f"❌ Error in Claude intent detection: {e}")
                                    # Fallback to keyword-based detection
                                    intent = detect_intent_fur(transcript, call_detected_lang)
                                    logger.websocket.info(f"Fallback intent detection: {intent}")
                                    logger.log_call_event("INTENT_DETECTED_FALLBACK", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript})

                                if intent == "affirmative" or intent == "agent_transfer":
                                    if conversation_stage != "TRANSFERRING_TO_AGENT":  # Prevent multiple transfers
                                        logger.websocket.info("User affirmed agent transfer. Initiating transfer.")
                                        logger.log_call_event("AGENT_TRANSFER_INITIATED", call_sid, customer_info['name'], {"intent": intent})
                                        customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
                                        await play_transfer_to_agent(websocket, customer_number=customer_number) 
                                        conversation_stage = "TRANSFERRING_TO_AGENT"
                                        interaction_complete = True
                                        # Wait for a moment before closing to ensure transfer message is sent
                                        await asyncio.sleep(2)
                                        break
                                    else:
                                        logger.websocket.warning("⚠️ Agent transfer already in progress, ignoring duplicate request")
                                elif intent == "negative":
                                    if conversation_stage != "GOODBYE_DECLINE":  # Prevent multiple goodbyes
                                        logger.websocket.info("User declined agent transfer. Saying goodbye.")
                                        logger.log_call_event("AGENT_TRANSFER_DECLINED", call_sid, customer_info['name'])
                                        await play_goodbye_after_decline(websocket, call_detected_lang)
                                        conversation_stage = "GOODBYE_DECLINE"
                                        interaction_complete = True
                                        # Wait for goodbye message to be sent before closing
                                        await asyncio.sleep(3)
                                        break
                                    else:
                                        logger.websocket.warning("⚠️ Goodbye already sent, ignoring duplicate request")
                                else:
                                    agent_question_repeat_count += 1
                                    if agent_question_repeat_count <= 2:  # Limit to 2 repeats
                                        logger.websocket.info(f"Unclear response to agent connect. Repeating question (attempt {agent_question_repeat_count}/2).")
                                        logger.log_call_event("AGENT_QUESTION_UNCLEAR_REPEAT", call_sid, customer_info['name'], {"attempt": agent_question_repeat_count})
                                        await play_agent_connect_question(websocket, call_detected_lang)
                                        # Reset the timer to wait for user response
                                        last_transcription_time = time.time()
                                    else:
                                        logger.websocket.info("Too many unclear responses. Assuming user wants agent transfer.")
                                        logger.log_call_event("AUTO_AGENT_TRANSFER_UNCLEAR", call_sid, customer_info['name'])
                                        customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
                                        await play_transfer_to_agent(websocket, customer_number=customer_number) 
                                        conversation_stage = "TRANSFERRING_TO_AGENT"
                                        interaction_complete = True
                                        # Wait for transfer message to be sent before closing
                                        await asyncio.sleep(2)
                                        break
                            # Add more elif conditions here for additional conversation stages if your flow extends
                    except Exception as e:
                        logger.websocket.error(f"❌ Error processing transcript: {e}")
                        logger.log_call_event("TRANSCRIPT_PROCESSING_ERROR", call_sid, customer_info['name'] if customer_info else 'Unknown', {"error": str(e)})

                    audio_buffer.clear()
                    last_transcription_time = now

    except Exception as e:
        logger.error.error(f"WebSocket compatibility error: {e}")
        logger.log_call_event("WEBSOCKET_COMPATIBILITY_ERROR", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown', {"error": str(e)})
    finally:
        # Ensure the websocket is closed gracefully only after conversation is complete
        try:
            if not interaction_complete:
                # If we're exiting due to an error before conversation completion, wait a bit
                await asyncio.sleep(1)
            
            if websocket.client_state.name not in ['DISCONNECTED']:
                await websocket.close()
                logger.websocket.info("🔒 WebSocket connection closed gracefully")
            else:
                logger.websocket.info("🔒 WebSocket already disconnected")
        except Exception as close_error:
            logger.error.error(f"Error closing WebSocket: {close_error}")
        logger.log_call_event("WEBSOCKET_CLOSED_GRACEFUL", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown')


# --- WebSocket Endpoint for Voicebot ---
@app.websocket("/ws/voicebot/{session_id}")
async def websocket_voicebot_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    
    # Initialize variables from query parameters
    query_params = dict(websocket.query_params)
    temp_call_id = query_params.get('temp_call_id')
    call_sid = query_params.get('call_sid', session_id) # Use session_id as a fallback for call_sid
    phone = query_params.get('phone')

    # Use the shared handler
    await handle_voicebot_websocket(websocket, session_id, temp_call_id, call_sid, phone)

# --- WebSocket Endpoint for Dashboard ---
@app.websocket("/ws/dashboard/{session_id}")
async def websocket_dashboard_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    active_connections.append(websocket)
    print(f"Dashboard connected: {session_id}")
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        print(f"Dashboard disconnected: {session_id}")
        active_connections.remove(websocket)


# --- API Endpoints for Dashboard ---

class CustomerData(BaseModel):
    name: str
    phone: str
    loan_id: str
    amount: str
    due_date: str
    state: str
    language_code: str

@app.post("/api/upload-customers")
async def upload_customers(file: UploadFile = File(...)):
    """
    Accepts a CSV file with the new format and processes it using the enhanced CSV processor.
    Expected CSV columns: name,phone,loan_id,amount,due_date,state,Cluster,Branch,
    Branch Contact Number,Employee,Employee ID,Employee Contact Number,
    Last Paid Date,Last Paid Amount,Due Amount
    """
    print(f"📁 [CHECKPOINT] /api/upload-customers endpoint hit")
    print(f"📁 [CHECKPOINT] File name: {file.filename}")
    print(f"📁 [CHECKPOINT] File content type: {file.content_type}")
    
    try:
        # Validate file type
        if not file.filename.lower().endswith('.csv'):
            return {
                "success": False, 
                "error": "Only CSV files are supported with the new format"
            }
        
        file_data = await file.read()
        print(f"📁 [CHECKPOINT] File size: {len(file_data)} bytes")
        
        # Use the enhanced CSV service
        from services.enhanced_csv_upload_service import enhanced_csv_service
        result = await enhanced_csv_service.upload_and_process_csv(
            file_data=file_data,
            filename=file.filename,
            uploaded_by="dashboard_user"  # TODO: Get from auth context
        )
        
        print(f"📁 [CHECKPOINT] Enhanced CSV processing result: {result}")
        return result
        
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in upload_customers endpoint: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/uploaded-files")
async def get_uploaded_files():
    """
    Retrieves all uploaded file records with their processing details.
    """
    print(f"📄 [CHECKPOINT] /api/uploaded-files endpoint hit")
    
    try:
        from database.schemas import get_session, FileUpload
        from sqlalchemy import desc
        
        session = get_session()
        try:
            # Get all file uploads ordered by upload date (newest first)
            file_uploads = session.query(FileUpload).order_by(desc(FileUpload.uploaded_at)).all()
            
            # Convert to list of dictionaries with detailed information
            upload_data = []
            for upload in file_uploads:
                upload_info = {
                    'id': str(upload.id),
                    'filename': upload.filename,
                    'original_filename': upload.original_filename,
                    'uploaded_by': upload.uploaded_by,
                    'uploaded_at': upload.uploaded_at.isoformat() if upload.uploaded_at else None,
                    'total_records': upload.total_records,
                    'processed_records': upload.processed_records,
                    'success_records': upload.success_records,
                    'failed_records': upload.failed_records,
                    'status': upload.status,
                    'processing_errors': upload.processing_errors,
                    # Computed fields
                    'file_size_bytes': 0,  # Not stored in current schema
                    'duplicate_records': 0,  # Not tracked separately
                    'processing_started_at': None,  # Not stored in current schema
                    'processing_completed_at': None,  # Not stored in current schema
                    'validation_errors': None,  # Not stored in current schema
                    'metadata': None  # Not stored in current schema
                }
                upload_data.append(upload_info)
            
            print(f"📄 [CHECKPOINT] Found {len(upload_data)} uploaded files")
            return {
                'success': True,
                'uploads': upload_data,
                'total_count': len(upload_data)
            }
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in get_uploaded_files endpoint: {e}")
        return {"success": False, "error": str(e), "uploads": []}

@app.get("/api/uploaded-files/{upload_id}/details")
async def get_upload_details(upload_id: str):
    """
    Retrieves detailed information about a specific upload including individual row processing results.
    """
    print(f"📄 [CHECKPOINT] /api/uploaded-files/{upload_id}/details endpoint hit")
    
    try:
        from database.schemas import get_session, FileUpload, UploadRow
        
        session = get_session()
        try:
            # Get the file upload record
            upload = session.query(FileUpload).filter(FileUpload.id == upload_id).first()
            
            if not upload:
                return {"success": False, "error": "Upload not found"}
            
            # Get associated upload rows
            upload_rows = session.query(UploadRow).filter(UploadRow.file_upload_id == upload_id).all()
            
            # Convert upload rows to detailed information
            row_details = []
            for row in upload_rows:
                row_info = {
                    'id': str(row.id),
                    'line_number': row.line_number,
                    'raw_data': row.raw_data,
                    'status': row.status,
                    'error': row.error,
                    'match_method': row.match_method,
                    'match_customer_id': str(row.match_customer_id) if row.match_customer_id else None,
                    'match_loan_id': str(row.match_loan_id) if row.match_loan_id else None,
                    'created_at': row.matched_at.isoformat() if row.matched_at else None
                }
                row_details.append(row_info)
            
            # Upload summary
            upload_details = {
                'id': str(upload.id),
                'filename': upload.filename,
                'original_filename': upload.original_filename,
                'uploaded_by': upload.uploaded_by,
                'uploaded_at': upload.uploaded_at.isoformat() if upload.uploaded_at else None,
                'total_records': upload.total_records,
                'processed_records': upload.processed_records,
                'success_records': upload.success_records,
                'failed_records': upload.failed_records,
                'status': upload.status,
                'processing_errors': upload.processing_errors,
                'rows': row_details,
                # Fields not in current schema
                'file_size_bytes': 0,
                'duplicate_records': 0,
                'processing_started_at': None,
                'processing_completed_at': None,
                'validation_errors': None,
                'metadata': None
            }
            
            print(f"📄 [CHECKPOINT] Retrieved details for upload {upload_id} with {len(row_details)} rows")
            return {
                'success': True,
                'upload_details': upload_details
            }
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in get_upload_details endpoint: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/uploaded-files/{upload_id}/download")
async def download_batch_report(upload_id: str):
    """
    Downloads a CSV report for a specific batch upload.
    """
    print(f"📄 [CHECKPOINT] /api/uploaded-files/{upload_id}/download endpoint hit")
    
    try:
        from database.schemas import get_session, FileUpload, UploadRow
        from fastapi.responses import StreamingResponse
        import io
        import csv
        
        session = get_session()
        try:
            # Get the upload record
            upload = session.query(FileUpload).filter(FileUpload.id == upload_id).first()
            if not upload:
                raise HTTPException(status_code=404, detail="Upload not found")
            
            # Get upload rows for this batch
            upload_rows = session.query(UploadRow).filter(UploadRow.file_upload_id == upload_id).all()
            
            # Create CSV content
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            headers = [
                'Line Number', 'Status', 'Customer Name', 'Phone', 'Loan ID', 
                'Amount', 'Due Date', 'State', 'Cluster', 'Branch',
                'Match Method', 'Error Message', 'Processed At'
            ]
            writer.writerow(headers)
            
            # Write data rows
            for row in upload_rows:
                raw_data = row.raw_data or {}
                writer.writerow([
                    row.line_number,
                    row.status,
                    raw_data.get('name', ''),
                    raw_data.get('phone', ''),
                    raw_data.get('loan_id', ''),
                    raw_data.get('amount', ''),
                    raw_data.get('due_date', ''),
                    raw_data.get('state', ''),
                    raw_data.get('cluster', ''),
                    raw_data.get('branch', ''),
                    row.match_method or '',
                    row.error or '',
                    row.matched_at.isoformat() if row.matched_at else ''
                ])
            
            # Create response
            output.seek(0)
            filename = f"batch_report_{upload.filename}_{upload.uploaded_at.strftime('%Y%m%d_%H%M%S')}.csv"
            
            print(f"📄 [CHECKPOINT] Generated CSV report for upload {upload_id} with {len(upload_rows)} rows")
            
            return StreamingResponse(
                io.BytesIO(output.getvalue().encode('utf-8')),
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
            
        finally:
            session.close()
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in download_batch_report endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession



@app.post("/api/trigger-single-call")
async def trigger_single_call(customer_id: str = Body(..., embed=True)):
    """
    Triggers a single call to a customer by their ID and starts polling for status.
    """
    print(f"🚀 [CHECKPOINT] /api/trigger-single-call endpoint hit")
    print(f"🚀 [CHECKPOINT] Customer ID: {customer_id}")
    
    try:
        result = await call_service.trigger_single_call(customer_id)
        print(f"🚀 [CHECKPOINT] Call service result: {result}")

        call_sid = result.get("call_sid")
        if call_sid:
            asyncio.create_task(poll_exotel_call_status(call_sid, customer_id))
            print(f"🚀 [CHECKPOINT] Polling started for CallSid: {call_sid}")
        else:
            print("⚠️ [CHECKPOINT] No call_sid found in result, polling not started")

        return result

    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in trigger_single_call endpoint: {e}")
        return {"success": False, "error": str(e)}


@app.post("/api/trigger-bulk-calls")
async def trigger_bulk_calls(customer_ids: list[str] = Body(..., embed=True)):
    """
    Triggers calls to a list of customers by their IDs.
    """
    print(f"🚀 [CHECKPOINT] /api/trigger-bulk-calls endpoint hit")
    print(f"🚀 [CHECKPOINT] Customer IDs: {customer_ids}")
    print(f"🚀 [CHECKPOINT] Number of customers: {len(customer_ids)}")
    
    try:
        result = await call_service.trigger_bulk_calls(customer_ids)
        print(f"🚀 [CHECKPOINT] Bulk call service result: {result}")
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in trigger_bulk_calls endpoint: {e}")
        return {"success": False, "error": str(e)}
    

@app.get("/api/customers")
async def get_all_customers():
    """
    Retrieves all customers with their loan information from the database.
    Updated to support new CSV schema with enhanced data.
    """
    print(f"👥 [CHECKPOINT] /api/customers endpoint hit")
    
    from database.schemas import get_session
    session = get_session()
    try:
        # Query customers with their loans and call sessions
        from database.schemas import CallSession
        customers = session.query(Customer).options(
            joinedload(Customer.loans),
            joinedload(Customer.call_sessions)
        ).all()
        print(f"👥 [CHECKPOINT] Found {len(customers)} customers in database")
        
        result = []
        for customer in customers:
            # Calculate totals from loans
            total_outstanding = sum(loan.outstanding_amount or 0 for loan in customer.loans)
            total_due = sum(loan.due_amount or 0 for loan in customer.loans)
            total_loans = len(customer.loans)
            
            # Get primary loan data (first loan or most recent)
            primary_loan = customer.loans[0] if customer.loans else None
            
            # Get latest call status from call sessions
            latest_call_status = "ready"  # Default status
            if customer.call_sessions:
                # Sort call sessions by created_at descending to get the latest
                latest_session = sorted(customer.call_sessions, key=lambda x: x.created_at, reverse=True)[0]
                latest_call_status = latest_session.status or "ready"
            
            customer_data = {
                "id": str(customer.id),
                "full_name": customer.full_name,
                "primary_phone": customer.primary_phone,
                "state": customer.state,
                "email": customer.email,
                "national_id": customer.national_id,
                "do_not_call": customer.do_not_call,
                "first_uploaded_at": format_ist_datetime(customer.first_uploaded_at),
                "last_contact_date": format_ist_datetime(customer.last_contact_date),
                "created_at": format_ist_datetime(customer.created_at),
                "updated_at": format_ist_datetime(customer.updated_at),
                "call_status": latest_call_status,  # Use latest call status from call sessions
                
                # Loan aggregation data
                "total_loans": total_loans,
                "total_outstanding": float(total_outstanding),
                "total_due": float(total_due),
                
                # Primary loan details (from first loan)
                "loan_id": primary_loan.loan_id if primary_loan else None,
                "outstanding_amount": float(primary_loan.outstanding_amount or 0) if primary_loan else 0,
                "due_amount": float(primary_loan.due_amount or 0) if primary_loan else 0,
                "next_due_date": format_ist_datetime(primary_loan.next_due_date) if primary_loan and primary_loan.next_due_date else None,
                "last_paid_date": format_ist_datetime(primary_loan.last_paid_date) if primary_loan and primary_loan.last_paid_date else None,
                "last_paid_amount": float(primary_loan.last_paid_amount or 0) if primary_loan else 0,
                
                # Branch and employee information (from primary loan)
                "cluster": primary_loan.cluster if primary_loan else None,
                "branch": primary_loan.branch if primary_loan else None,
                "branch_contact_number": primary_loan.branch_contact_number if primary_loan else None,
                "employee_name": primary_loan.employee_name if primary_loan else None,
                "employee_id": primary_loan.employee_id if primary_loan else None,
                "employee_contact_number": primary_loan.employee_contact_number if primary_loan else None,
                
                # All loans details
                "loans": [
                    {
                        "id": str(loan.id),
                        "loan_id": loan.loan_id,
                        "outstanding_amount": float(loan.outstanding_amount or 0),
                        "due_amount": float(loan.due_amount or 0),
                        "next_due_date": format_ist_datetime(loan.next_due_date),
                        "last_paid_date": format_ist_datetime(loan.last_paid_date),
                        "last_paid_amount": float(loan.last_paid_amount or 0),
                        "status": loan.status,
                        "cluster": loan.cluster,
                        "branch": loan.branch,
                        "branch_contact_number": loan.branch_contact_number,
                        "employee_name": loan.employee_name,
                        "employee_id": loan.employee_id,
                        "employee_contact_number": loan.employee_contact_number,
                        "created_at": format_ist_datetime(loan.created_at),
                        "updated_at": format_ist_datetime(loan.updated_at)
                    } for loan in customer.loans
                ]
            }
            
            result.append(customer_data)
        
        print(f"👥 [CHECKPOINT] Returning customer list successfully")
        return result
    except Exception as e:
        print(f"❌ [CHECKPOINT] Exception in get_all_customers endpoint: {e}")
        return []
    finally:
        session.close()

from fastapi import Request
from database.schemas import (
    db_manager,
    update_call_status,
    get_call_session_by_sid,
    update_customer_call_status_by_phone
)


@app.post("/exotel-webhook")
async def exotel_webhook(request: Request):
    """
    Handles Exotel call status webhooks and updates DB + Customer status.
    """
    form_data = await request.form()
    form_dict = dict(form_data)

    print("📩 Webhook received:", form_dict)

    call_sid = form_dict.get("CallSid")
    exotel_status = form_dict.get("CallStatus")

    print("📩 Raw Exotel Status:", exotel_status)

    # Map Exotel → internal statuses (used in DB + frontend)
    status_mapping = {
        "initiated": "initiated",
        "ringing": "call_in_progress",
        "answered": "call_in_progress",
        "in-progress": "call_in_progress",
        "completed": "call_completed",
        "failed": "call_failed",
        "busy": "call_failed",
        "no-answer": "call_failed",
        "not-answered": "call_failed",
        "canceled": "call_failed",
        "cancelled": "call_failed",
    }

    internal_status = status_mapping.get(exotel_status.lower(), "call_failed") if exotel_status else "call_failed"

    # --- Database update ---
    session = db_manager.get_session()
    try:
        call_session = get_call_session_by_sid(session, call_sid)
        if call_session:
            print(f"✅ Found call session for CallSid={call_sid}")
            
            # Update CallSession
            update_call_status(
                session,
                call_sid,
                internal_status,
                f"Exotel webhook: {exotel_status}",
                extra_data=form_dict
            )

            # Save to call_status_updates table
            from database.schemas import CallStatusUpdate
            status_update = CallStatusUpdate(
                call_session_id=call_session.id,
                status=internal_status,
                message=f"Exotel webhook: {exotel_status}",
                extra_data=form_dict
            )
            session.add(status_update)

            # Update Customer
            if call_session.customer:
                print(f"✅ Found customer for call: {call_session.customer.full_name} ({call_session.customer.primary_phone})")
                update_customer_call_status_by_phone(
                    session,
                    call_session.customer.primary_phone,
                    internal_status
                )
            else:
                print(f"⚠️ No customer found for call session CallSid={call_sid}")

            session.commit()
            print(f"✅ CallSid={call_sid} updated → {internal_status}")
        else:
            print(f"⚠️ No call session found for CallSid={call_sid}")

    except Exception as e:
        session.rollback()
        print(f"❌ Error updating call status: {e}")
    finally:
        db_manager.close_session(session)

    return {"status": "ok"}


async def poll_exotel_call_status(call_sid: str, customer_id: str, interval: int = 10, max_attempts: int = 20):
    """
    Polls Exotel API for call status and updates DB until call is completed or max attempts reached.
    Uses db_manager instead of SessionLocal and maps Exotel statuses → internal statuses.
    """
    url = f"https://api.exotel.com/v1/Accounts/{EXOTEL_SID}/Calls/{call_sid}.json"
    auth = (EXOTEL_API_KEY, EXOTEL_API_TOKEN)

    status_map = {
        "in-progress": "call_in_progress",
        "answered": "call_in_progress",
        "completed": "call_completed",
        "failed": "call_failed",
        "busy": "call_failed",
        "no-answer": "call_failed",
        "not-answered": "call_failed",
        "canceled": "call_failed",
        "cancelled": "call_failed",
    }

    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, auth=auth)

            if response.status_code == 200:
                call_data = response.json().get("Call", {})
                raw_status = call_data.get("Status", "").lower()
                end_time = call_data.get("EndTime")
                duration = call_data.get("Duration")

                logger.websocket.info(f"📞 [POLL] Call {call_sid} status: {raw_status}")

                # Map to internal status
                status = status_map.get(raw_status, "call_failed")

                # --- DB Update ---
                session = db_manager.get_session()
                try:
                    # Update call_sessions
                    call_session = get_call_session_by_sid(session, call_sid)
                    if call_session:
                        update_call_status(
                            session=session,
                            call_sid=call_sid,
                            status=status,
                            message=f"Polled Exotel: {raw_status}",
                            extra_data=call_data
                        )

                    # Update customers
                    customer = session.query(Customer).filter_by(id=customer_id).first()
                    if customer:
                        customer.call_status = status
                        customer.updated_at = datetime.utcnow()

                    session.commit()
                    logger.database.info(f"✅ [POLL] DB updated: {call_sid} → {status}")

                    # --- Broadcast ---
                    await broadcast_status_update(call_sid, status, customer_id)

                finally:
                    session.close()

                # Stop polling if final status reached
                if raw_status in ["completed", "failed", "busy", "no-answer", "canceled", "cancelled"]:
                    logger.websocket.info(f"✅ [POLL] Final status for {call_sid}: {status}")
                    break

            else:
                logger.error.error(f"⚠️ [POLL] Failed to fetch status for {call_sid}. HTTP {response.status_code}")

        except Exception as e:
            logger.error.error(f"❌ [POLL] Error while polling Exotel: {e}")

        await asyncio.sleep(interval)






@app.post("/api/update-customer-status")
async def update_customer_status(request: Request):
    """Update customer call status in the database"""
    try:
        data = await request.json()
        customer_id = data.get('customer_id')
        call_status = data.get('call_status')
        
        if not customer_id or not call_status:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Missing customer_id or call_status"}
            )
        
        session = db_manager.get_session()  # Use db_manager to get session
        try:
            # Update customer call status
            update_customer_call_status(
                session,
                customer_id,
                call_status
            )
            session.commit()
            return JSONResponse(
                status_code=200,
                content={"success": True, "message": f"Customer status updated to {call_status}"}
            )
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [API] Error updating customer status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Internal server error: {str(e)}"}
        )

@app.post("/api/update-bulk-customer-status")
async def update_bulk_customer_status(request: Request):
    """Update multiple customer call statuses in the database"""
    try:
        data = await request.json()
        customer_ids = data.get('customer_ids', [])
        call_status = data.get('call_status')
        
        if not customer_ids or not call_status:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Missing customer_ids or call_status"}
            )
        
        session = db_manager.get_session()  # Use db_manager to get session
        try:
            updated_count = 0
            for customer_id in customer_ids:
                if update_customer_call_status(session, customer_id, call_status):
                    updated_count += 1
            session.commit()
            return JSONResponse(
                status_code=200,
                content={
                    "success": True, 
                    "message": f"Updated {updated_count}/{len(customer_ids)} customers to {call_status}"
                }
            )
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [API] Error updating bulk customer status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Internal server error: {str(e)}"}
        )


@app.get("/api/call-statuses")
async def get_call_statuses(request: Request):
    """Get call status updates for the UI dashboard"""
    try:
        session = db_manager.get_session()
        try:
            from database.schemas import CallStatusUpdate, CallSession, Customer
            
            # Get all call status updates with related data
            status_updates = session.query(CallStatusUpdate).join(
                CallSession, CallStatusUpdate.call_session_id == CallSession.id
            ).join(
                Customer, CallSession.customer_id == Customer.id
            ).order_by(CallStatusUpdate.timestamp.desc()).limit(100).all()
            
            # Format response
            statuses = []
            for update in status_updates:
                statuses.append({
                    "id": str(update.id),
                    "call_sid": update.call_session.call_sid,
                    "customer_name": update.call_session.customer.full_name,
                    "customer_phone": update.call_session.customer.primary_phone,
                    "status": update.status,
                    "message": update.message,
                    "timestamp": format_ist_datetime(update.timestamp),
                    "extra_data": update.extra_data
                })
            
            return JSONResponse(
                status_code=200,
                content={"success": True, "statuses": statuses}
            )
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [API] Error fetching call statuses: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Internal server error: {str(e)}"}
        )


@app.get("/api/call-statuses/{call_sid}")
async def get_call_status_by_sid(call_sid: str):
    """Get all status updates for a specific call"""
    try:
        session = db_manager.get_session()
        try:
            from database.schemas import CallStatusUpdate, CallSession, Customer
            
            # Get call session
            call_session = get_call_session_by_sid(session, call_sid)
            if not call_session:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "error": "Call session not found"}
                )
            
            # Get all status updates for this call
            status_updates = session.query(CallStatusUpdate).filter(
                CallStatusUpdate.call_session_id == call_session.id
            ).order_by(CallStatusUpdate.timestamp.asc()).all()
            
            # Format response
            statuses = []
            for update in status_updates:
                statuses.append({
                    "id": str(update.id),
                    "status": update.status,
                    "message": update.message,
                    "timestamp": format_ist_datetime(update.timestamp),
                    "extra_data": update.extra_data
                })
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True, 
                    "call_sid": call_sid,
                    "customer_name": call_session.customer.full_name if call_session.customer else None,
                    "customer_phone": call_session.customer.primary_phone if call_session.customer else None,
                    "statuses": statuses
                }
            )
            
        finally:
            session.close()
            
    except Exception as e:
        print(f"❌ [API] Error fetching call status: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Internal server error: {str(e)}"}
        )


# This is a catch-all for the old websocket endpoint, redirecting or handling as needed.
@app.websocket("/stream")
async def old_websocket_endpoint(websocket: WebSocket):
    """
    Handles the old /stream endpoint.
    For backward compatibility, we'll redirect this to the new voicebot endpoint.
    """
    await websocket.accept()
    print("[Compatibility] Old /stream endpoint connected. Using voicebot logic...")
    
    # Initialize variables - we'll get the real CallSid from the start message
    query_params = dict(websocket.query_params)
    temp_call_id = query_params.get('temp_call_id')
    call_sid = query_params.get('call_sid')
    phone = query_params.get('phone')
    
    print(f"[Compatibility] Initial query params: temp_call_id={temp_call_id}, call_sid={call_sid}, phone={phone}")
    
    # State variable for the conversation stage
    conversation_stage = "WAITING_FOR_START" # Wait for the start message to get CallSid
    call_detected_lang = "en-IN" # Default language, will be updated after first user response
    audio_buffer = bytearray()
    last_transcription_time = time.time()
    interaction_complete = False # Flag to stop processing media after the main flow ends
    customer_info = None # Will be set when we get customer data
    initial_greeting_played = False # Track if initial greeting was played
    agent_question_repeat_count = 0 # Track how many times agent question was repeated
    emi_delivery_in_progress = False # Flag to prevent premature WebSocket closure during EMI delivery
    session_id = None # Will be set from the start message
    
    # Call timeout mechanism
    call_start_time = time.time()
    max_call_duration = 600  # 10 minutes maximum call duration
    
    try:
        while True:
            # Check for call timeout
            if time.time() - call_start_time > max_call_duration:
                logger.websocket.warning(f"⏰ Call timeout reached ({max_call_duration}s) - ending call gracefully")
                logger.log_call_event("CALL_TIMEOUT", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown')
                if customer_info and not interaction_complete:
                    # Play a quick timeout message
                    try:
                        timeout_msg = GOODBYE_TEMPLATE.get(call_detected_lang, GOODBYE_TEMPLATE["en-IN"])
                        audio_bytes = await sarvam_handler.synthesize_tts(timeout_msg, call_detected_lang)
                        await stream_audio_to_websocket(websocket, audio_bytes)
                        await asyncio.sleep(2)  # Wait for message to play
                    except Exception as e:
                        logger.tts.error(f"❌ Error playing timeout message: {e}")
                interaction_complete = True
                break
            data = await websocket.receive_text()
            msg = json.loads(data)
            event_type = msg.get('event', 'unknown')
            
            # Log WebSocket message using the new logging system
            logger.websocket.info(f"📨 Received message: {event_type}")
            logger.log_websocket_message(event_type, msg, call_sid=call_sid, session_id=session_id)
            
            # Debug: Log complete message for troubleshooting
            logger.websocket.debug(f"🔍 FULL MESSAGE DEBUG: {json.dumps(msg, indent=2)}")

            if msg.get("event") == "start":
                logger.websocket.info("🔁 Got start event - extracting CallSid and customer data")
                logger.log_call_event("START_MESSAGE_RECEIVED", call_sid or "unknown")
                
                # Debug: Log the full start message to see what Exotel is actually sending
                logger.websocket.debug(f"🔍 FULL START MESSAGE DEBUG: {json.dumps(msg, indent=2)}")
                
                # Extract CallSid from the start message - this is how Exotel sends it
                call_sid = None
                # CRITICAL: Check the nested start structure first - this is where Exotel actually sends it
                if 'start' in msg and 'call_sid' in msg['start']:
                    call_sid = msg['start']['call_sid']  # CRITICAL: This is where Exotel sends it!
                    logger.websocket.info(f"🎯 FOUND CallSid in start.call_sid: {call_sid}")
                elif 'start' in msg and 'callSid' in msg['start']:
                    call_sid = msg['start']['callSid']
                    logger.websocket.info(f"🎯 FOUND CallSid in start.callSid: {call_sid}")
                elif 'callSid' in msg:
                    call_sid = msg['callSid']
                elif 'CallSid' in msg:
                    call_sid = msg['CallSid']
                elif 'call_sid' in msg:
                    call_sid = msg['call_sid']
                elif 'streamSid' in msg:
                    call_sid = msg['streamSid']
                elif 'stream' in msg and 'callSid' in msg['stream']:
                    call_sid = msg['stream']['callSid']
                
                # Debug: Check all possible locations for CallSid
                logger.websocket.debug("🔍 Checking for CallSid in message fields:")
                logger.websocket.debug(f"🔍 msg.get('callSid'): {msg.get('callSid')}")
                logger.websocket.debug(f"🔍 msg.get('CallSid'): {msg.get('CallSid')}")
                logger.websocket.debug(f"🔍 msg.get('call_sid'): {msg.get('call_sid')}")
                logger.websocket.debug(f"🔍 msg.get('streamSid'): {msg.get('streamSid')}")
                logger.websocket.debug(f"🔍 msg.get('stream'): {msg.get('stream')}")
                logger.websocket.debug(f"🔍 msg.get('start'): {msg.get('start')}")
                logger.websocket.debug(f"🔍 All msg keys: {list(msg.keys())}")
                
                logger.websocket.info(f"✅ Extracted CallSid from start message: {call_sid}")
                
                # Use CallSid as session_id
                session_id = call_sid or generate_websocket_session_id()
                
                logger.websocket.info(f"Using session_id: {session_id}")
                
                # Now that we have the CallSid, try to get customer info from multiple sources
                if not customer_info:
                    # 1. Try to get from Redis using CallSid
                    if call_sid:
                        logger.database.info(f"Looking up customer data by CallSid: {call_sid}")
                        redis_data = redis_manager.get_call_session(call_sid)
                        if redis_data:
                            customer_info = {
                                'name': redis_data.get('name'),
                                'loan_id': redis_data.get('loan_id'),
                                'amount': redis_data.get('amount'),
                                'due_date': redis_data.get('due_date'),
                                'lang': redis_data.get('language_code', 'en-IN'),
                                'phone': redis_data.get('phone_number', ''),
                                'state': redis_data.get('state', '')
                            }
                            logger.database.info(f"✅ Found customer data in Redis: {customer_info['name']}")
                            logger.log_call_event("CUSTOMER_DATA_FOUND_REDIS", call_sid, customer_info['name'], customer_info)
                    
                    # 2. Try to get customer data from database by CallSid
                    if not customer_info and call_sid:
                        logger.database.info(f"Looking up call session in database by CallSid: {call_sid}")
                        try:
                            session_db = db_manager.get_session()
                            call_session = get_call_session_by_sid(session_db, call_sid)
                            if call_session and call_session.customer_id:
                                # Get customer from database with loans relationship
                                customer = session_db.query(Customer).options(joinedload(Customer.loans)).filter(Customer.id == call_session.customer_id).first()
                                if customer:
                                    # Get the first loan for this customer
                                    loan = customer.loans[0] if customer.loans else None
                                    customer_info = {
                                        'name': customer.full_name,
                                        'loan_id': loan.loan_id if loan else 'N/A',
                                        'amount': float(loan.outstanding_amount) if loan and loan.outstanding_amount else 0,
                                        'due_date': loan.next_due_date.isoformat() if loan and loan.next_due_date else None,
                                        'lang': 'en-IN',  # Default language
                                        'phone': customer.primary_phone,
                                        'state': customer.state or ''
                                    }
                                    logger.database.info(f"✅ Found customer in database: {customer_info['name']}")
                                    logger.log_call_event("CUSTOMER_DATA_FOUND_DATABASE", call_sid, customer_info['name'], customer_info)
                            session_db.close()
                        except Exception as e:
                            logger.database.error(f"❌ Error looking up customer in database: {e}")
                
                # 3. If no customer found, this is an error
                if not customer_info:
                    logger.database.error("❌ No customer data found - cannot proceed without real customer information")
                    logger.log_call_event("CUSTOMER_DATA_NOT_FOUND", call_sid)
                    await websocket.send_text(json.dumps({
                        "event": "error",
                        "message": "Customer data not found. Please ensure customer information is uploaded and call is triggered properly."
                    }))
                    return
                
                # 4. Validate customer data has required fields
                required_fields = ['name', 'loan_id', 'amount', 'due_date']
                missing_fields = [field for field in required_fields if not customer_info.get(field)]
                if missing_fields:
                    logger.database.error(f"❌ Customer data missing required fields: {missing_fields}")
                    logger.log_call_event("CUSTOMER_DATA_INCOMPLETE", call_sid, customer_info['name'] if customer_info else 'Unknown', {"missing_fields": missing_fields})
                    await websocket.send_text(json.dumps({
                        "event": "error",
                        "message": f"Customer data incomplete. Missing fields: {', '.join(missing_fields)}"
                    }))
                    return
                
                print(f"[Compatibility] ✅ Customer data validated: {customer_info['name']} - Loan: {customer_info['loan_id']}, Amount: ₹{customer_info['amount']}")
                
                # Initialize language variables for enhanced language detection
                csv_language = customer_info.get('lang', 'en-IN')
                state_language = get_initial_language_from_state(customer_info.get('state', ''))
                initial_greeting_language = csv_language if csv_language and csv_language != 'en-IN' else state_language
                call_detected_lang = initial_greeting_language
                
                logger.websocket.info(f"🌐 Language Configuration:")
                logger.websocket.info(f"   📄 CSV Language: {csv_language}")
                logger.websocket.info(f"   📍 State Language: {state_language}")
                logger.websocket.info(f"   🎯 Initial Greeting Language: {initial_greeting_language}")
                
                # Play initial greeting immediately when WebSocket starts
                logger.tts.info(f"1. Playing initial greeting for {customer_info['name']} in {initial_greeting_language}")
                logger.log_call_event("INITIAL_GREETING_START", call_sid, customer_info['name'], {"language": initial_greeting_language})
                try:
                    await greeting_template_play(websocket, customer_info, lang=initial_greeting_language)
                    logger.tts.info(f"✅ Initial greeting played successfully in {initial_greeting_language}")
                    logger.log_call_event("INITIAL_GREETING_SUCCESS", call_sid, customer_info['name'], {"language": initial_greeting_language})
                    initial_greeting_played = True
                    conversation_stage = "WAITING_FOR_LANG_DETECT"
                except Exception as e:
                    logger.tts.error(f"❌ Error playing initial greeting: {e}")
                    logger.log_call_event("INITIAL_GREETING_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                    # Try fallback simple greeting
                    try:
                        simple_greeting = f"Hello, this is South India Finvest Bank calling. Am I speaking with {customer_info['name']}?"
                        audio_bytes = await sarvam_handler.synthesize_tts(simple_greeting, "en-IN")
                        await stream_audio_to_websocket(websocket, audio_bytes)
                        logger.tts.info("✅ Fallback greeting sent successfully")
                        logger.log_call_event("FALLBACK_GREETING_SUCCESS", call_sid, customer_info['name'])
                        initial_greeting_played = True
                        conversation_stage = "WAITING_FOR_LANG_DETECT"
                    except Exception as fallback_e:
                        logger.tts.error(f"❌ Error sending fallback greeting: {fallback_e}")
                        logger.log_call_event("FALLBACK_GREETING_ERROR", call_sid, customer_info['name'], {"error": str(fallback_e)})
                continue

            if msg.get("event") == "stop":
                logger.websocket.info("🛑 Received stop event from Twilio/Exotel")
                # Don't break the loop immediately - only if conversation is complete
                if interaction_complete:
                    logger.websocket.info("✅ Conversation already complete, processing stop event")
                    break
                else:
                    logger.websocket.info("⚠️ Stop event received but conversation not complete - ignoring for now")
                    # Log the stop event but continue processing
                    logger.log_call_event("STOP_EVENT_IGNORED", call_sid, customer_info['name'] if customer_info else 'Unknown', 
                                        {"reason": "conversation_not_complete", "stage": conversation_stage})
                    continue

            if msg.get("event") == "media":
                payload_b64 = msg["media"]["payload"]
                raw_audio = base64.b64decode(payload_b64)

                if interaction_complete:
                    continue

                if raw_audio and any(b != 0 for b in raw_audio):
                    audio_buffer.extend(raw_audio)
                
                now = time.time()

                if now - last_transcription_time >= BUFFER_DURATION_SECONDS:
                    if len(audio_buffer) == 0:
                        if conversation_stage == "WAITING_FOR_LANG_DETECT":
                            logger.websocket.info("No audio received during language detection stage. Playing 'didn't hear' prompt.")
                            logger.log_call_event("NO_AUDIO_LANG_DETECT", call_sid, customer_info['name'])
                            await play_did_not_hear_response(websocket, call_detected_lang)
                            last_transcription_time = time.time()
                        elif conversation_stage == "WAITING_AGENT_RESPONSE":
                            agent_question_repeat_count += 1
                            if agent_question_repeat_count <= 2:
                                logger.websocket.info(f"No audio received during agent question stage. Repeating question (attempt {agent_question_repeat_count}/2).")
                                logger.log_call_event("AGENT_QUESTION_REPEAT", call_sid, customer_info['name'], {"attempt": agent_question_repeat_count})
                                await play_agent_connect_question(websocket, call_detected_lang)
                                last_transcription_time = time.time()
                            else:
                                logger.websocket.info("Too many no-audio responses. Assuming user wants agent transfer.")
                                logger.log_call_event("AUTO_AGENT_TRANSFER_NO_AUDIO", call_sid, customer_info['name'])
                                customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
                                await play_transfer_to_agent(websocket, customer_number=customer_number) 
                                conversation_stage = "TRANSFERRING_TO_AGENT"
                                interaction_complete = True
                                await asyncio.sleep(2)
                                break
                        audio_buffer.clear()
                        last_transcription_time = now
                        continue

                    try:
                        transcript = await sarvam_handler.transcribe_from_payload(audio_buffer)
                        if isinstance(transcript, tuple):
                            transcript_text, detected_language = transcript
                            if detected_language and detected_language != "en-IN":
                                call_detected_lang = detected_language
                                logger.websocket.info(f"🌐 Language updated from transcription: {call_detected_lang}")
                            transcript = transcript_text
                        elif isinstance(transcript, str):
                            pass
                        else:
                            transcript = ""
                        
                        logger.websocket.info(f"📝 Transcript: {transcript}")
                        logger.log_call_event("TRANSCRIPT_RECEIVED", call_sid, customer_info['name'], {"transcript": transcript, "stage": conversation_stage})

                        if transcript:
                            if conversation_stage == "WAITING_FOR_LANG_DETECT":
                                # Detect user's preferred language from their response
                                user_detected_lang = detect_language(transcript)
                                logger.websocket.info(f"🎯 User Response Language Detection:")
                                logger.websocket.info(f"   📍 State-mapped language: {initial_greeting_language}")
                                logger.websocket.info(f"   🗣️  User detected language: {user_detected_lang}")
                                logger.websocket.info(f"   📄 CSV language: {csv_language}")
                                logger.log_call_event("LANGUAGE_DETECTED", call_sid, customer_info['name'], {
                                    "detected_lang": user_detected_lang, 
                                    "state_lang": initial_greeting_language,
                                    "csv_lang": csv_language,
                                    "transcript": transcript
                                })
                                
                                # Enhanced Language Switching Logic
                                if user_detected_lang != initial_greeting_language:
                                    logger.websocket.info(f"🔄 Language Mismatch Detected!")
                                    logger.websocket.info(f"   Initial greeting was in: {initial_greeting_language}")
                                    logger.websocket.info(f"   User responded in: {user_detected_lang}")
                                    logger.websocket.info(f"   🔄 Switching entire conversation to: {user_detected_lang}")
                                    logger.log_call_event("LANGUAGE_SWITCH_DETECTED", call_sid, customer_info['name'], {
                                        "from_lang": initial_greeting_language,
                                        "to_lang": user_detected_lang,
                                        "reason": "user_preference"
                                    })
                                    
                                    # Replay greeting in user's preferred language
                                    try:
                                        logger.websocket.info(f"🔁 Replaying greeting in user's language: {user_detected_lang}")
                                        await greeting_template_play(websocket, customer_info, lang=user_detected_lang)
                                        logger.websocket.info(f"✅ Successfully replayed greeting in {user_detected_lang}")
                                        logger.log_call_event("GREETING_REPLAYED_NEW_LANG", call_sid, customer_info['name'], {"new_lang": user_detected_lang})
                                        
                                        # Update the conversation language to user's preference
                                        call_detected_lang = user_detected_lang
                                        
                                        # Give user a moment to acknowledge the language switch
                                        await asyncio.sleep(1)
                                        
                                    except Exception as e:
                                        logger.websocket.error(f"❌ Error replaying greeting in {user_detected_lang}: {e}")
                                        logger.log_call_event("GREETING_REPLAY_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                                        # Fallback to user's detected language anyway
                                        call_detected_lang = user_detected_lang
                                        
                                else:
                                    logger.websocket.info(f"✅ Language Consistency Confirmed!")
                                    logger.websocket.info(f"   User responded in same language as greeting: {user_detected_lang}")
                                    logger.log_call_event("LANGUAGE_CONSISTENT", call_sid, customer_info['name'], {"language": user_detected_lang})
                                    call_detected_lang = user_detected_lang
                                
                                # Final language confirmation
                                logger.websocket.info(f"🎉 Final Conversation Language: {call_detected_lang}")
                                logger.log_call_event("FINAL_LANGUAGE_SET", call_sid, customer_info['name'], {"final_lang": call_detected_lang})
                                
                                try:
                                    await play_emi_details_part1(websocket, customer_info or {}, call_detected_lang)
                                    await play_emi_details_part2(websocket, customer_info or {}, call_detected_lang)
                                    await play_agent_connect_question(websocket, call_detected_lang)
                                    conversation_stage = "WAITING_AGENT_RESPONSE"
                                    logger.tts.info(f"✅ EMI details and agent question sent successfully in {call_detected_lang}")
                                    logger.log_call_event("EMI_DETAILS_SENT", call_sid, customer_info['name'], {"language": call_detected_lang})
                                except Exception as e:
                                    logger.tts.error(f"❌ Error playing EMI details: {e}")
                                    logger.log_call_event("EMI_DETAILS_ERROR", call_sid, customer_info['name'], {"error": str(e)})
                            
                            elif conversation_stage == "WAITING_AGENT_RESPONSE":
                                try:
                                    intent = detect_intent_with_claude(transcript, call_detected_lang)
                                    logger.websocket.info(f"Claude detected intent: {intent}")
                                    logger.log_call_event("INTENT_DETECTED_CLAUDE", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript})
                                except Exception as e:
                                    logger.websocket.error(f"❌ Error in Claude intent detection: {e}")
                                    intent = detect_intent_fur(transcript, call_detected_lang)
                                    logger.websocket.info(f"Fallback intent detection: {intent}")
                                    logger.log_call_event("INTENT_DETECTED_FALLBACK", call_sid, customer_info['name'], {"intent": intent, "transcript": transcript})

                                if intent == "affirmative" or intent == "agent_transfer":
                                    if conversation_stage != "TRANSFERRING_TO_AGENT":
                                        logger.websocket.info("User affirmed agent transfer. Initiating transfer.")
                                        logger.log_call_event("AGENT_TRANSFER_INITIATED", call_sid, customer_info['name'], {"intent": intent})
                                        customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
                                        await play_transfer_to_agent(websocket, customer_number=customer_number) 
                                        conversation_stage = "TRANSFERRING_TO_AGENT"
                                        interaction_complete = True
                                        await asyncio.sleep(2)
                                        break
                                    else:
                                        logger.websocket.warning("⚠️ Agent transfer already in progress, ignoring duplicate request")
                                elif intent == "negative":
                                    if conversation_stage != "GOODBYE_DECLINE":
                                        logger.websocket.info("User declined agent transfer. Saying goodbye.")
                                        logger.log_call_event("AGENT_TRANSFER_DECLINED", call_sid, customer_info['name'])
                                        await play_goodbye_after_decline(websocket, call_detected_lang)
                                        conversation_stage = "GOODBYE_DECLINE"
                                        interaction_complete = True
                                        await asyncio.sleep(3)
                                        break
                                    else:
                                        logger.websocket.warning("⚠️ Goodbye already sent, ignoring duplicate request")
                                else:
                                    agent_question_repeat_count += 1
                                    if agent_question_repeat_count <= 2:
                                        logger.websocket.info(f"Unclear response to agent connect. Repeating question (attempt {agent_question_repeat_count}/2).")
                                        logger.log_call_event("AGENT_QUESTION_UNCLEAR_REPEAT", call_sid, customer_info['name'], {"attempt": agent_question_repeat_count})
                                        await play_agent_connect_question(websocket, call_detected_lang)
                                        last_transcription_time = time.time()
                                    else:
                                        logger.websocket.info("Too many unclear responses. Assuming user wants agent transfer.")
                                        logger.log_call_event("AUTO_AGENT_TRANSFER_UNCLEAR", call_sid, customer_info['name'])
                                        customer_number = customer_info.get('phone', '08438019383') if customer_info else "08438019383"
                                        await play_transfer_to_agent(websocket, customer_number=customer_number) 
                                        conversation_stage = "TRANSFERRING_TO_AGENT"
                                        interaction_complete = True
                                        await asyncio.sleep(2)
                                        break
                    except Exception as e:
                        logger.websocket.error(f"❌ Error processing transcript: {e}")
                        logger.log_call_event("TRANSCRIPT_PROCESSING_ERROR", call_sid, customer_info['name'] if customer_info else 'Unknown', {"error": str(e)})

                    audio_buffer.clear()
                    last_transcription_time = now

    except Exception as e:
        logger.error.error(f"WebSocket compatibility error: {e}")
        logger.log_call_event("WEBSOCKET_COMPATIBILITY_ERROR", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown', {"error": str(e)})
    finally:
        # Ensure the websocket is closed gracefully only after conversation is complete
        try:
            if not interaction_complete:
                # If we're exiting due to an error before conversation completion, wait a bit
                await asyncio.sleep(1)
            
            if websocket.client_state.name not in ['DISCONNECTED']:
                await websocket.close()
                logger.websocket.info("🔒 WebSocket connection closed gracefully")
            else:
                logger.websocket.info("🔒 WebSocket already disconnected")
        except Exception as close_error:
            logger.error.error(f"Error closing WebSocket: {close_error}")
        logger.log_call_event("WEBSOCKET_CLOSED_GRACEFUL", call_sid or 'unknown', customer_info['name'] if customer_info else 'Unknown')


    # --- Add this helper ---
async def broadcast_status_update(call_sid: str, status: str, customer_id: str = None):
    """
    Broadcasts a call status update to all connected WebSocket clients.
    """
    message = {
        "event": "call_status_update",
        "call_sid": call_sid,
        "status": status,
        "customer_id": customer_id,
        "message": f"Call status updated to {status}"
    }

    disconnected = []
    for ws in active_connections:
        try:
            await ws.send_text(json.dumps(message))
        except Exception as e:
            logger.error.error(f"❌ Failed to send WS message: {e}")
            disconnected.append(ws)

    # Remove dead connections
    for ws in disconnected:
        try:
            active_connections.remove(ws)
        except ValueError:
            pass

    logger.websocket.info(f"📢 Broadcasted status update: {message}")





if __name__ == "__main__":
    logger.app.info("Starting server directly from main.py")
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )