import asyncio
import ssl
import requests
import urllib3
import time
import sys
import ctypes
from datetime import datetime
from websockets.client import connect as ws_connect

# --- WINDOWS SLEEP PREVENTION CONFIG ---
# Constants from winnt.h
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

def prevent_sleep():
    """Enable system sleep prevention (Windows only)."""
    if sys.platform.startswith('win'):
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
            )
            print("⚡ System Sleep Prevented: ON")
        except Exception as e:
            print(f"⚠️ Could not set sleep prevention: {e}")

def allow_sleep():
    """Allow system sleep again (Windows only)."""
    if sys.platform.startswith('win'):
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            print("💤 System Sleep Restored: ON")
        except Exception as e:
            print(f"⚠️ Could not reset sleep settings: {e}")

# --- RADAR CONFIGURATION ---
HOSTS_CONFIG = {
    "10.37.23.201": ("evo", "root"),
    "10.37.2.84": ("evo", "root"),
    "10.37.2.85": ("evo", "root"),
    "10.37.2.86": ("evo", "root"),
    "10.37.2.87": ("evo", "root")
}

SUBPROTOCOL = "ws_ui"
FIELD_USER = "uname"
FIELD_PASS = "passwd"

# Suppress warnings for insecure requests (self-signed certs)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_auth_cookie(host, username, password):
    """Performs HTTP POST login and returns the formatted cookie string."""
    login_url = f"http://{host}/login"
    print(f"🔐 [{host}] Authenticating...")
    
    session = requests.Session()
    payload = {FIELD_USER: username, FIELD_PASS: password}
    
    try:
        response = session.post(login_url, data=payload, verify=False, timeout=10)
        if response.status_code != 200 or not session.cookies:
            print(f"❌ [{host}] Login Failed (Status: {response.status_code})")
            return None
            
        print(f"✅ [{host}] Login Successful.")
        return "; ".join([f"{c.name}={c.value}" for c in session.cookies])
    except Exception as e:
        print(f"❌ [{host}] Auth Error: {e}")
        return None

async def record_raw_stream(host, auth_cookie):
    """Maintains the WebSocket connection and file writing for a specific host."""
    ws_uri = f"wss://{host}/"
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    headers = {
        "Cookie": auth_cookie,
        "User-Agent": "Mozilla/5.0",
        "Origin": f"http://{host}"
    }

    try:
        async with ws_connect(
            ws_uri, 
            subprotocols=[SUBPROTOCOL], 
            ssl=ssl_context, 
            extra_headers=headers,
            ping_interval=20, # Keep connection alive during silence
            ping_timeout=20
        ) as websocket:
            
            print(f"📡 [{host}] Connected! Requesting Cfg...")
            await websocket.send("GetCfg")
            
            # Filename formatting
            filename = f"{host.replace('.', '_')}_EVO_{int(time.time())}.txt"
            
            with open(filename, 'w') as f:
                print(f"🔴 [{host}] Recording to: {filename}")
                
                async for message in websocket:
                    # High-precision timestamp
                    ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    
                    f.write(f"{ts}\n{message}\n")
                    f.flush() 
                    
                    # Optional: Uncomment if you want console feedback per X frames
                    # frame_count += 1
                    # if frame_count % 100 == 0:
                    #     print(f"📦 [{host}] Captured {frame_count} frames...")

    except asyncio.CancelledError:
        print(f"\n⏹️ [{host}] Task cancelled.")
    except Exception as e:
        print(f"\n❌ [{host}] Connection Error: {e}")

async def main():
    """Orchestrates the login and task creation for all hosts."""
    tasks = []

    print("--- Starting Radar Recorder ---")

    for host, credentials in HOSTS_CONFIG.items():
        username, password = credentials
        cookie = get_auth_cookie(host, username, password)
        
        if cookie:
            # Create a concurrent task for this specific host
            tasks.append(record_raw_stream(host, cookie))
        else:
            print(f"⚠️ Skipping {host} due to authentication failure.")

    if tasks:
        print(f"🚀 Launching {len(tasks)} concurrent recording streams...")
        print("⌨️  Press Ctrl+C to stop all recordings.")
        # Run all recordings concurrently
        await asyncio.gather(*tasks)
    else:
        print("No active streams to maintain. Exiting.")

if __name__ == "__main__":
    # 1. Prevent Sleep
    prevent_sleep()
    
    try:
        # 2. Run Main Async Loop
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Global stop requested by user.")
    finally:
        # 3. Restore Sleep Settings (always runs, even on crash)
        allow_sleep()