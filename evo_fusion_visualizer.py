import re
import base64
import io
import math
import pandas as pd
import numpy as np
import plotly.express as px
from PIL import Image

# --- CONFIGURATION ---
XML_FILE = "us95&sh8_iprj.txt"
DATA_FILE = "EVO_raw_data_1770174722.txt"

# Fusion Tuning
MATCH_RADIUS = 10.0   # Loose radius for initial candidate search
ISOLATION_DIST = 15.0 # How far other cars must be to count as "Clean Data" for calibration
MIN_OVERLAP_FRAMES = 5
DOWNSAMPLE = 2

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

def parse_and_align_data(filepath, map_config):
    data = []
    evo_s0 = {'x': None, 'y': None}
    
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
    
    if evo_s0['x'] is None: return pd.DataFrame() 

    trans_x = map_config['s0_x'] - evo_s0['x']
    trans_y = map_config['s0_y'] - evo_s0['y']

    with open(filepath, 'r') as f:
        lines = f.readlines()
        
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
                        'X': x,
                        'Y': y,
                        'Sensor': sensor_id
                    })
                except: pass
                
    return pd.DataFrame(data)

def learn_systematic_bias(raw_tracks, s1, s2):
    """
    Looks for isolated cars to determine the average offset (bias) 
    between Sensor 1 and Sensor 2.
    """
    ids_1 = [i for s, i in raw_tracks.keys() if s == s1]
    ids_2 = [i for s, i in raw_tracks.keys() if s == s2]
    
    biases_x = []
    biases_y = []
    
    # We only check a subset to be fast
    for id1 in ids_1:
        t1 = raw_tracks[(s1, id1)]
        
        # Find frames where this car is ALONE (Sparse Data)
        # For simplicity, we just check if it has ONE match in S2 that is spatially distinct
        
        for id2 in ids_2:
            t2 = raw_tracks[(s2, id2)]
            
            # Common times
            common_times = np.intersect1d(t1['Time'].values, t2['Time'].values)
            if len(common_times) < 10: continue # Need decent overlap for stats
            
            # Align frames
            df1 = t1[t1['Time'].isin(common_times)].sort_values('Time')
            df2 = t2[t2['Time'].isin(common_times)].sort_values('Time')
            
            # Check Euclidian Dist
            dx = df1['X'].values - df2['X'].values
            dy = df1['Y'].values - df2['Y'].values
            dist = np.sqrt(dx**2 + dy**2)
            
            # If they are reasonably close (candidates) AND consistent
            if np.mean(dist) < MATCH_RADIUS:
                # This is a candidate match.
                # In a robust system, we would check if any OTHER S2 objects are close
                # to confirm isolation. For now, we assume < MATCH_RADIUS implies 
                # a match candidate.
                
                biases_x.extend(dx)
                biases_y.extend(dy)

    if not biases_x:
        return 0.0, 0.0
        
    # Robust Mean (Filter outliers)
    bx = np.array(biases_x)
    by = np.array(biases_y)
    
    # Reject anything outside 1 std dev (removes "wrong car" matches from the calibration set)
    mask = (abs(bx - np.mean(bx)) < 2 * np.std(bx)) & (abs(by - np.mean(by)) < 2 * np.std(by))
    
    final_dx = np.mean(bx[mask])
    final_dy = np.mean(by[mask])
    
    return final_dx, final_dy

