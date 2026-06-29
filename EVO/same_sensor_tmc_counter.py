"""
TURNING MOVEMENT COUNTER
=========================

Counts intersection turning movements from raw radar tracks.
No stitching, blending, or fusion - just raw track gate crossings.

Movement naming convention:
  Gate names expected format: {Direction}_{SensorID}  e.g. N_S0, S_S1, E_S0, W_S1

Movement classification:
  Entry gate → Exit gate → Movement name
  e.g. S → E = NBR (Northbound Right)
       S → W = NBL (Northbound Left)
       S → N = NBT (Northbound Through)
       etc.

Output:
  DataFrame with columns: [Timestamp, Movement, Sensor]
"""

import re
import io
import base64
import json
import pandas as pd
import numpy as np
from PIL import Image
from shapely.geometry import LineString

# ============================================================================
# CONFIGURATION
# ============================================================================

INT_DIR     = "../sites/86_US95&SH8/"
XML_FILE    = INT_DIR + "us95&sh8_iprj.txt"
DATA_FILE   = INT_DIR + "10_37_2_86_EVO_1770686257.txt"
GATES_FILE  = INT_DIR + "gates.json"
OUTPUT_FILE = INT_DIR + "movement_counts.csv"

MIN_TRACK_POINTS = 3

# ============================================================================
# MOVEMENT LOOKUP TABLE
# ============================================================================

MOVEMENT_MAP = {
    ('S', 'N'): 'NBT',
    ('S', 'E'): 'NBR',
    ('S', 'W'): 'NBL',
    ('N', 'S'): 'SBT',
    ('N', 'W'): 'SBR',
    ('N', 'E'): 'SBL',
    ('W', 'E'): 'EBT',
    ('W', 'N'): 'EBR',
    ('W', 'S'): 'EBL',
    ('E', 'W'): 'WBT',
    ('E', 'S'): 'WBR',
    ('E', 'N'): 'WBL',
}

# ============================================================================
# PARSING FUNCTIONS (copied from current fusion_improved.py)
# ============================================================================

def parse_xml_config(filepath):
    config = {'scale': 0.2, 'bg_off_x': 0, 'bg_off_y': 0, 's0_x': 0, 's0_y': 0}
    img_b64 = None
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        m_img = re.search(r'BackgroundImage="([^"]+)"', content)
        if m_img:
            img_b64 = "data:image/png;base64," + m_img.group(1)
            try:
                img_bytes = base64.b64decode(m_img.group(1))
                pil_img = Image.open(io.BytesIO(img_bytes))
                config['width'] = pil_img.width
                config['height'] = pil_img.height
            except: pass
        m_scale = re.search(r'MeterPerPixel="([^"]+)"', content)
        if m_scale: config['scale'] = float(m_scale.group(1))
        m_bgx = re.search(r'(?:BackgroundImage|Background_)PosX="([^"]+)"', content)
        if m_bgx: config['bg_off_x'] = float(m_bgx.group(1))
        m_bgy = re.search(r'(?:BackgroundImage|Background_)PosY="([^"]+)"', content)
        if m_bgy: config['bg_off_y'] = float(m_bgy.group(1))
        m_s0x = re.search(r'Radarsensor_0_Position_X="([^"]+)"', content)
        m_s0y = re.search(r'Radarsensor_0_Position_Y="([^"]+)"', content)
        if m_s0x and m_s0y:
            config['s0_x'] = (float(m_s0x.group(1)) - config['bg_off_x']) * config['scale']
            config['s0_y'] = (float(m_s0y.group(1)) - config['bg_off_y']) * config['scale']
    return config, img_b64


