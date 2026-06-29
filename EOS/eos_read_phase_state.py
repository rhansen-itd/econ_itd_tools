import asyncio
import websockets
import ssl
from datetime import datetime

# CONFIGURATION
# ------------------------------------------------------------------
IP_ADDRESS = "10.37.23.200" #"10.37.2.66" #23.200 Banks
PORT = "8443" #8443 is the secure websocket port, but 8081 is the non-secure one that works without SSL context
WS_URL = f"wss://{IP_ADDRESS}:{PORT}/"
SUB_PROTOCOL = "front-panel-protocol"
# ------------------------------------------------------------------

def get_active_phases(hex_word):
    try:
        val = int(hex_word, 16)
        return [i + 1 for i in range(16) if (val >> i) & 1]
    except ValueError:
        return []

async def monitor_controller():
    # Create an SSL context that ignores certificate errors
    # (Traffic controllers almost always use self-signed certs)
    ssl_context = ssl._create_unverified_context()

    print(f"Connecting to {WS_URL}...")
    
    try:
        async with websockets.connect(
            WS_URL, 
            subprotocols=[SUB_PROTOCOL],
            ssl=ssl_context  # This is the key for port 8443
        ) as ws:
            print("Connected! Monitoring phases...\n")
            
            last_state = {"Red": [], "Yellow": [], "Green": []}
            heartbeat_count = 0

            async for message in ws:
                if len(message) < 100 or "STATUS" not in message:
                    continue

                current_state = {
                    "Green":  get_active_phases(message[17:21]), #add 40 for channels instead of phases
                    "Yellow": get_active_phases(message[21:25]),
                    "Red":    get_active_phases(message[25:29])
                }

                if current_state != last_state:
                    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    print(f"[{timestamp}] CHANGE:")
                    for color, phases in current_state.items():
                        if current_state[color] != last_state[color]:
                            print(f"  {color}: {phases if phases else 'None'}")
                    print("-" * 20)
                    last_state = current_state

                heartbeat_count += 1
                if heartbeat_count >= 50:
                    await ws.send("get")
                    heartbeat_count = 0

    except Exception as e:
        print(f"FAILED TO CONNECT: {e}")
        print("\nTroubleshooting Tips:")
        print(f"1. Can you ping {IP_ADDRESS} from this computer?")
        print(f"2. Open your browser to https://{IP_ADDRESS}:{PORT}/")
        print("3. Ensure no other script is already holding the connection open.")

if __name__ == "__main__":
    asyncio.run(monitor_controller())