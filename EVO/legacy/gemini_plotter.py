import pandas as pd
import numpy as np
import re
import base64
import io
import json
import os
import plotly.express as px
from scipy.interpolate import Rbf
from shapely.geometry import LineString, Point
from PIL import Image

# --- CONFIGURATION ---
XML_FILE = "us95&sh8_iprj.txt"
DATA_FILE = "EVO_raw_data_1770177118.txt"
GATES_FILE = "gates.json"

# Tuning
FINE_MATCH_DIST = 6.0      # Fusion radius (Meters)
ISOLATION_RADIUS = 15.0    # Calibration isolation (Meters)
SMOOTHING = 5.0            # RBF Smoothing
DOWNSAMPLE = 2             # Plot reduction

# --- 1. PARSING & ALIGNMENT ---
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
        m_bgx = re.search(r'(?:BackgroundImage|Background_)PosX="([^"]+)"', content) or re.search(r'BackgroundImagePosX="([^"]+)"', content)
        if m_bgx: config['bg_off_x'] = float(m_bgx.group(1))
        m_bgy = re.search(r'(?:BackgroundImage|Background_)PosY="([^"]+)"', content) or re.search(r'BackgroundImagePosY="([^"]+)"', content)
        if m_bgy: config['bg_off_y'] = float(m_bgy.group(1))
        m_s0x = re.search(r'Radarsensor_0_Position_X="([^"]+)"', content)
        m_s0y = re.search(r'Radarsensor_0_Position_Y="([^"]+)"', content)
        if m_s0x and m_s0y:
            config['s0_x'] = (float(m_s0x.group(1)) - config['bg_off_x']) * config['scale']
            config['s0_y'] = (float(m_s0y.group(1)) - config['bg_off_y']) * config['scale']
    return config, img_b64

def load_gates(filepath, map_config):
    """
    Loads gates WITHOUT re-applying scale. 
    Assumes gates.json is already in Map Meters (from the designer tool).
    """
    if not os.path.exists(filepath):
        print("⚠️ No gates.json found.")
        return []
        
    with open(filepath, 'r') as f: gates_raw = json.load(f)
    gates = []
    print("\n--- Loading Gates ---")
    for g in gates_raw:
        # Heuristic: Name gates like "S0_Entry" implies Sensor 0 is the owner
        sensor = 0
        if 'S1' in g['name']: sensor = 1
        elif 'S2' in g['name']: sensor = 2
        elif 'S3' in g['name']: sensor = 3
        
        # TRUST THE JSON (Meters)
        p1 = (g['p1'][0], g['p1'][1])
        p2 = (g['p2'][0], g['p2'][1])
        
        gates.append({
            'name': g['name'],
            'owner': sensor, # The Domain Owner
            'line': LineString([p1, p2]),
            'p1': p1, 'p2': p2
        })
        print(f"   Gate {g['name']} (Owner S{sensor}) loaded.")
    return gates

def parse_and_align_data(filepath, map_config):
    data = []
    evo_s0 = {'x': 0, 'y': 0} # Default
    
    # 1. Find Anchor
    with open(filepath, 'r') as f:
        for line in f:
            if line.startswith('C;'):
                parts = line.split(';')
                if len(parts) > 1:
                    vals = parts[1].split(',')
                    if len(vals) >= 3:
                        evo_s0['x'] = float(vals[0])
                        evo_s0['y'] = float(vals[1])
                        break
                        
    trans_x = map_config['s0_x'] - evo_s0['x']
    trans_y = map_config['s0_y'] - evo_s0['y']

    # 2. Parse Tracks
    with open(filepath, 'r') as f: lines = f.readlines()
    
    current_time = 0.0
    for line in lines:
        line = line.strip()
        if ':' in line and len(line) < 15:
            try:
                parts = line.split(':')
                current_time = float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
            except: pass
            continue
        
        if line.startswith('F;'):
            parts = line.split(';')
            for ent in parts[2:]:
                if not ent: continue
                p = ent.split(',')
                if len(p) < 4: continue
                try:
                    oid = int(p[0])
                    x = float(p[2]) + trans_x
                    y = float(p[3]) + trans_y
                    sensor_id = oid % 10
                    if sensor_id > 3: sensor_id = sensor_id % 4 
                    
                    data.append({
                        'Time': current_time, 
                        'ID': oid, 
                        'X': x, 'Y': y, 
                        'Sensor': sensor_id
                    })
                except: pass
    
    return pd.DataFrame(data)

