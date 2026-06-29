import pandas as pd
import numpy as np
import re
import base64
import io
import json
import plotly.express as px
from scipy.interpolate import Rbf
from shapely.geometry import LineString, Point
from PIL import Image

# --- CONFIGURATION ---
XML_FILE = "us95&sh8_iprj.txt"
DATA_FILE = "EVO_raw_data_1770174722.txt"
GATES_FILE = "gates.json"

# Tuning
COARSE_MATCH_DIST = 10.0   # Initial loose search radius for calibration
FINE_MATCH_DIST = 5.0      # Strict radius for final fusion matching
ISOLATION_RADIUS = 15.0    # "Clean data" must be this far from other cars
MIN_CALIB_POINTS = 10      # Need at least this many data points to build the bias map
SMOOTHING = 5.0            # RBF Smoothing factor (prevents overfitting to noise)

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
    Load gates and transform from display coordinates to track coordinates.
    Gates are defined in display space (0,0 = top-left of background image).
    Tracks are in sensor-relative space after alignment.
    """
    with open(filepath, 'r') as f:
        gates_raw = json.load(f)
    
    gates = []
    print("\n--- Loading Gates ---")
    print(f"   S0 sensor position in map coords: ({map_config['s0_x']:.1f}, {map_config['s0_y']:.1f})")
    
    for g in gates_raw:
        # Extract sensor from name (e.g., "S0_Gate" -> 0, "S1_Gate" -> 1)
        sensor = int(g['name'].split('_')[0][1:]) if g['name'].startswith('S') else None
        
        # Gates were drawn in display coordinates (map image space)
        # We need to transform them to match the track coordinate system
        # The track data has been shifted so S0 is at map_config['s0_x'], map_config['s0_y']
        # But the gates are relative to the background image origin
        # So we DON'T apply any additional transformation - gates and tracks should already align
        # because tracks were aligned TO the map via: trans_x = map_config['s0_x'] - evo_s0['x']
        
        p1 = (g['p1'][0], g['p1'][1])
        p2 = (g['p2'][0], g['p2'][1])
        
        gates.append({
            'name': g['name'],
            'sensor': sensor,
            'line': LineString([p1, p2]),
            'p1': p1,
            'p2': p2
        })
        
        print(f"   {g['name']} (S{sensor}): ({p1[0]:.1f}, {p1[1]:.1f}) -> ({p2[0]:.1f}, {p2[1]:.1f})")
    
    return gates

def parse_and_align_data(filepath, map_config):
    data = []
    evo_s0 = {'x': None, 'y': None}
    
    print("--- Parsing Data File ---")
    
    # First pass: find S0 position
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
    
    # Global Offset (Rough Alignment)
    trans_x = map_config['s0_x'] - evo_s0['x']
    trans_y = map_config['s0_y'] - evo_s0['y']
    print(f"   Translation: ({trans_x:.2f}, {trans_y:.2f})")

    # Second pass: extract object data
    with open(filepath, 'r') as f:
        lines = f.readlines()
    
    current_time = 0.0
    time_count = 0
    obj_count = 0
    
    for line in lines:
        line = line.strip()
        
        # Parse timestamp lines (format: HH:MM:SS.mmm)
        if ':' in line and '.' in line and len(line) < 20 and not line.startswith('F;'):
            try:
                # Handle format like "19:12:02.433"
                time_parts = line.split(':')
                if len(time_parts) == 3:
                    hours = float(time_parts[0])
                    minutes = float(time_parts[1])
                    seconds = float(time_parts[2])
                    current_time = hours * 3600 + minutes * 60 + seconds
                    time_count += 1
            except Exception as e:
                pass
            continue
        
        # Parse object data lines
        if line.startswith('F;'):
            parts = line.split(';')
            if len(parts) < 3:
                continue
                
            for ent in parts[4:]:  # Skip first 4 fields (F, frame_id, ?, ?)
                if not ent: continue
                p = ent.split(',')
                if len(p) < 4: continue
                
                try:
                    oid = int(p[0])
                    x = float(p[2]) + trans_x
                    y = float(p[3]) + trans_y
                    sensor_id = oid % 10
                    if sensor_id > 3: 
                        sensor_id = sensor_id % 4 
                    
                    data.append({
                        'Time': current_time, 
                        'ID': oid, 
                        'X': x, 
                        'Y': y, 
                        'Sensor': sensor_id
                    })
                    obj_count += 1
                except Exception as e:
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

# --- SPATIAL BIAS LEARNING ---
def train_spatial_bias_model(df):
    """
    Builds an RBF Interpolator to predict the error (dx, dy) 
    between sensors based on location (x, y).
    """
    print("--- Training Spatial Bias Model ---")
    
    df = df.sort_values('Time')
    times = df['Time'].unique()
    
    training_points = []
    calib_frames = times[::5] 
    
    print(f"   Scanning {len(calib_frames)} frames for isolated cars...")
    
    for t in calib_frames:
        frame = df[df['Time'] == t]
        if len(frame) < 2: continue
        
        s0_objs = frame[frame['Sensor'] == 0]
        other_objs = frame[frame['Sensor'] != 0]
        
        if s0_objs.empty or other_objs.empty: continue
        
        for _, s0_row in s0_objs.iterrows():
            x0, y0 = s0_row['X'], s0_row['Y']
            
            # Isolation Check
            s0_dists = np.sqrt((s0_objs['X'] - x0)**2 + (s0_objs['Y'] - y0)**2)
            if np.sum(s0_dists < ISOLATION_RADIUS) > 1:
                continue 
            
            # Find Candidates in Other Sensors
            dists = np.sqrt((other_objs['X'] - x0)**2 + (other_objs['Y'] - y0)**2)
            
            min_idx = dists.idxmin()
            min_dist = dists[min_idx]
            
            if min_dist < COARSE_MATCH_DIST:
                match = other_objs.loc[min_idx]
                dx = x0 - match['X']
                dy = y0 - match['Y']
                
                training_points.append({
                    'x': match['X'], 'y': match['Y'], 
                    'dx': dx, 'dy': dy,
                    'sensor': match['Sensor']
                })

    print(f"   Found {len(training_points)} calibration points.")
    
    models = {}
    train_df = pd.DataFrame(training_points)
    
    if train_df.empty:
        print("⚠️ Not enough calibration data found. Using Raw alignment.")
        return None

    for sid in train_df['sensor'].unique():
        s_data = train_df[train_df['sensor'] == sid]
        if len(s_data) < MIN_CALIB_POINTS:
            print(f"   Skipping S{sid} (only {len(s_data)} points)")
            continue
            
        print(f"   Fitting Spatial Model for Sensor {sid} ({len(s_data)} pts)...")
        try:
            rbf_x = Rbf(s_data['x'], s_data['y'], s_data['dx'], function='multiquadric', smooth=SMOOTHING)
            rbf_y = Rbf(s_data['x'], s_data['y'], s_data['dy'], function='multiquadric', smooth=SMOOTHING)
            models[sid] = (rbf_x, rbf_y)
        except Exception as e:
            print(f"   RBF Error S{sid}: {e}")
            
    return models

def apply_spatial_correction(df, models):
    """
    Applies the learned RBF warp to align all sensors to S0.
    """
    if not models:
        df['CorrX'] = df['X']
        df['CorrY'] = df['Y']
        return df
        
    print("--- Applying Spatial Correction ---")
    
    corr_x_list = []
    corr_y_list = []
    
    for _, row in df.iterrows():
        sid = row['Sensor']
        x, y = row['X'], row['Y']
        
        if sid == 0 or sid not in models:
            corr_x_list.append(x)
            corr_y_list.append(y)
        else:
            rbf_x, rbf_y = models[sid]
            dx = rbf_x(x, y)
            dy = rbf_y(x, y)
            
            corr_x_list.append(x + dx)
            corr_y_list.append(y + dy)
            
    df['CorrX'] = corr_x_list
    df['CorrY'] = corr_y_list
    return df

def check_gate_crossings(track_df, gates):
    """
    Check which gates a track crosses and return gate transitions.
    Returns: list of (sensor_label, time) for each crossing
    """
    crossings = []
    track_df = track_df.sort_values('Time').reset_index(drop=True)
    
    for i in range(len(track_df) - 1):
        p1 = Point(track_df.iloc[i]['CorrX'], track_df.iloc[i]['CorrY'])
        p2 = Point(track_df.iloc[i+1]['CorrX'], track_df.iloc[i+1]['CorrY'])
        segment = LineString([p1, p2])
        
        for gate in gates:
            if segment.intersects(gate['line']):
                crossings.append({
                    'sensor': gate['sensor'],
                    'time': track_df.iloc[i]['Time'],
                    'gate_name': gate['name']
                })
    
    return crossings

def classify_tracks_by_gates(df, gates):
    """
    Classify each track as:
    - 'entry': crosses from one sensor gate to another (needs fusion)
    - 'exit': the corresponding departure track
    - 'internal': stays within same sensor gates (ignore duplicates)
    """
    print("\n--- Classifying Tracks by Gate Crossings ---")
    print(f"   Gates in map coordinates:")
    for gate in gates:
        print(f"      {gate['name']} (S{gate['sensor']}): ({gate['p1'][0]:.1f}, {gate['p1'][1]:.1f}) -> ({gate['p2'][0]:.1f}, {gate['p2'][1]:.1f})")
    
    # Show data range
    print(f"\n   Track data range:")
    print(f"      X: {df['CorrX'].min():.1f} to {df['CorrX'].max():.1f}")
    print(f"      Y: {df['CorrY'].min():.1f} to {df['CorrY'].max():.1f}")
    
    tracks = {}
    total_tracks = 0
    
    for (sensor, oid), group in df.groupby(['Sensor', 'ID']):
        total_tracks += 1
        track = group.sort_values('Time').reset_index(drop=True)
        
        # Skip very short tracks
        if len(track) < 2:
            continue
            
        crossings = check_gate_crossings(track, gates)
        
        # Determine transition pattern
        sensors_crossed = [c['sensor'] for c in crossings]
        unique_sensors = set(sensors_crossed)
        
        track_type = 'unknown'
        if len(unique_sensors) > 1:
            # Crosses between different sensor gates
            track_type = 'transition'
        elif len(sensors_crossed) > 0:
            # Stays within same sensor
            track_type = 'internal'
        
        tracks[(sensor, oid)] = {
            'df': track,
            'type': track_type,
            'crossings': crossings,
            'sensors_crossed': sensors_crossed,
            'unique_sensors': unique_sensors
        }
    
    print(f"\n   Total tracks: {total_tracks}")
    print(f"   Tracks with 2+ points: {len(tracks)}")
    
    transition_count = sum(1 for t in tracks.values() if t['type'] == 'transition')
    internal_count = sum(1 for t in tracks.values() if t['type'] == 'internal')
    unknown_count = sum(1 for t in tracks.values() if t['type'] == 'unknown')
    
    print(f"   Transition tracks: {transition_count}")
    print(f"   Internal tracks: {internal_count}")
    print(f"   Unknown tracks: {unknown_count}")
    
    # Debug: show sample tracks
    if transition_count == 0 and internal_count == 0:
        print("\n   ⚠️ WARNING: No tracks crossing gates detected!")
        print("   Sample track analysis:")
        for i, (key, track) in enumerate(list(tracks.items())[:5]):
            sensor, oid = key
            df_t = track['df']
            print(f"\n   Track S{sensor}#{oid}:")
            print(f"      Points: {len(df_t)}")
            print(f"      X range: {df_t['CorrX'].min():.1f} to {df_t['CorrX'].max():.1f}")
            print(f"      Y range: {df_t['CorrY'].min():.1f} to {df_t['CorrY'].max():.1f}")
            print(f"      First point: ({df_t.iloc[0]['CorrX']:.1f}, {df_t.iloc[0]['CorrY']:.1f})")
            print(f"      Last point: ({df_t.iloc[-1]['CorrX']:.1f}, {df_t.iloc[-1]['CorrY']:.1f})")
            print(f"      Crossings: {len(track['crossings'])}")
            print(f"      Type: {track['type']}")
    
    return tracks

def fuse_tracks_with_gates(tracks):
    """
    Fuse tracks based on gate-crossing logic:
    - Only fuse tracks that show gate transitions
    - Use spatial proximity with corrected coordinates to find best match
    - If no gate crossings detected, fall back to showing all tracks
    """
    print("--- Fusing Transition Tracks ---")
    
    # Separate transition tracks by sensor
    transition_tracks = {k: v for k, v in tracks.items() if v['type'] == 'transition'}
    internal_tracks = {k: v for k, v in tracks.items() if v['type'] == 'internal'}
    unknown_tracks = {k: v for k, v in tracks.items() if v['type'] == 'unknown'}
    
    print(f"   Transition: {len(transition_tracks)}, Internal: {len(internal_tracks)}, Unknown: {len(unknown_tracks)}")
    
    # If no gate crossings detected, treat all tracks as "internal" for display
    if len(transition_tracks) == 0 and len(internal_tracks) == 0:
        print("   ⚠️ No gate crossings detected - displaying all tracks as raw data")
        internal_tracks = tracks
    
    matches = []
    consumed = set()
    
    # For each transition track, find its best match
    for key1, track1 in transition_tracks.items():
        if key1 in consumed:
            continue
            
        sensor1, id1 = key1
        df1 = track1['df']
        
        best_match = None
        best_overlap = 0
        
        # Look for matches in other sensors
        for key2, track2 in transition_tracks.items():
            if key2 in consumed or key2 == key1:
                continue
                
            sensor2, id2 = key2
            if sensor1 == sensor2:  # Same sensor, skip
                continue
                
            df2 = track2['df']
            
            # Find temporal overlap
            common_times = np.intersect1d(df1['Time'].values, df2['Time'].values)
            if len(common_times) < 3:
                continue
            
            # Check spatial proximity using corrected coordinates
            subset1 = df1[df1['Time'].isin(common_times)].reset_index(drop=True)
            subset2 = df2[df2['Time'].isin(common_times)].reset_index(drop=True)
            
            dists = np.sqrt((subset1['CorrX'].values - subset2['CorrX'].values)**2 + 
                           (subset1['CorrY'].values - subset2['CorrY'].values)**2)
            
            avg_dist = np.mean(dists)
            
            if avg_dist < FINE_MATCH_DIST and len(common_times) > best_overlap:
                best_overlap = len(common_times)
                best_match = (key2, track2, common_times, avg_dist)
        
        if best_match:
            key2, track2, common_times, avg_dist = best_match
            matches.append({
                'key1': key1,
                'key2': key2,
                'track1': track1,
                'track2': track2,
                'overlap_times': common_times,
                'avg_dist': avg_dist
            })
            consumed.add(key1)
            consumed.add(key2)
    
    print(f"   Created {len(matches)} fused track pairs")
    
    # Generate fused trajectories
    fused_data = []
    
    for m in matches:
        df1 = m['track1']['df']
        df2 = m['track2']['df']
        s1, id1 = m['key1']
        s2, id2 = m['key2']
        overlap = m['overlap_times']
        
        # Order by start time
        if df2['Time'].min() < df1['Time'].min():
            df1, df2 = df2, df1
            s1, s2 = s2, s1
            id1, id2 = id2, id1
        
        all_times = sorted(set(df1['Time']).union(set(df2['Time'])))
        overlap_start = overlap[0]
        overlap_end = overlap[-1]
        duration = overlap_end - overlap_start if overlap_end > overlap_start else 1
        
        for t in all_times:
            p1 = df1[df1['Time'] == t]
            p2 = df2[df2['Time'] == t]
            
            if not p1.empty and p2.empty:
                # Before handoff - use first sensor
                fused_data.append({
                    'Time': t,
                    'X': p1['CorrX'].values[0],
                    'Y': p1['CorrY'].values[0],
                    'Type': 'Fused',
                    'Hover': f"Fused {id1}→{id2} (S{s1})",
                    'ColorID': f"{id1}_{id2}"
                })
            elif p1.empty and not p2.empty:
                # After handoff - use second sensor
                fused_data.append({
                    'Time': t,
                    'X': p2['CorrX'].values[0],
                    'Y': p2['CorrY'].values[0],
                    'Type': 'Fused',
                    'Hover': f"Fused {id1}→{id2} (S{s2})",
                    'ColorID': f"{id1}_{id2}"
                })
            elif not p1.empty and not p2.empty:
                # Handoff zone - blend
                alpha = (t - overlap_start) / duration if duration > 0 else 0.5
                alpha = max(0.0, min(1.0, alpha))
                
                x = (1 - alpha) * p1['CorrX'].values[0] + alpha * p2['CorrX'].values[0]
                y = (1 - alpha) * p1['CorrY'].values[0] + alpha * p2['CorrY'].values[0]
                
                fused_data.append({
                    'Time': t,
                    'X': x,
                    'Y': y,
                    'Type': 'Fused',
                    'Hover': f"Handoff {alpha:.2f} ({id1}→{id2})",
                    'ColorID': f"{id1}_{id2}"
                })
    
    fused_df = pd.DataFrame(fused_data)
    
    # Keep internal and unconsumed tracks
    internal_data = []
    for key, track in tracks.items():
        if key not in consumed:
            df = track['df'].copy()
            sensor, oid = key
            
            # Use corrected coordinates for display
            for _, row in df.iterrows():
                internal_data.append({
                    'Time': row['Time'],
                    'X': row['CorrX'],
                    'Y': row['CorrY'],
                    'Type': track['type'],
                    'Hover': f"S{sensor} #{oid} ({track['type']})",
                    'ColorID': oid
                })
    
    internal_df = pd.DataFrame(internal_data)
    
    print(f"   Fused data points: {len(fused_df)}")
    print(f"   Internal data points: {len(internal_df)}")
    
    return fused_df, internal_df

def plot_final(fused, internal, map_config, bg_image, gates):
    print("--- Plotting ---")
    
    # Combine data
    if not fused.empty:
        fused['ColorVal'] = 'white'
    if not internal.empty:
        internal['ColorVal'] = internal.apply(lambda r: 
            {0:'cyan', 1:'yellow', 2:'lime', 3:'magenta'}.get(r['ColorID'] % 10, 'gray'), axis=1)
    
    df = pd.concat([internal, fused]) if not fused.empty else internal
    df = df.sort_values('Time')
    
    # Debug: print first few positions
    print(f"\n   Sample track positions:")
    for i in range(min(5, len(df))):
        print(f"      ({df.iloc[i]['X']:.1f}, {df.iloc[i]['Y']:.1f})")
    
    # Downsample for performance
    times = df['Time'].unique()
    df = df[df['Time'].isin(times[::2][:600])]
    
    fig = px.scatter(
        df, x='X', y='Y', animation_frame='Time', animation_group='Hover',
        color='ColorVal', hover_name='Hover',
        color_discrete_map='identity',
        title="Gate-Based Fusion (White = Fused, Colors = Internal/Raw)"
    )
    
    fig.update_traces(marker=dict(size=8, opacity=0.8, line=dict(width=1, color='black')))
    
    w = map_config['width'] * map_config['scale']
    h = map_config['height'] * map_config['scale']
    
    print(f"   Map dimensions: {w:.1f} x {h:.1f} meters")
    print(f"   Background offset: ({map_config['bg_off_x']:.1f}, {map_config['bg_off_y']:.1f})")
    print(f"   S0 position: ({map_config['s0_x']:.1f}, {map_config['s0_y']:.1f})")
    
    # Add gate lines
    for gate in gates:
        fig.add_shape(
            type="line",
            x0=gate['p1'][0], y0=gate['p1'][1],
            x1=gate['p2'][0], y1=gate['p2'][1],
            line=dict(color="red" if gate['sensor'] == 0 else "orange", width=3, dash="dash"),
            name=gate['name']
        )
        # Add text label
        fig.add_annotation(
            x=(gate['p1'][0] + gate['p2'][0])/2,
            y=(gate['p1'][1] + gate['p2'][1])/2,
            text=gate['name'],
            showarrow=False,
            font=dict(color="yellow", size=12)
        )
    
    fig.update_layout(
        images=[dict(source=bg_image, xref="x", yref="y", x=0, y=0, sizex=w, sizey=h, 
                    sizing="stretch", opacity=0.8, layer="below")],
        xaxis=dict(range=[0, w], showgrid=False, zeroline=False),
        yaxis=dict(range=[h, 0], showgrid=False, zeroline=False),
        template="plotly_dark", height=800
    )
    
    if fig.layout.updatemenus:
        fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = 100
    
    fig.write_html("fusion_gate_based.html")
    print("✓ Saved to fusion_gate_based.html")

if __name__ == "__main__":
    cfg, img = parse_xml_config(XML_FILE)
    gates = load_gates(GATES_FILE, cfg)
    df = parse_and_align_data(DATA_FILE, cfg)
    
    if df.empty:
        print("ERROR: No data loaded. Exiting.")
        exit(1)
    
    # 1. Learn spatial bias correction
    models = train_spatial_bias_model(df)
    
    # 2. Apply correction to all data
    df_corr = apply_spatial_correction(df, models)
    
    # 3. Classify tracks by gate crossings
    tracks = classify_tracks_by_gates(df_corr, gates)
    
    # 4. Fuse only transition tracks
    fused, internal = fuse_tracks_with_gates(tracks)
    
    # 5. Visualize
    plot_final(fused, internal, cfg, img, gates)
    