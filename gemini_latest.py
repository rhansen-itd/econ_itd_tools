import pandas as pd
import numpy as np
import re
import json
import os
import plotly.express as px
from scipy.interpolate import Rbf
from shapely.geometry import LineString, Point

# --- CONFIGURATION ---
XML_FILE = "us95&sh8_iprj.txt"
DATA_FILE = "EVO_raw_data_1770174722.txt"
GATES_FILE = "gates.json"

# Tuning
STITCH_TIME = 2.0       # Max gap to stitch broken IDs
STITCH_DIST = 15.0      # Max jump to stitch broken IDs
ISOLATION_RADIUS = 15.0 # For RBF calibration
COARSE_MATCH = 10.0     # For RBF calibration
SMOOTHING = 5.0         # RBF Smoothing
DOWNSAMPLE = 2          # Visualization speed

# --- 1. SETUP ---
def parse_xml_config(filepath):
    config = {'width': 2000, 'height': 2000, 'scale': 0.1, 'bg_off_x': 0, 'bg_off_y': 0, 's0_x': 0, 's0_y': 0}
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            m_scale = re.search(r'MeterPerPixel="([^"]+)"', content)
            if m_scale: config['scale'] = float(m_scale.group(1))
            m_bgx = re.search(r'BackgroundImagePosX="([^"]+)"', content)
            if m_bgx: config['bg_off_x'] = float(m_bgx.group(1))
            m_bgy = re.search(r'BackgroundImagePosY="([^"]+)"', content)
            if m_bgy: config['bg_off_y'] = float(m_bgy.group(1))
            m_s0x = re.search(r'Radarsensor_0_Position_X="([^"]+)"', content)
            if m_s0x: config['s0_x'] = (float(m_s0x.group(1)) - config['bg_off_x']) * config['scale']
            m_s0y = re.search(r'Radarsensor_0_Position_Y="([^"]+)"', content)
            if m_s0y: config['s0_y'] = (float(m_s0y.group(1)) - config['bg_off_y']) * config['scale']
            m_w = re.search(r'Width="([^"]+)"', content)
            if m_w: config['width'] = float(m_w.group(1))
            m_h = re.search(r'Height="([^"]+)"', content)
            if m_h: config['height'] = float(m_h.group(1))
    except: pass
    return config

def load_gates(filepath):
    # CLAUDE'S CORRECT LOGIC: Do not re-transform. Trust the JSON meters.
    if not os.path.exists(filepath): return []
    with open(filepath, 'r') as f: gates_raw = json.load(f)
    gates = []
    print("\n--- Loading Gates ---")
    for g in gates_raw:
        owner = 0
        if 'S1' in g['name']: owner = 1
        elif 'S2' in g['name']: owner = 2
        p1 = (g['p1'][0], g['p1'][1])
        p2 = (g['p2'][0], g['p2'][1])
        gates.append({'name': g['name'], 'owner': owner, 'line': LineString([p1, p2]), 'p1': p1, 'p2': p2})
    return gates

def parse_data(filepath, map_config):
    data = []
    evo_s0 = {'x':0, 'y':0}
    try:
        with open(filepath, 'r') as f:
            for line in f:
                if line.startswith('C;'):
                    parts = line.split(';')
                    if len(parts)>1: vals=parts[1].split(','); evo_s0={'x':float(vals[0]), 'y':float(vals[1])}; break
    except: pass
    trans_x = map_config['s0_x'] - evo_s0['x']
    trans_y = map_config['s0_y'] - evo_s0['y']
    
    with open(filepath, 'r') as f: lines = f.readlines()
    curr_time = 0.0
    for line in lines:
        if ':' in line and len(line)<15:
            try: p=line.strip().split(':'); curr_time=float(p[0])*3600+float(p[1])*60+float(p[2])
            except: pass
            continue
        if line.startswith('F;'):
            parts = line.split(';')
            for ent in parts[2:]:
                if not ent: continue
                p = ent.split(',')
                if len(p)<4: continue
                try:
                    oid = int(p[0])
                    x = float(p[2]) + trans_x
                    y = float(p[3]) + trans_y
                    sid = oid % 10
                    if sid > 3: sid = sid % 4
                    data.append({'Time': curr_time, 'ID': oid, 'X': x, 'Y': y, 'Sensor': sid})
                except: pass
    return pd.DataFrame(data)

# --- 2. PIPELINE ---