def fuse_tracks_bias_aware(df):
    print("--- Running Bias-Aware Fusion Engine ---")
    
    df = df.sort_values('Time')
    
    # 1. Group Raw Tracks
    raw_tracks = {}
    for (sensor, oid), group in df.groupby(['Sensor', 'ID']):
        raw_tracks[(sensor, oid)] = group.drop_duplicates(subset='Time').sort_values('Time')

    matches = [] 
    sensors = sorted(df['Sensor'].unique())

    # Iterate sensor pairs
    for i in range(len(sensors)):
        for j in range(i + 1, len(sensors)):
            s1 = sensors[i]
            s2 = sensors[j]
            
            print(f"   Calibrating Pair: S{s1} vs S{s2}...")
            
            # 2. LEARN BIAS (The systematic error)
            # bias_x = S1_x - S2_x
            bias_x, bias_y = learn_systematic_bias(raw_tracks, s1, s2)
            print(f"      -> Detected Bias: S{s2} is offset by ({bias_x:.2f}, {bias_y:.2f})m relative to S{s1}")
            
            # 3. MATCH WITH BIAS CORRECTION
            ids_1 = [k for s, k in raw_tracks.keys() if s == s1]
            ids_2 = [k for s, k in raw_tracks.keys() if s == s2]
            
            for id1 in ids_1:
                t1 = raw_tracks[(s1, id1)]
                for id2 in ids_2:
                    t2 = raw_tracks[(s2, id2)]
                    
                    common_times = np.intersect1d(t1['Time'].values, t2['Time'].values)
                    if len(common_times) < MIN_OVERLAP_FRAMES: continue
                    
                    df1_c = t1[t1['Time'].isin(common_times)].sort_values('Time')
                    df2_c = t2[t2['Time'].isin(common_times)].sort_values('Time')
                    
                    min_len = min(len(df1_c), len(df2_c))
                    df1_c = df1_c.iloc[:min_len]
                    df2_c = df2_c.iloc[:min_len]
                    
                    # BIAS CORRECTION:
                    # We shift S2 by the bias to see if it aligns with S1
                    # S2_corrected = S2 + Bias
                    # Dist = S1 - (S2 + Bias) = (S1 - S2) - Bias
                    
                    adj_dx = (df1_c['X'].values - df2_c['X'].values) - bias_x
                    adj_dy = (df1_c['Y'].values - df2_c['Y'].values) - bias_y
                    
                    dist = np.sqrt(adj_dx**2 + adj_dy**2)
                    
                    # Use a tighter threshold now that we removed bias
                    if np.mean(dist) < (MATCH_RADIUS / 2):
                        matches.append({
                            's1': s1, 'id1': id1,
                            's2': s2, 'id2': id2,
                            'times': common_times
                        })

    # 4. Generate Output (Same logic as before, just cleaner matches)
    fused_data = []
    consumed = set()
    
    for m in matches:
        s1, id1 = m['s1'], m['id1']
        s2, id2 = m['s2'], m['id2']
        times = m['times']
        
        t1 = raw_tracks[(s1, id1)]
        t2 = raw_tracks[(s2, id2)]
        
        # Direction check
        if t2['Time'].min() < t1['Time'].min():
             s1, s2 = s2, s1
             id1, id2 = id2, id1
             t1, t2 = t2, t1

        all_times = sorted(list(set(t1['Time']).union(set(t2['Time']))))
        
        # Consume inputs
        consumed.add((s1, id1))
        consumed.add((s2, id2))

        for t in all_times:
            p1 = t1[t1['Time'] == t]
            p2 = t2[t2['Time'] == t]
            
            exists1 = not p1.empty
            exists2 = not p2.empty
            
            new_x, new_y = 0, 0
            hover_txt = ""
            
            if exists1 and not exists2:
                new_x = p1['X'].values[0]
                new_y = p1['Y'].values[0]
                hover_txt = f"Fused: {id1} (S{s1} Only)"
                
            elif not exists1 and exists2:
                new_x = p2['X'].values[0]
                new_y = p2['Y'].values[0]
                hover_txt = f"Fused: {id2} (S{s2} Only)"
                
            elif exists1 and exists2:
                overlap_start = times[0]
                overlap_end = times[-1]
                duration = overlap_end - overlap_start
                alpha = 0.5
                if duration > 0: alpha = (t - overlap_start) / duration
                
                # We blend the raw positions (not bias corrected) for the visual handoff
                # because we want to visually slide from one sensor's "truth" to the other's "truth"
                x1 = p1['X'].values[0]
                y1 = p1['Y'].values[0]
                x2 = p2['X'].values[0]
                y2 = p2['Y'].values[0]
                
                new_x = (1 - alpha) * x1 + (alpha) * x2
                new_y = (1 - alpha) * y1 + (alpha) * y2
                
                hover_txt = f"Handoff {alpha*100:.0f}%: {id1} -> {id2}"

            fused_data.append({
                'Time': t,
                'X': new_x, 'Y': new_y,
                'Type': 'Fused Object',
                'Hover': hover_txt,
                'Sensor': 'Fused',
                'ColorID': id1 # Inherit color
            })
            
    fused_df = pd.DataFrame(fused_data)
    
    # Add Unmatched
    unmatched_data = []
    for (s, oid), group in raw_tracks.items():
        if (s, oid) not in consumed:
            g = group.copy()
            g['Type'] = 'Raw Sensor'
            g['Hover'] = g.apply(lambda r: f"Raw: {r['ID']} (S{r['Sensor']})", axis=1)
            g['ColorID'] = g['ID']
            g['Sensor'] = g['Sensor'] # Keep numeric for color map
            unmatched_data.append(g)
            
    if unmatched_data:
        unmatched_df = pd.concat(unmatched_data)
        return fused_df, unmatched_df
    return fused_df, pd.DataFrame()