def load_gates(filepath, map_config):
    """
    Load gates from JSON file.
    Supports both naming conventions:
    - Old: S0_Gate, S1_Gate (sensor only)
    - New: N_S0, S_S1, E_S0, W_S1 (direction_sensor for turning movements)
    """
    with open(filepath, 'r') as f:
        gates_raw = json.load(f)

    gates = []
    print("\n--- Loading Gates ---")
    print(f"   S0 sensor position in map coords: ({map_config['s0_x']:.1f}, {map_config['s0_y']:.1f})")

    for idx, g in enumerate(gates_raw):
        name = g['name']

        if '_S' in name:
            parts = name.split('_S')
            direction = parts[0] if len(parts) > 0 else ''
            sensor = int(parts[1]) if len(parts) > 1 else 0
        elif name.startswith('S') and '_' in name:
            sensor = int(name[1])
            direction = ''
        else:
            sensor = 0
            direction = ''

        p1 = (g['p1'][0], g['p1'][1])
        p2 = (g['p2'][0], g['p2'][1])

        gates.append({
            'name':      name,
            'sensor':    sensor,
            'direction': direction,
            'line':      LineString([p1, p2]),
            'p1':        p1,
            'p2':        p2,
            'idx':       idx
        })

        print(f"   [{idx}] {name} (S{sensor}, dir={direction or 'N/A'}): "
              f"({p1[0]:.1f}, {p1[1]:.1f}) -> ({p2[0]:.1f}, {p2[1]:.1f})")

    return gates


def parse_and_align_data(filepath, map_config):
    data = []
    evo_s0 = {'x': None, 'y': None}

    print("--- Parsing Data File ---")

    with open(filepath, 'r') as f:
        for line in f:
            if line.startswith('C;'):
                parts = line.split(';')
                if len(parts) > 1:
                    vals = parts[1].split(',')
                    if len(vals) >= 3:
                        try:
                            evo_s0['x'] = float(vals[0])
                            evo_s0['y'] = float(vals[1])
                            print(f"   Found S0 position: ({evo_s0['x']:.2f}, {evo_s0['y']:.2f})")
                            break
                        except:
                            pass

    if evo_s0['x'] is None:
        print("   ⚠️ Warning: Could not find S0 position (C; line), using 0,0")
        evo_s0['x'] = 0
        evo_s0['y'] = 0

    trans_x = map_config['s0_x'] - evo_s0['x']
    trans_y = map_config['s0_y'] - evo_s0['y']
    print(f"   Translation: ({trans_x:.2f}, {trans_y:.2f})")

    with open(filepath, 'r') as f:
        lines = f.readlines()

    current_time = 0.0
    time_count = 0
    obj_count = 0

    for line in lines:
        line = line.strip()

        if ':' in line and '.' in line and len(line) < 20 and not line.startswith('F;'):
            try:
                time_parts = line.split(':')
                if len(time_parts) == 3:
                    hours   = float(time_parts[0])
                    minutes = float(time_parts[1])
                    seconds = float(time_parts[2])
                    current_time = hours * 3600 + minutes * 60 + seconds
                    time_count += 1
            except:
                pass
            continue

        if line.startswith('F;'):
            parts = line.split(';')
            if len(parts) < 3:
                continue

            for ent in parts[4:]:
                if not ent: continue
                p = ent.split(',')
                if len(p) < 4: continue

                try:
                    oid       = int(p[0])
                    veh_class = int(p[1])
                    x         = float(p[2]) + trans_x
                    y         = float(p[3]) + trans_y
                    sensor_id = oid % 10
                    if sensor_id > 3:
                        sensor_id = sensor_id % 4

                    data.append({
                        'Time':   current_time,
                        'ID':     oid,
                        'X':      x,
                        'Y':      y,
                        'Sensor': sensor_id,
                        'Class':  veh_class
                    })
                    obj_count += 1
                except:
                    pass

    print(f"   Parsed {time_count} timestamps, {obj_count} object detections")

    df = pd.DataFrame(data)

    if df.empty:
        print("   ⚠️ ERROR: No data parsed! Check file format.")
        return df

    print(f"   DataFrame shape: {df.shape}")
    print(f"   Time range: {df['Time'].min():.2f} - {df['Time'].max():.2f}")
    print(f"   Sensors found: {sorted(df['Sensor'].unique())}")

    return df




