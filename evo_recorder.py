import asyncio
import ssl
import requests
import urllib3
import time
from datetime import datetime
from websockets.client import connect as ws_connect

# --- CONFIGURATION ---
HOST = "10.37.2.86"
USERNAME = "evo"  
PASSWORD = "root" 

# URL MAPPINGS
LOGIN_URL = f"http://{HOST}/login"
WS_URI = f"wss://{HOST}/"
SUBPROTOCOL = "ws_ui"

# FORM FIELDS
FIELD_USER = "uname"
FIELD_PASS = "passwd"

# Suppress warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

async def record_raw_stream(auth_cookie):
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    print(f"📡 Connecting to Radar Stream at {WS_URI}...")
    
    headers = {
        "Cookie": auth_cookie,
        "User-Agent": "Mozilla/5.0",
        "Origin": f"http://{HOST}"
    }

    try:
        async with ws_connect(
            WS_URI, 
            subprotocols=[SUBPROTOCOL], 
            ssl=ssl_context, 
            extra_headers=headers
        ) as websocket:
            
            print("🔹 Connected! Sending Configuration Request...")
            await websocket.send("GetCfg")
            
            # Create a filename with a timestamp
            filename = f"{HOST.replace('.', '_')}_EVO_{int(time.time())}.txt"
            
            with open(filename, 'w') as f:
                print(f"🔴 Recording RAW stream to: {filename}")
                print("Press Ctrl+C to stop recording.")
                
                frame_count = 0
                
                async for message in websocket:
                    # 1. Generate Timestamp (HH:MM:SS.mmm)
                    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    
                    # 2. Write to file (Timestamp line, then Message line)
                    f.write(f"{ts}\n{message}\n")
                    f.flush() # Important: ensures data is saved if script crashes
                    
                    # 3. Console Feedback
                    frame_count += 1
                    msg_type = message.split(';')[0]
                    print(f"\r📥 Frames Captured: {frame_count} [Last: {msg_type}]", end="")

    except asyncio.CancelledError:
        print("\n⏹️ Recording Stopped.")
    except Exception as e:
        print(f"\n❌ Connection Error: {e}")

def get_auth_cookie():
    print(f"🔐 Authenticating via POST to {LOGIN_URL}...")
    session = requests.Session()
    payload = {FIELD_USER: USERNAME, FIELD_PASS: PASSWORD}
    
    try:
        response = session.post(LOGIN_URL, data=payload, verify=False, timeout=10)
        if response.status_code != 200 or not session.cookies:
            print(f"❌ Login Failed (Status: {response.status_code})")
            return None
            
        print("✅ Login Successful.")
        return "; ".join([f"{c.name}={c.value}" for c in session.cookies])
    except Exception as e:
        print(f"❌ Auth Error: {e}")
        return None

if __name__ == "__main__":
    cookie = get_auth_cookie()
    if cookie:
        try:
            asyncio.run(record_raw_stream(cookie))
        except KeyboardInterrupt:
            print("\nUser stopped recording.")