# --- 2. SPATIAL BIAS (RBF) ---
def train_spatial_bias(df):
    print("--- 1. Learning Spatial Bias ---")
    df = df.sort_values('Time')
    times = df['Time'].unique()
    training = []
    
    for t in times[::5]:
        frame = df[df['Time'] == t]
        if len(frame) < 2: continue
        
        s0_objs = frame[frame['Sensor'] == 0]
        other_objs = frame[frame['Sensor'] != 0]
        
        if s0_objs.empty or other_objs.empty: continue
        
        for _, s0 in s0_objs.iterrows():
            # Isolation Check
            if np.sum(np.sqrt((s0_objs['X']-s0['X'])**2 + (s0_objs['Y']-s0['Y'])**2) < ISOLATION_RADIUS) > 1: continue
            
            # Find Candidate
            dists = np.sqrt((other_objs['X'] - s0['X'])**2 + (other_objs['Y'] - s0['Y'])**2)
            min_idx = dists.idxmin()
            
            if dists[min_idx] < 10.0: # Loose match
                match = other_objs.loc[min_idx]
                training.append({
                    'x': match['X'], 'y': match['Y'], 
                    'dx': s0['X'] - match['X'], 'dy': s0['Y'] - match['Y'], 
                    'sensor': match['Sensor']
                })
                
    models = {}
    train_df = pd.DataFrame(training)
    if train_df.empty: return models
    
    for sid in train_df['sensor'].unique():
        s_data = train_df[train_df['sensor'] == sid]
        if len(s_data) > 5:
            try:
                models[sid] = (
                    Rbf(s_data['x'], s_data['y'], s_data['dx'], function='multiquadric', smooth=SMOOTHING),
                    Rbf(s_data['x'], s_data['y'], s_data['dy'], function='multiquadric', smooth=SMOOTHING)
                )
            except: pass
    return models

def apply_correction(df, models):
    if not models:
        df['CorrX'] = df['X']
        df['CorrY'] = df['Y']
        return df
    
    cx, cy = [], []
    for _, row in df.iterrows():
        sid = row['Sensor']
        x, y = row['X'], row['Y']
        if sid != 0 and sid in models:
            rbf_x, rbf_y = models[sid]
            cx.append(x + rbf_x(x, y))
            cy.append(y + rbf_y(x, y))
        else:
            cx.append(x)
            cy.append(y)
    df['CorrX'] = cx
    df['CorrY'] = cy
    return df

# --- 3. HYBRID FUSION LOGIC ---
def process_tracks_hybrid(df, gates):
    print("--- 2. Processing Hybrid Fusion (Strict Domain + Smooth Blend) ---")
    
    raw_tracks = {}
    
    # 1. CLASSIFY & FILTER GHOSTS
    for (sensor, oid), group in df.groupby(['Sensor', 'ID']):
        track = group.sort_values('Time').reset_index(drop=True)
        if len(track) < 2: continue
        
        # Check Crossings
        crossings = []
        for i in range(len(track)-1):
            p1 = Point(track.iloc[i]['CorrX'], track.iloc[i]['CorrY'])
            p2 = Point(track.iloc[i+1]['CorrX'], track.iloc[i+1]['CorrY'])
            seg = LineString([p1, p2])
            for gate in gates:
                if seg.intersects(gate['line']):
                    crossings.append({'owner': gate['owner'], 'time': track.iloc[i]['Time']})
        
        track_type = 'unknown'
        
        if not crossings:
            track_type = 'no_cross' # Keep as Raw
        else:
            owners = set(c['owner'] for c in crossings)
            if len(owners) == 1:
                # Internal Track
                gate_owner = list(owners)[0]
                if sensor == gate_owner:
                    track_type = 'internal_valid'
                else:
                    track_type = 'internal_ghost' # <--- DELETE THIS
            else:
                # Transition Track
                track_type = 'transition'

        # APPLY FILTER
        if track_type != 'internal_ghost':
            raw_tracks[(sensor, oid)] = {
                'df': track, 'type': track_type, 'crossings': crossings
            }

    print(f"   Kept {len(raw_tracks)} tracks. Removed ghosts.")

    # 2. FUSE TRANSITIONS
    transitions = {k: v for k, v in raw_tracks.items() if v['type'] == 'transition'}
    matches = []
    consumed = set()
    
    keys = list(transitions.keys())
    for i in range(len(keys)):
        k1 = keys[i]
        if k1 in consumed: continue
        
        best_match = None
        best_dist = FINE_MATCH_DIST
        
        t1 = transitions[k1]['df']
        
        for j in range(i+1, len(keys)):
            k2 = keys[j]
            if k2 in consumed: continue
            
            # Must be different sensors
            if k1[0] == k2[0]: continue
            
            t2 = transitions[k2]['df']
            
            # Overlap
            common = np.intersect1d(t1['Time'].values, t2['Time'].values)
            if len(common) < 3: continue
            
            # Distance (Corrected)
            c1 = t1[t1['Time'].isin(common)]
            c2 = t2[t2['Time'].isin(common)]
            dist = np.mean(np.sqrt((c1['CorrX'].values - c2['CorrX'].values)**2 + 
                                   (c1['CorrY'].values - c2['CorrY'].values)**2))
            
            if dist < best_dist:
                best_dist = dist
                best_match = k2
                
        if best_match:
            matches.append({'k1': k1, 'k2': best_match})
            consumed.add(k1)
            consumed.add(best_match)

    # 3. GENERATE OUTPUT
    final_rows = []
    
    # Process Matches (Sigmoid Blend)
    for m in matches:
        k1, k2 = m['k1'], m['k2']
        t1 = transitions[k1]
        t2 = transitions[k2]
        
        # Direction Logic: Use Gate Times
        # Find first gate crossing for each
        c1_time = t1['crossings'][0]['time'] if t1['crossings'] else 0
        c2_time = t2['crossings'][0]['time'] if t2['crossings'] else 0
        
        # Sort by who crossed first
        if c2_time < c1_time:
            k1, k2 = k2, k1
            t1, t2 = t2, t1
            c1_time, c2_time = c2_time, c1_time
            
        start_owner = t1['crossings'][0]['owner'] if t1['crossings'] else k1[0]
        end_owner = t2['crossings'][-1]['owner'] if t2['crossings'] else k2[0]
        
        # Blend Duration based on Gate Separation
        # (Approximate time between entering Gate A and exiting Gate B)
        # Or simpler: The entire overlap period.
        
        df1 = t1['df']
        df2 = t2['df']
        all_times = sorted(set(df1['Time']).union(set(df2['Time'])))
        
        # Overlap Window
        common = np.intersect1d(df1['Time'].values, df2['Time'].values)
        if len(common) > 0:
            blend_start = common[0]
            blend_duration = common[-1] - common[0]
            if blend_duration <= 0: blend_duration = 1.0
        else:
            blend_start = c1_time
            blend_duration = 1.0
            
        for t in all_times:
            p1 = df1[df1['Time'] == t]
            p2 = df2[df2['Time'] == t]
            
            has1 = not p1.empty
            has2 = not p2.empty
            
            x, y, h = 0, 0, ""
            
            if has1 and not has2:
                x, y = p1['CorrX'].values[0], p1['CorrY'].values[0]
                h = f"Valid S{start_owner}"
            elif not has1 and has2:
                x, y = p2['CorrX'].values[0], p2['CorrY'].values[0]
                h = f"Valid S{end_owner}"
            elif has1 and has2:
                # SIGMOID BLEND
                alpha = (t - blend_start) / blend_duration
                alpha = max(0.0, min(1.0, alpha))
                w = alpha * alpha * (3 - 2 * alpha)
                
                x = (1-w)*p1['CorrX'].values[0] + w*p2['CorrX'].values[0]
                y = (1-w)*p1['CorrY'].values[0] + w*p2['CorrY'].values[0]
                h = f"Handoff {w:.2f}"
                
            final_rows.append({
                'Time': t, 'X': x, 'Y': y, 'Type': 'Fused', 'Hover': h, 'ColorID': f"F_{k1[1]}"
            })

    # Process Unmatched (Internal / No-Cross / Unmatched Transition)
    for key, val in raw_tracks.items():
        if key in consumed: continue
        
        sensor, oid = key
        # Use Corrected Coords
        for _, row in val['df'].iterrows():
            final_rows.append({
                'Time': row['Time'], 
                'X': row['CorrX'], 'Y': row['CorrY'], 
                'Type': 'Raw', 
                'Hover': f"S{sensor} #{oid}", 
                'ColorID': oid
            })

    return pd.DataFrame(final_rows)