def get_gate_crossings(track_df, gates):
    """
    Find all gate crossings for a track using actual line segment intersection.
    Returns list of (time, gate_name, gate_direction, gate_sensor) in crossing order.
    """
    track_df = track_df.sort_values('Time').reset_index(drop=True)
    crossings = []
    gates_hit = set()

    for i in range(len(track_df) - 1):
        x1, y1 = track_df.iloc[i]['X'], track_df.iloc[i]['Y']
        x2, y2 = track_df.iloc[i+1]['X'], track_df.iloc[i+1]['Y']

        segment = LineString([(x1, y1), (x2, y2)])

        for gate_idx, gate in enumerate(gates):
            if gate_idx in gates_hit:
                continue

            if segment.intersects(gate['line']):
                crossings.append({
                    'time':      track_df.iloc[i]['Time'],
                    'gate_name': gate['name'],
                    'direction': gate.get('direction', ''),
                    'sensor':    gate['sensor'],
                    'gate_idx':  gate_idx
                })
                gates_hit.add(gate_idx)

    return crossings


def classify_movement(crossings):
    """
    Given an ordered list of gate crossings, return movement name or None.
    Uses only the first and last crossing to determine entry/exit direction.
    Only classifies if both crossings are from the same sensor.
    """
    if len(crossings) < 2:
        return None

    entry = crossings[0]
    exit_ = crossings[-1]

    entry_dir = entry['direction']
    exit_dir  = exit_['direction']

    if not entry_dir or not exit_dir:
        return None

    return MOVEMENT_MAP.get((entry_dir, exit_dir), None)


def count_movements(df, gates):
    """
    Iterate over all raw tracks per sensor and classify movements.
    Returns DataFrame: [Timestamp, Movement, Sensor]
    """
    print("\n--- Counting Movements ---")

    results = []

    for (sensor, obj_id), track_df in df.groupby(['Sensor', 'ID']):
        if len(track_df) < MIN_TRACK_POINTS:
            continue

        crossings = get_gate_crossings(track_df, gates)

        if len(crossings) < 2:
            continue

        movement = classify_movement(crossings)

        if movement is None:
            continue

        # Timestamp = time of exit gate crossing
        exit_time = crossings[-1]['time']

        results.append({
            'Timestamp': exit_time,
            'Movement':  movement,
            'Sensor':    sensor
        })

    result_df = pd.DataFrame(results)

    if not result_df.empty:
        result_df = result_df.sort_values('Timestamp').reset_index(drop=True)

    return result_df


def print_summary(result_df):
    """Print a summary table of movement counts by sensor."""
    if result_df.empty:
        print("   No movements classified.")
        return

    print(f"\n   Total movements classified: {len(result_df)}")
    print(f"\n   {'Movement':<10} {'Sensor':<8} {'Count':<8}")
    print(f"   {'-'*28}")

    summary = (result_df
               .groupby(['Movement', 'Sensor'])
               .size()
               .reset_index(name='Count')
               .sort_values(['Movement', 'Sensor']))

    for _, row in summary.iterrows():
        print(f"   {row['Movement']:<10} S{int(row['Sensor']):<7} {int(row['Count']):<8}")


def main():
    print("=" * 60)
    print("TURNING MOVEMENT COUNTER")
    print("=" * 60)

    # Load config, gates, and data
    config, _ = parse_xml_config(XML_FILE)
    gates     = load_gates(GATES_FILE, config)
    df        = parse_and_align_data(DATA_FILE, config)

    if df.empty:
        print("ERROR: No data loaded.")
        return

    # Count movements
    result_df = count_movements(df, gates)

    # Print summary
    print_summary(result_df)

    # Save to CSV
    result_df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n✓ Saved to {OUTPUT_FILE}")

    return result_df


if __name__ == "__main__":
    main()