def stitch_tracks(df):
    print("--- 1. Stitching Broken Tracks ---")
    df = df.sort_values('Time').drop_duplicates(subset=['ID', 'Time'])
    stitched_dfs = []
    for sensor, group in df.groupby('Sensor'):
        stats = group.groupby('ID').agg(t_end=('Time', 'max'), x_end=('X', 'last'), y_end=('Y', 'last'), t_start=('Time', 'min'), x_start=('X', 'first'), y_start=('Y', 'first')).reset_index().sort_values('t_start')
        id_map = {i:i for i in stats['ID']}
        consumed = set()
        for i, row in stats.iterrows():
            if row['ID'] in consumed: continue
            candidates = stats[(stats['t_start'] > row['t_end']) & (stats['t_start'] < row['t_end'] + STITCH_TIME) & (~stats['ID'].isin(consumed))]
            if candidates.empty: continue
            dists = np.sqrt((candidates['x_start'] - row['x_end'])**2 + (candidates['y_start'] - row['y_end'])**2)
            if dists.min() < STITCH_DIST:
                match_id = candidates.loc[dists.idxmin(), 'ID']
                id_map[match_id] = id_map[row['ID']]
                consumed.add(match_id)
        g = group.copy()
        g['ID'] = g['ID'].map(id_map)
        stitched_dfs.append(g)
    return pd.concat(stitched_dfs)

def train_and_apply_warp(df):
    print("--- 2. RBF Warping (Claude's Logic) ---")
    df = df.sort_values('Time')
    training = []
    times = df['Time'].unique()
    for t in times[::10]:
        frame = df[df['Time'] == t]
        if len(frame) < 2: continue
        s0 = frame[frame['Sensor'] == 0]
        s1 = frame[frame['Sensor'] != 0]
        if s0.empty or s1.empty: continue
        for _, r0 in s0.iterrows():
            if np.sum(np.sqrt((s0['X']-r0['X'])**2 + (s0['Y']-r0['Y'])**2) < ISOLATION_RADIUS) > 1: continue
            dists = np.sqrt((s1['X']-r0['X'])**2 + (s1['Y']-r0['Y'])**2)
            if dists.min() < COARSE_MATCH:
                m = s1.loc[dists.idxmin()]
                training.append({'x': m['X'], 'y': m['Y'], 'dx': r0['X']-m['X'], 'dy': r0['Y']-m['Y'], 's': m['Sensor']})
    
    models = {}
    if training:
        tdf = pd.DataFrame(training)
        for s in tdf['s'].unique():
            sd = tdf[tdf['s']==s]
            if len(sd)>5:
                try: models[s] = (Rbf(sd['x'],sd['y'],sd['dx'], smooth=SMOOTHING), Rbf(sd['x'],sd['y'],sd['dy'], smooth=SMOOTHING))
                except: pass

    cx, cy = [], []
    for _, r in df.iterrows():
        if r['Sensor'] in models:
            mx, my = models[r['Sensor']]
            cx.append(r['X'] + mx(r['X'], r['Y']))
            cy.append(r['Y'] + my(r['X'], r['Y']))
        else:
            cx.append(r['X']); cy.append(r['Y'])
    df['CorrX'] = cx; df['CorrY'] = cy
    return df