def plot_traffic(fused_df, raw_df, map_config, bg_image):
    print("--- Generating Visualization ---")
    
    # Process Raw for background plotting
    raw_viz = raw_df.copy()
    sensor_colors = {0: 'cyan', 1: 'yellow', 2: 'lime', 3: 'magenta'}
    raw_viz['ColorVal'] = raw_viz['Sensor'].map(sensor_colors)

    if not fused_df.empty:
        fused_df['Type'] = 'Fused Object'
        fused_df['ColorVal'] = 'white'
        plot_df = pd.concat([raw_viz, fused_df])
    else:
        plot_df = raw_viz

    plot_df = plot_df.sort_values('Time')
    
    # Downsample
    times = plot_df['Time'].unique()
    sel_times = times[::DOWNSAMPLE][:500]
    plot_df = plot_df[plot_df['Time'].isin(sel_times)]
    
    fig = px.scatter(
        plot_df, 
        x='X', y='Y', 
        animation_frame='Time', 
        animation_group='Hover', 
        color='ColorVal',       
        hover_name='Hover',
        title="Bias-Corrected Sensor Fusion",
        color_discrete_map="identity"
    )
    
    fig.update_traces(marker=dict(size=12, opacity=0.8, line=dict(width=1, color='black')))
    
    # Update Background
    width_m = map_config['width'] * map_config['scale']
    height_m = map_config['height'] * map_config['scale']
    
    fig.update_layout(
        images=[dict(
            source=bg_image,
            xref="x", yref="y",
            x=0, y=0,
            sizex=width_m, sizey=height_m,
            sizing="stretch",
            opacity=0.8,
            layer="below"
        )],
        xaxis=dict(range=[0, width_m], showgrid=False, zeroline=False),
        yaxis=dict(range=[height_m, 0], showgrid=False, zeroline=False),
        template="plotly_dark",
        height=800
    )
    
    fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = 100

    print("--- Saving to 'fusion_bias_corrected.html' ---")
    fig.write_html("fusion_bias_corrected.html")
    print("Done.")

if __name__ == "__main__":
    print("1. Config...")
    cfg, img = parse_xml_config(XML_FILE)
    print("2. Aligning...")
    raw_df = parse_and_align_data(DATA_FILE, cfg)
    print("3. Fusing with Bias Learning...")
    fused_df, unmatched_df = fuse_tracks_bias_aware(raw_df)
    print("4. Plotting...")
    plot_traffic(fused_df, unmatched_df, cfg, img)