def plot_final(df, map_config, bg_image, gates):
    print("--- Plotting ---")
    if df.empty: return
    
    def get_color(row):
        if row['Type'] == 'Fused': return 'white'
        if 'S0' in row['Hover']: return 'cyan'
        if 'S1' in row['Hover']: return 'yellow'
        return 'lime'

    df['ColorVal'] = df.apply(get_color, axis=1)
    df = df.sort_values('Time')
    
    times = df['Time'].unique()
    df = df[df['Time'].isin(times[::DOWNSAMPLE][:600])]
    
    fig = px.scatter(
        df, x='X', y='Y', animation_frame='Time', animation_group='Hover',
        color='ColorVal', hover_name='Hover',
        color_discrete_map='identity',
        title="Hybrid Gate Fusion (Ghosts Removed + Sigmoid Blend)"
    )
    
    fig.update_traces(marker=dict(size=10, opacity=0.9, line=dict(width=1, color='black')))
    
    for g in gates:
        fig.add_shape(type="line", x0=g['p1'][0], y0=g['p1'][1], x1=g['p2'][0], y1=g['p2'][1],
            line=dict(color="orange", width=2, dash="dash"))
    
    w = map_config['width'] * map_config['scale']
    h = map_config['height'] * map_config['scale']
    
    fig.update_layout(
        images=[dict(source=bg_image, xref="x", yref="y", x=0, y=0, sizex=w, sizey=h, sizing="stretch", opacity=0.8, layer="below")],
        xaxis=dict(range=[0, w], showgrid=False, zeroline=False),
        yaxis=dict(range=[h, 0], showgrid=False, zeroline=False),
        template="plotly_dark", height=800
    )
    fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = 100
    fig.write_html("fusion_hybrid.html")
    print("✓ Saved to fusion_hybrid.html")

if __name__ == "__main__":
    cfg, img = parse_xml_config(XML_FILE)
    gates = load_gates(GATES_FILE, cfg)
    df = parse_and_align_data(DATA_FILE, cfg)
    
    if not df.empty:
        models = train_spatial_bias(df)
        df_corr = apply_correction(df, models)
        final_df = process_tracks_hybrid(df_corr, gates)
        plot_final(final_df, cfg, img, gates)