def strict_gate_fusion(df, gates):
    print("--- 3. Strict Logic & Fusion ---")
    tracks = {}
    for (sensor, oid), group in df.groupby(['Sensor', 'ID']):
        t = group.sort_values('Time').reset_index(drop=True)
        if len(t) < 2: continue
        
        # Check Gates on Warped Data
        crossings = []
        path = LineString([Point(xy) for xy in zip(t['CorrX'], t['CorrY'])])
        for g in gates:
            if path.intersects(g['line']):
                crossings.append({'owner': g['owner'], 'time': t.iloc[len(t)//2]['Time']}) # Approx time
        
        # --- NO EXCEPTIONS LOGIC ---
        status = 'valid'
        if len(crossings) < 2: status = 'orphan' # < 2 Gates -> DELETE
        else:
            owners = set(c['owner'] for c in crossings)
            if len(owners) == 1:
                if sensor != list(owners)[0]: status = 'ghost' # Internal but wrong sensor -> DELETE
            else:
                status = 'transition' # Fuse
        
        if status not in ['orphan', 'ghost']:
            tracks[(sensor, oid)] = {'df': t, 'status': status, 'crossings': crossings}

    # Fuse
    final_rows = []
    processed = set()
    keys = list(tracks.keys())
    
    for i in range(len(keys)):
        k1 = keys[i]
        if k1 in processed: continue
        t1 = tracks[k1]['df']
        best_match = None; best_dist = 6.0
        
        for j in range(i+1, len(keys)):
            k2 = keys[j]
            if k2 in processed: continue
            if k1[0] == k2[0]: continue
            t2 = tracks[k2]['df']
            
            common = pd.merge(t1, t2, on='Time', suffixes=('_1', '_2'))
            if len(common) < 5: continue
            dist = np.mean(np.sqrt((common['CorrX_1']-common['CorrX_2'])**2 + (common['CorrY_1']-common['CorrY_2'])**2))
            if dist < best_dist:
                best_dist = dist; best_match = k2
        
        if best_match:
            k2 = best_match
            processed.add(k1); processed.add(k2)
            t2 = tracks[k2]['df']
            
            # Add Inputs
            for _, r in t1.iterrows(): final_rows.append({'Time':r['Time'], 'X':r['CorrX'], 'Y':r['CorrY'], 'Type':'Input', 'Hover':f"Input S{k1[0]}", 'ColorID':k1[0]})
            for _, r in t2.iterrows(): final_rows.append({'Time':r['Time'], 'X':r['CorrX'], 'Y':r['CorrY'], 'Type':'Input', 'Hover':f"Input S{k2[0]}", 'ColorID':k2[0]})
            
            # Fuse (Sigmoid Blend)
            times = sorted(set(t1['Time']).union(set(t2['Time'])))
            # Simple midpoint blend
            blend_start = min(t1['Time'].max(), t2['Time'].max()) - 1.0 # Last 1 sec overlap
            
            for t in times:
                p1 = t1[t1['Time']==t]
                p2 = t2[t2['Time']==t]
                x,y,h=0,0,""
                
                if not p1.empty and not p2.empty:
                    x = (p1['CorrX'].values[0] + p2['CorrX'].values[0])/2
                    y = (p1['CorrY'].values[0] + p2['CorrY'].values[0])/2
                    h = "Fused"
                elif not p1.empty: x,y,h = p1['CorrX'].values[0], p1['CorrY'].values[0], f"Fused S{k1[0]}"
                elif not p2.empty: x,y,h = p2['CorrX'].values[0], p2['CorrY'].values[0], f"Fused S{k2[0]}"
                final_rows.append({'Time':t, 'X':x, 'Y':y, 'Type':'Fused', 'Hover':h, 'ColorID':'Fused'})
        else:
            # Unmatched Valid
            processed.add(k1)
            for _, r in t1.iterrows():
                final_rows.append({'Time':r['Time'], 'X':r['CorrX'], 'Y':r['CorrY'], 'Type':'Internal', 'Hover':f"Valid S{k1[0]}", 'ColorID':k1[0]})

    return pd.DataFrame(final_rows)

def plot_final(df, map_config, bg_image, gates):
    if df.empty: 
        print("❌ Empty Result.")
        return
    def get_c(row):
        if row['Type'] == 'Fused': return 'white'
        return {0:'cyan', 1:'yellow', 2:'lime', 3:'magenta'}.get(row['ColorID'], 'gray')
    df['ColorVal'] = df.apply(get_c, axis=1)
    df = df.sort_values('Time')
    df = df[df['Time'].isin(df['Time'].unique()[::DOWNSAMPLE][:600])]
    
    fig = px.scatter(df, x='X', y='Y', animation_frame='Time', animation_group='Hover', color='ColorVal', hover_name='Hover', color_discrete_map='identity', title="Corrected Fusion")
    fig.for_each_trace(lambda t: t.update(marker=dict(size=6, opacity=0.3)) if 'Input' in t.hovertext else t.update(marker=dict(size=12, opacity=1.0, line=dict(width=1, color='black'))))
    for g in gates: fig.add_shape(type="line", x0=g['p1'][0], y0=g['p1'][1], x1=g['p2'][0], y1=g['p2'][1], line=dict(color="orange", width=2, dash="dash"))
    w = map_config.get('width', 2000) * map_config['scale']
    h = map_config.get('height', 2000) * map_config['scale']
    fig.update_layout(images=[dict(source=bg_image, xref="x", yref="y", x=0, y=0, sizex=w, sizey=h, sizing="stretch", opacity=0.8, layer="below")], xaxis=dict(range=[0, w], showgrid=False, zeroline=False), yaxis=dict(range=[h, 0], showgrid=False, zeroline=False), template="plotly_dark", height=800)
    fig.write_html("fusion_final_corrected.html")
    print("✓ Saved to fusion_final_corrected.html")

if __name__ == "__main__":
    cfg, img = parse_xml_config(XML_FILE)
    gates = load_gates(GATES_FILE)
    df = parse_data(DATA_FILE, cfg)
    if not df.empty:
        df = stitch_tracks(df)
        df = train_and_apply_warp(df)
        final_df = strict_gate_fusion(df, gates)
        plot_final(final_df, cfg, img, gates)