import matplotlib.pyplot as plt
import json
import os
from evo_fusion_visualizer import parse_xml_config # Re-use your existing parser

# --- CONFIG ---
XML_FILE = "./sites/86_US95&SH8/us95&sh8_iprj.txt"
OUTPUT_FILE = "gates.json"

def create_gates():
    print("--- EVO Gate Designer ---")
    print("1. Loading Map...")
    cfg, img_b64 = parse_xml_config(XML_FILE)
    
    # Setup Plot
    fig, ax = plt.subplots(figsize=(12, 10))
    
    # Plot Image
    width_m = cfg['width'] * cfg['scale']
    height_m = cfg['height'] * cfg['scale']
    
    # Helper to decode base64 for matplotlib
    import base64
    import io
    from PIL import Image
    img_bytes = base64.b64decode(img_b64.split(',')[1])
    bg_img = Image.open(io.BytesIO(img_bytes))
    
    ax.imshow(bg_img, extent=[0, width_m, height_m, 0])
    ax.set_title("Click 2 points to define a Gate. Close window to finish.")
    ax.set_xlim(0, width_m)
    ax.set_ylim(height_m, 0)

    gates = []
    
    # Load existing if available
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'r') as f:
            gates = json.load(f)
            for g in gates:
                ax.plot([g['p1'][0], g['p2'][0]], [g['p1'][1], g['p2'][1]], 'r-', lw=2)
                ax.text(g['p1'][0], g['p1'][1], g['name'], color='yellow')
                print(f"Loaded existing gate: {g['name']}")

    print("\nINSTRUCTIONS:")
    print("  - Left Click two points to draw a line.")
    print("  - Check the console to name the gate.")
    print("  - Close the plot window to save and exit.\n")

    while True:
        try:
            # Get 2 clicks
            pts = plt.ginput(2, timeout=-1)
            if len(pts) < 2: break
            
            p1, p2 = pts
            
            # Draw temporary line
            line, = ax.plot([p1[0], p2[0]], [p1[1], p2[1]], 'cyan', lw=2)
            plt.draw()
            
            # Ask for name
            name = input(f"Gate Name for line {p1} -> {p2}? (Enter to skip): ")
            if not name:
                line.remove()
                plt.draw()
                continue
                
            # Store
            gate = {
                'name': name,
                'p1': p1,
                'p2': p2
            }
            gates.append(gate)
            
            # make permanent
            line.set_color('red')
            ax.text(p1[0], p1[1], name, color='yellow', fontsize=12, fontweight='bold')
            plt.draw()
            
        except:
            break

    # Save
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(gates, f, indent=2)
    print(f"\nSaved {len(gates)} gates to {OUTPUT_FILE}")

if __name__ == "__main__":
    create_gates()