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
from datetime import datetime
import os

# --- PATH TEMPLATE SYSTEM ---

class PathTemplate:
    """Represents a learned trajectory path through the intersection"""
    
    def __init__(self, template_id, gate_sequence, initial_track_df, confidence=1.0):
        self.template_id = template_id
        self.gate_sequence = gate_sequence  # e.g., ["N_S0", "S_S0"]
        self.confidence = confidence
        self.samples = 1
        self.created = datetime.now().isoformat()
        self.last_seen = self.created
        
        # Store path as list of {x, y, velocity, weight}
        self.points = []
        for _, row in initial_track_df.iterrows():
            self.points.append({
                'x': row['CorrX'],
                'y': row['CorrY'],
                'velocity': 0.0,  # Will compute
                'weight': 1.0
            })
        
        self._compute_velocities()
    
    def _compute_velocities(self):
        """Compute velocity at each point"""
        for i in range(len(self.points) - 1):
            dx = self.points[i+1]['x'] - self.points[i]['x']
            dy = self.points[i+1]['y'] - self.points[i]['y']
            dist = np.sqrt(dx**2 + dy**2)
            # Assume 0.1s between points (typical radar rate)
            self.points[i]['velocity'] = dist / 0.1
        if self.points:
            self.points[-1]['velocity'] = self.points[-2]['velocity'] if len(self.points) > 1 else 0
    
    def add_track(self, track_df, weight=1.0):
        """Add a new track to this template using weighted average"""
        self.samples += 1
        self.last_seen = datetime.now().isoformat()
        
        # Resample new track to match template length
        if len(track_df) != len(self.points):
            # Simple linear interpolation to match lengths
            new_points = self._resample_track(track_df, len(self.points))
        else:
            new_points = [(row['CorrX'], row['CorrY']) for _, row in track_df.iterrows()]
        
        # Weighted average: old_point + weight * (new_point - old_point) / (total_weight + weight)
        total_weight = sum(p['weight'] for p in self.points)
        
        for i, (new_x, new_y) in enumerate(new_points):
            if i < len(self.points):
                old_x = self.points[i]['x']
                old_y = self.points[i]['y']
                old_weight = self.points[i]['weight']
                
                # Weighted update
                alpha = weight / (old_weight + weight)
                self.points[i]['x'] = old_x + alpha * (new_x - old_x)
                self.points[i]['y'] = old_y + alpha * (new_y - old_y)
                self.points[i]['weight'] += weight
        
        self._compute_velocities()
    
    def _resample_track(self, track_df, target_length):
        """Resample track to target length"""
        current_length = len(track_df)
        indices = np.linspace(0, current_length - 1, target_length)
        
        points = []
        for idx in indices:
            i = int(idx)
            frac = idx - i
            
            if i >= current_length - 1:
                points.append((track_df.iloc[-1]['CorrX'], track_df.iloc[-1]['CorrY']))
            else:
                x = (1 - frac) * track_df.iloc[i]['CorrX'] + frac * track_df.iloc[i+1]['CorrX']
                y = (1 - frac) * track_df.iloc[i]['CorrY'] + frac * track_df.iloc[i+1]['CorrY']
                points.append((x, y))
        
        return points
    
    def find_nearest_point(self, x, y):
        """Find index of nearest point on template to given position"""
        min_dist = float('inf')
        min_idx = 0
        
        for i, pt in enumerate(self.points):
            dist = np.sqrt((pt['x'] - x)**2 + (pt['y'] - y)**2)
            if dist < min_dist:
                min_dist = dist
                min_idx = i
        
        return min_idx, min_dist
    
    def lateral_distance(self, idx, x, y):
        """Calculate perpendicular distance from point to path at given index"""
        if idx >= len(self.points) - 1:
            idx = len(self.points) - 2
        
        # Line segment from points[idx] to points[idx+1]
        p1 = self.points[idx]
        p2 = self.points[idx + 1]
        
        # Vector along path
        dx = p2['x'] - p1['x']
        dy = p2['y'] - p1['y']
        length = np.sqrt(dx**2 + dy**2)
        
        if length < 0.01:
            return np.sqrt((x - p1['x'])**2 + (y - p1['y'])**2)
        
        # Normalized perpendicular vector
        perp_x = -dy / length
        perp_y = dx / length
        
        # Distance to point
        to_point_x = x - p1['x']
        to_point_y = y - p1['y']
        
        # Perpendicular distance
        lateral = abs(to_point_x * perp_x + to_point_y * perp_y)
        
        return lateral
    
    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            'template_id': self.template_id,
            'confidence': self.confidence,
            'samples': self.samples,
            'gate_sequence': self.gate_sequence,
            'points': self.points,
            'created': self.created,
            'last_seen': self.last_seen
        }
    
    @staticmethod
    def from_dict(data):
        """Create PathTemplate from dictionary"""
        template = PathTemplate.__new__(PathTemplate)
        template.template_id = data['template_id']
        template.confidence = data['confidence']
        template.samples = data['samples']
        template.gate_sequence = data['gate_sequence']
        template.points = data['points']
        template.created = data['created']
        template.last_seen = data['last_seen']
        return template


def load_path_templates(filepath):
    """Load existing path templates from JSON file"""
    if not os.path.exists(filepath):
        return {
            'intersection_id': 'intersection',
            'last_updated': datetime.now().isoformat(),
            'path_templates': [],
            'statistics': {
                'total_tracks_analyzed': 0,
                'high_confidence_tracks': 0
            }
        }
    
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Convert template dicts back to PathTemplate objects
        templates = []
        for t_dict in data.get('path_templates', []):
            templates.append(PathTemplate.from_dict(t_dict))
        
        data['path_templates'] = templates
        return data
    except:
        return load_path_templates.__wrapped__(filepath)  # Return empty if error


def save_path_templates(filepath, template_data):
    """Save path templates to JSON file"""
    # Convert PathTemplate objects to dicts
    save_data = template_data.copy()
    save_data['path_templates'] = [t.to_dict() for t in template_data['path_templates']]
    save_data['last_updated'] = datetime.now().isoformat()
    
    with open(filepath, 'w') as f:
        json.dump(save_data, f, indent=2)
    
    print(f"\n✓ Saved {len(template_data['path_templates'])} path templates to {filepath}")


# --- END PATH TEMPLATE SYSTEM ---


XML_FILE = "us95&sh8_iprj.txt"
DATA_FILE = "EVO_raw_data_1770177118.txt"
GATES_FILE = "gates.json"
TEMPLATES_FILE = "path_templates.json"  # Persistent path learning

# Tuning
COARSE_MATCH_DIST = 10.0   # Initial loose search radius for calibration
FINE_MATCH_DIST = 5.0      # Strict radius for final fusion matching
ISOLATION_RADIUS = 15.0    # "Clean data" must be this far from other cars
MIN_CALIB_POINTS = 10      # Need at least this many data points to build the bias map
SMOOTHING = 5.0            # RBF Smoothing factor (prevents overfitting to noise)

# Path Template Learning
LATERAL_BUFFER = 2.0       # meters - half a lane width
LOOKAHEAD_TIME = 5.0       # seconds - max time gap for path-based stitching
MIN_TEMPLATE_POINTS = 10   # Minimum points to create a template
MIN_TRACK_DURATION = 3.0   # seconds - minimum duration for high confidence

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
        
        # Extract sensor and direction from name
        if '_S' in name:
            # New format: N_S0, S_S1, etc.
            parts = name.split('_S')
            direction = parts[0] if len(parts) > 0 else ''
            sensor = int(parts[1]) if len(parts) > 1 else 0
        elif name.startswith('S') and '_' in name:
            # Old format: S0_Gate, S1_Gate
            sensor = int(name[1])
            direction = ''
        else:
            sensor = 0
            direction = ''
        
        p1 = (g['p1'][0], g['p1'][1])
        p2 = (g['p2'][0], g['p2'][1])
        
        gates.append({
            'name': name,
            'sensor': sensor,
            'direction': direction,
            'line': LineString([p1, p2]),
            'p1': p1,
            'p2': p2,
            'idx': idx  # Unique identifier
        })
        
        print(f"   [{idx}] {name} (S{sensor}, dir={direction or 'N/A'}): ({p1[0]:.1f}, {p1[1]:.1f}) -> ({p2[0]:.1f}, {p2[1]:.1f})")
    
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
        # Format: F;frame_id;?;?;?;objID,class,x,y,z,...;objID,class,x,y,z,...
        if line.startswith('F;'):
            parts = line.split(';')
            if len(parts) < 3:
                continue
                
            for ent in parts[4:]:  # Skip first 4 fields
                if not ent: continue
                p = ent.split(',')
                if len(p) < 4: continue
                
                try:
                    oid = int(p[0])
                    veh_class = int(p[1])  # Vehicle class
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
                        'Sensor': sensor_id,
                        'Class': veh_class  # Add vehicle class
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
    print(f"   Classes found: {sorted(df['Class'].unique())}")
    
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
    Check which gates a track crosses by checking ALL points along the track.
    A track crosses a gate if ANY point comes within GATE_BUFFER of the gate line.
    
    Returns crossings with gate INDEX (not name) to handle duplicate names.
    """
    GATE_BUFFER = 5.0  # meters - vehicles within this distance count as crossing
    
    crossings = []
    track_df = track_df.sort_values('Time').reset_index(drop=True)
    
    # Track which gates we've already counted for this track (by index, not name)
    gates_hit = set()
    
    for i in range(len(track_df)):
        x, y = track_df.iloc[i]['CorrX'], track_df.iloc[i]['CorrY']
        p = Point(x, y)
        
        for gate_idx, gate in enumerate(gates):
            gate_line = gate['line']
            dist = gate_line.distance(p)
            
            # If this point is within buffer of gate and we haven't counted this gate yet
            if dist <= GATE_BUFFER and gate_idx not in gates_hit:
                crossings.append({
                    'sensor': gate['sensor'],
                    'time': track_df.iloc[i]['Time'],
                    'gate_name': gate['name'],
                    'gate_idx': gate_idx  # Add unique identifier
                })
                gates_hit.add(gate_idx)
    
    return crossings

def stitch_same_sensor_tracks(df):
    """
    Stitch tracks from the SAME sensor that got dropped and re-acquired.
    This happens BEFORE spatial correction, using raw coordinates.
    
    Velocity-aware stitching:
    - If decelerating: search in circular area (30s window)
    - If constant velocity: shorter time window (5s) + directional cone
    """
    print("\n--- Stitching Same-Sensor Tracks ---")
    
    # Group by sensor and ID
    tracks = {}
    for (sensor, oid), group in df.groupby(['Sensor', 'ID']):
        track = group.sort_values('Time').reset_index(drop=True)
        if len(track) >= 2:
            tracks[(sensor, oid)] = track
    
    print(f"   Initial tracks: {len(tracks)}")
    
    # Parameters
    MAX_TIME_GAP_STOPPED = 30.0  # seconds for stopped/slow vehicles
    MAX_TIME_GAP_MOVING = 5.0    # seconds for moving vehicles
    MAX_SPATIAL_GAP_STOPPED = 20.0  # meters
    MAX_SPATIAL_GAP_MOVING = 30.0   # meters
    MIN_VELOCITY = 1.0  # m/s threshold for "moving"
    
    stitched = {}
    consumed = set()
    
    # Sort tracks by sensor for efficiency
    by_sensor = {}
    for key, track in tracks.items():
        sensor = key[0]
        if sensor not in by_sensor:
            by_sensor[sensor] = {}
        by_sensor[sensor][key] = track
    
    # Stitch within each sensor
    for sensor, sensor_tracks in by_sensor.items():
        for key1, track1 in sensor_tracks.items():
            if key1 in consumed:
                continue
            
            # Get end state
            end_time = track1['Time'].iloc[-1]
            end_x = track1['X'].iloc[-1]
            end_y = track1['Y'].iloc[-1]
            
            # Calculate velocity at end (last 3 points if available)
            if len(track1) >= 3:
                t_span = track1['Time'].iloc[-1] - track1['Time'].iloc[-3]
                if t_span > 0:
                    dx = track1['X'].iloc[-1] - track1['X'].iloc[-3]
                    dy = track1['Y'].iloc[-1] - track1['Y'].iloc[-3]
                    velocity = np.sqrt(dx**2 + dy**2) / t_span
                    direction = np.arctan2(dy, dx)  # radians
                else:
                    velocity = 0
                    direction = 0
            else:
                velocity = 0
                direction = 0
            
            is_moving = velocity > MIN_VELOCITY
            
            # Find best candidate
            best_match = None
            best_score = float('inf')
            
            for key2, track2 in sensor_tracks.items():
                if key2 == key1 or key2 in consumed:
                    continue
                
                # Must be same sensor
                if key2[0] != key1[0]:
                    continue
                
                start_time = track2['Time'].iloc[0]
                start_x = track2['X'].iloc[0]
                start_y = track2['Y'].iloc[0]
                
                time_gap = start_time - end_time
                
                # Check time window based on velocity
                max_time = MAX_TIME_GAP_MOVING if is_moving else MAX_TIME_GAP_STOPPED
                if time_gap <= 0 or time_gap > max_time:
                    continue
                
                spatial_gap = np.sqrt((start_x - end_x)**2 + (start_y - end_y)**2)
                
                # For moving vehicles, check directional cone
                if is_moving:
                    # Direction to candidate
                    angle_to_candidate = np.arctan2(start_y - end_y, start_x - end_x)
                    angle_diff = abs(angle_to_candidate - direction)
                    # Normalize to [0, pi]
                    if angle_diff > np.pi:
                        angle_diff = 2 * np.pi - angle_diff
                    
                    # Must be within 60 degree cone
                    if angle_diff > np.pi / 3:
                        continue
                    
                    if spatial_gap > MAX_SPATIAL_GAP_MOVING:
                        continue
                else:
                    # Stationary: just check circular area
                    if spatial_gap > MAX_SPATIAL_GAP_STOPPED:
                        continue
                
                # Score: prefer closer in both time and space
                score = time_gap + spatial_gap
                if score < best_score:
                    best_score = score
                    best_match = key2
            
            if best_match:
                track2 = sensor_tracks[best_match]
                
                # Stitch them
                combined = pd.concat([track1, track2]).sort_values('Time').reset_index(drop=True)
                
                # Create new key
                new_key = (key1[0], f"{key1[1]}_stitch_{best_match[1]}")
                stitched[new_key] = combined
                
                consumed.add(key1)
                consumed.add(best_match)
    
    # Keep unconsumed tracks
    for key, track in tracks.items():
        if key not in consumed:
            stitched[key] = track
    
    print(f"   After stitching: {len(stitched)} tracks")
    print(f"   Stitched {len(consumed) // 2} pairs")
    
    # Convert back to dataframe
    all_data = []
    for key, track in stitched.items():
        track_copy = track.copy()
        track_copy['ID'] = key[1]  # Update ID to stitched name
        all_data.append(track_copy)
    
    return pd.concat(all_data).reset_index(drop=True) if all_data else pd.DataFrame()


def build_path_templates(tracks, template_data, gates):
    """
    Build path templates from high-confidence tracks.
    
    High confidence criteria (tiered):
    1. Single sensor crossing 2+ gates (most confident)
    2. Multi-sensor fused in sparse traffic
    3. Single sensor with consistent velocity
    """
    print("\n--- Building Path Templates ---")
    
    existing_templates = template_data['path_templates']
    new_templates = []
    reinforced_count = 0
    
    print(f"   Loaded {len(existing_templates)} existing templates")
    
    # Identify high-confidence tracks
    high_conf_tracks = []
    
    for key, track_info in tracks.items():
        df = track_info['df']
        track_type = track_info['type']
        num_gates = track_info['num_gates']
        
        # Duration check
        duration = df['Time'].max() - df['Time'].min()
        if duration < MIN_TRACK_DURATION:
            continue
        
        # Velocity consistency check
        if len(df) >= 10:
            velocities = []
            for i in range(len(df) - 1):
                dx = df.iloc[i+1]['CorrX'] - df.iloc[i]['CorrX']
                dy = df.iloc[i+1]['CorrY'] - df.iloc[i]['CorrY']
                dt = df.iloc[i+1]['Time'] - df.iloc[i]['Time']
                if dt > 0:
                    velocities.append(np.sqrt(dx**2 + dy**2) / dt)
            
            if velocities:
                velocity_std = np.std(velocities)
                velocity_mean = np.mean(velocities)
                if velocity_mean > 0:
                    velocity_cv = velocity_std / velocity_mean  # Coefficient of variation
                else:
                    velocity_cv = 999
            else:
                velocity_cv = 999
        else:
            velocity_cv = 999
        
        # Tier 1: Valid internal (crosses 2+ same-sensor gates)
        if track_type == 'valid_internal' and num_gates >= 2:
            confidence = 0.95
            tier = 1
        # Tier 2: Fused tracks in sparse traffic
        elif track_type == 'transition' and num_gates >= 2 and velocity_cv < 0.3:
            confidence = 0.85
            tier = 2
        # Tier 3: Consistent velocity single sensor
        elif track_type == 'valid_internal' and velocity_cv < 0.2:
            confidence = 0.75
            tier = 3
        else:
            continue
        
        # Gate sequence
        gate_sequence = [c['gate_name'] for c in track_info['crossings']]
        gate_sequence = list(dict.fromkeys(gate_sequence))  # Remove duplicates, preserve order
        
        high_conf_tracks.append({
            'key': key,
            'df': df,
            'gate_sequence': gate_sequence,
            'confidence': confidence,
            'tier': tier
        })
    
    print(f"   Found {len(high_conf_tracks)} high-confidence tracks")
    
    # Match to existing templates or create new ones
    for hc_track in high_conf_tracks:
        matched = False
        
        # Try to match to existing template
        for template in existing_templates:
            # Must have same gate sequence
            if template.gate_sequence == hc_track['gate_sequence']:
                # Check if track follows this path
                start_x = hc_track['df'].iloc[0]['CorrX']
                start_y = hc_track['df'].iloc[0]['CorrY']
                
                nearest_idx, dist = template.find_nearest_point(start_x, start_y)
                
                if dist < 10.0:  # Within 10m of template start
                    # Add track to template
                    template.add_track(hc_track['df'], weight=hc_track['confidence'])
                    matched = True
                    reinforced_count += 1
                    break
        
        # Create new template if no match
        if not matched and len(hc_track['df']) >= MIN_TEMPLATE_POINTS:
            template_id = f"path_{len(existing_templates) + len(new_templates):03d}"
            new_template = PathTemplate(
                template_id,
                hc_track['gate_sequence'],
                hc_track['df'],
                confidence=hc_track['confidence']
            )
            new_templates.append(new_template)
    
    # Update template data
    template_data['path_templates'].extend(new_templates)
    template_data['statistics']['total_tracks_analyzed'] += len(tracks)
    template_data['statistics']['high_confidence_tracks'] += len(high_conf_tracks)
    
    print(f"   Reinforced {reinforced_count} existing templates")
    print(f"   Created {len(new_templates)} new templates")
    print(f"   Total templates: {len(template_data['path_templates'])}")
    
    return template_data


def stitch_with_path_templates(df, templates):
    """
    Stitch orphan tracks using learned path templates.
    Much more accurate than brute-force spatial matching.
    """
    if not templates:
        print("\n   No path templates available for stitching")
        return df
    
    print("\n--- Path-Based Stitching ---")
    print(f"   Using {len(templates)} path templates")
    
    # Group tracks
    tracks = {}
    for (sensor, oid), group in df.groupby(['Sensor', 'ID']):
        track = group.sort_values('Time').reset_index(drop=True)
        if len(track) >= 2:
            tracks[(sensor, oid)] = track
    
    stitched = {}
    consumed = set()
    stitch_count = 0
    
    # For each track, try to match to templates
    for key1, track1 in tracks.items():
        if key1 in consumed:
            continue
        
        end_time = track1['Time'].iloc[-1]
        end_x = track1['CorrX'].iloc[-1]
        end_y = track1['CorrY'].iloc[-1]
        
        # Calculate end velocity
        if len(track1) >= 3:
            t_span = track1['Time'].iloc[-1] - track1['Time'].iloc[-3]
            if t_span > 0:
                dx = track1['CorrX'].iloc[-1] - track1['CorrX'].iloc[-3]
                dy = track1['CorrY'].iloc[-1] - track1['CorrY'].iloc[-3]
                velocity = np.sqrt(dx**2 + dy**2) / t_span
            else:
                velocity = 5.0  # Default
        else:
            velocity = 5.0
        
        # Find matching template
        best_template = None
        best_template_idx = None
        best_lateral_dist = float('inf')
        
        for template in templates:
            nearest_idx, dist = template.find_nearest_point(end_x, end_y)
            lateral_dist = template.lateral_distance(nearest_idx, end_x, end_y)
            
            if lateral_dist < LATERAL_BUFFER and lateral_dist < best_lateral_dist:
                best_lateral_dist = lateral_dist
                best_template = template
                best_template_idx = nearest_idx
        
        if best_template is None:
            continue
        
        # Search forward along template for matching orphan
        lookahead_dist = velocity * LOOKAHEAD_TIME
        
        best_match = None
        best_match_score = float('inf')
        
        for key2, track2 in tracks.items():
            if key2 == key1 or key2 in consumed:
                continue
            
            start_time = track2['Time'].iloc[0]
            time_gap = start_time - end_time
            
            if time_gap <= 0 or time_gap > LOOKAHEAD_TIME:
                continue
            
            start_x = track2['CorrX'].iloc[0]
            start_y = track2['CorrY'].iloc[0]
            
            # Check if start point is along the template path
            nearest_idx2, dist2 = best_template.find_nearest_point(start_x, start_y)
            
            # Must be ahead on the path
            if nearest_idx2 <= best_template_idx:
                continue
            
            lateral_dist2 = best_template.lateral_distance(nearest_idx2, start_x, start_y)
            
            if lateral_dist2 < LATERAL_BUFFER:
                # Calculate distance along path
                path_dist = 0
                for i in range(best_template_idx, nearest_idx2):
                    if i < len(best_template.points) - 1:
                        dx = best_template.points[i+1]['x'] - best_template.points[i]['x']
                        dy = best_template.points[i+1]['y'] - best_template.points[i]['y']
                        path_dist += np.sqrt(dx**2 + dy**2)
                
                if path_dist < lookahead_dist:
                    score = time_gap + lateral_dist2 + (path_dist / lookahead_dist)
                    if score < best_match_score:
                        best_match_score = score
                        best_match = key2
        
        if best_match:
            track2 = tracks[best_match]
            combined = pd.concat([track1, track2]).sort_values('Time').reset_index(drop=True)
            
            new_key = (key1[0], f"{key1[1]}_path_{best_match[1]}")
            stitched[new_key] = combined
            
            consumed.add(key1)
            consumed.add(best_match)
            stitch_count += 1
    
    # Keep unconsumed tracks
    for key, track in tracks.items():
        if key not in consumed:
            stitched[key] = track
    
    print(f"   Path-stitched {stitch_count} pairs")
    print(f"   Final track count: {len(stitched)}")
    
    # Convert back to dataframe
    all_data = []
    for key, track in stitched.items():
        track_copy = track.copy()
        track_copy['ID'] = key[1]
        all_data.append(track_copy)
    
    return pd.concat(all_data).reset_index(drop=True) if all_data else pd.DataFrame()


    """
    Stitch tracks from the SAME sensor that got dropped and re-acquired.
    This happens BEFORE spatial correction, using raw coordinates.
    
    Velocity-aware stitching:
    - If decelerating: search in circular area (30s window)
    - If constant velocity: shorter time window (5s) + directional cone
    """
    print("\n--- Stitching Same-Sensor Tracks ---")
    
    # Group by sensor and ID
    tracks = {}
    for (sensor, oid), group in df.groupby(['Sensor', 'ID']):
        track = group.sort_values('Time').reset_index(drop=True)
        if len(track) >= 2:
            tracks[(sensor, oid)] = track
    
    print(f"   Initial tracks: {len(tracks)}")
    
    # Parameters
    MAX_TIME_GAP_STOPPED = 30.0  # seconds for stopped/slow vehicles
    MAX_TIME_GAP_MOVING = 5.0    # seconds for moving vehicles
    MAX_SPATIAL_GAP_STOPPED = 20.0  # meters
    MAX_SPATIAL_GAP_MOVING = 30.0   # meters
    MIN_VELOCITY = 1.0  # m/s threshold for "moving"
    
    stitched = {}
    consumed = set()
    
    # Sort tracks by sensor for efficiency
    by_sensor = {}
    for key, track in tracks.items():
        sensor = key[0]
        if sensor not in by_sensor:
            by_sensor[sensor] = {}
        by_sensor[sensor][key] = track
    
    # Stitch within each sensor
    for sensor, sensor_tracks in by_sensor.items():
        for key1, track1 in sensor_tracks.items():
            if key1 in consumed:
                continue
            
            # Get end state
            end_time = track1['Time'].iloc[-1]
            end_x = track1['X'].iloc[-1]
            end_y = track1['Y'].iloc[-1]
            
            # Calculate velocity at end (last 3 points if available)
            if len(track1) >= 3:
                t_span = track1['Time'].iloc[-1] - track1['Time'].iloc[-3]
                if t_span > 0:
                    dx = track1['X'].iloc[-1] - track1['X'].iloc[-3]
                    dy = track1['Y'].iloc[-1] - track1['Y'].iloc[-3]
                    velocity = np.sqrt(dx**2 + dy**2) / t_span
                    direction = np.arctan2(dy, dx)  # radians
                else:
                    velocity = 0
                    direction = 0
            else:
                velocity = 0
                direction = 0
            
            is_moving = velocity > MIN_VELOCITY
            
            # Find best candidate
            best_match = None
            best_score = float('inf')
            
            for key2, track2 in sensor_tracks.items():
                if key2 == key1 or key2 in consumed:
                    continue
                
                # Must be same sensor
                if key2[0] != key1[0]:
                    continue
                
                start_time = track2['Time'].iloc[0]
                start_x = track2['X'].iloc[0]
                start_y = track2['Y'].iloc[0]
                
                time_gap = start_time - end_time
                
                # Check time window based on velocity
                max_time = MAX_TIME_GAP_MOVING if is_moving else MAX_TIME_GAP_STOPPED
                if time_gap <= 0 or time_gap > max_time:
                    continue
                
                spatial_gap = np.sqrt((start_x - end_x)**2 + (start_y - end_y)**2)
                
                # For moving vehicles, check directional cone
                if is_moving:
                    # Direction to candidate
                    angle_to_candidate = np.arctan2(start_y - end_y, start_x - end_x)
                    angle_diff = abs(angle_to_candidate - direction)
                    # Normalize to [0, pi]
                    if angle_diff > np.pi:
                        angle_diff = 2 * np.pi - angle_diff
                    
                    # Must be within 60 degree cone
                    if angle_diff > np.pi / 3:
                        continue
                    
                    if spatial_gap > MAX_SPATIAL_GAP_MOVING:
                        continue
                else:
                    # Stationary: just check circular area
                    if spatial_gap > MAX_SPATIAL_GAP_STOPPED:
                        continue
                
                # Score: prefer closer in both time and space
                score = time_gap + spatial_gap
                if score < best_score:
                    best_score = score
                    best_match = key2
            
            if best_match:
                track2 = sensor_tracks[best_match]
                
                # Stitch them
                combined = pd.concat([track1, track2]).sort_values('Time').reset_index(drop=True)
                
                # Create new key
                new_key = (key1[0], f"{key1[1]}_stitch_{best_match[1]}")
                stitched[new_key] = combined
                
                consumed.add(key1)
                consumed.add(best_match)
    
    # Keep unconsumed tracks
    for key, track in tracks.items():
        if key not in consumed:
            stitched[key] = track
    
    print(f"   After stitching: {len(stitched)} tracks")
    print(f"   Stitched {len(consumed) // 2} pairs")
    
    # Convert back to dataframe
    all_data = []
    for key, track in stitched.items():
        track_copy = track.copy()
        track_copy['ID'] = key[1]  # Update ID to stitched name
        all_data.append(track_copy)
    
    return pd.concat(all_data).reset_index(drop=True) if all_data else pd.DataFrame()
    """
    Try to connect fragment tracks that are likely the same object.
    Look for fragments where one ends and another begins nearby in space and time.
    """
    print("\n--- Stitching Fragment Tracks ---")
    
    fragments = {k: v for k, v in tracks.items() if v['type'] == 'fragment'}
    stitched_count = 0
    
    if not fragments:
        print("   No fragments to stitch")
        return tracks
    
    print(f"   Processing {len(fragments)} fragments...")
    
    # Parameters for stitching
    MAX_TIME_GAP = 2.0  # seconds
    MAX_SPATIAL_GAP = 15.0  # meters
    
    stitched = {}
    consumed = set()
    
    for key1, frag1 in fragments.items():
        if key1 in consumed:
            continue
            
        df1 = frag1['df']
        end_time = df1['Time'].max()
        end_x = df1[df1['Time'] == end_time]['CorrX'].values[0]
        end_y = df1[df1['Time'] == end_time]['CorrY'].values[0]
        
        # Look for a fragment that starts shortly after this one ends
        best_match = None
        best_score = float('inf')
        
        for key2, frag2 in fragments.items():
            if key2 == key1 or key2 in consumed:
                continue
            
            df2 = frag2['df']
            start_time = df2['Time'].min()
            start_x = df2[df2['Time'] == start_time]['CorrX'].values[0]
            start_y = df2[df2['Time'] == start_time]['CorrY'].values[0]
            
            time_gap = start_time - end_time
            spatial_gap = np.sqrt((start_x - end_x)**2 + (start_y - end_y)**2)
            
            if 0 < time_gap < MAX_TIME_GAP and spatial_gap < MAX_SPATIAL_GAP:
                # Score: prefer closer in both time and space
                score = time_gap + spatial_gap
                if score < best_score:
                    best_score = score
                    best_match = (key2, frag2)
        
        if best_match:
            key2, frag2 = best_match
            
            # Stitch them together
            df_combined = pd.concat([df1, frag2['df']]).sort_values('Time').reset_index(drop=True)
            
            # Use the tracking sensor from the first fragment
            tracking_sensor = key1[0]
            
            # Re-check gate crossings for the combined track
            crossings = check_gate_crossings(df_combined, gates)
            gates_crossed = set((c['sensor'], c['gate_name']) for c in crossings)
            sensors_crossed = set(c['sensor'] for c in crossings)
            num_gates = len(gates_crossed)
            
            # Reclassify with sensor matching logic
            track_type = 'fragment'
            if num_gates >= 2:
                if len(sensors_crossed) == 1:
                    gate_sensor = list(sensors_crossed)[0]
                    if gate_sensor == tracking_sensor:
                        track_type = 'valid_internal'
                    else:
                        track_type = 'transition'
                else:
                    track_type = 'transition'
            elif num_gates == 1:
                gate_sensor = list(sensors_crossed)[0] if sensors_crossed else None
                if gate_sensor == tracking_sensor:
                    track_type = 'fragment'
                else:
                    track_type = 'transition'
            
            # Create stitched track
            stitched_key = (tracking_sensor, f"{key1[1]}_stitched_{key2[1]}")
            stitched[stitched_key] = {
                'df': df_combined,
                'type': track_type,
                'crossings': crossings,
                'gates_crossed': gates_crossed,
                'sensors_crossed': sensors_crossed,
                'num_gates': num_gates,
                'tracking_sensor': tracking_sensor
            }
            
            consumed.add(key1)
            consumed.add(key2)
            stitched_count += 1
    
    # Update tracks: remove consumed fragments, add stitched tracks
    new_tracks = {k: v for k, v in tracks.items() if k not in consumed}
    new_tracks.update(stitched)
    
    print(f"   Stitched {stitched_count} fragment pairs")
    print(f"   Remaining fragments: {sum(1 for t in new_tracks.values() if t['type'] == 'fragment')}")
    
    return new_tracks

def determine_track_class(track_df):
    """
    Determine the class of a track.
    If >10% of points are pedestrian (class 10), classify as pedestrian.
    Otherwise use the most common class.
    """
    if 'Class' not in track_df.columns:
        return 30  # Default to car
    
    total_points = len(track_df)
    ped_points = (track_df['Class'] == 10).sum()
    
    if ped_points / total_points > 0.1:
        return 10  # Pedestrian
    
    # Otherwise use mode
    mode_class = track_df['Class'].mode()
    if len(mode_class) > 0:
        return mode_class[0]
    return track_df['Class'].iloc[0]

def classify_tracks_by_gates(df, gates):
    """
    Classify each track based on gate crossings:
    - 'valid_internal': crosses 2+ gates from SAME sensor AND tracking sensor matches gate sensor
    - 'transition': crosses gates from DIFFERENT sensors OR tracking sensor doesn't match gate sensor
    - 'fragment': crosses only 1 gate (keep for handoff matching, don't discard)
    """
    print("\n--- Classifying Tracks by Gate Crossings ---")
    print(f"   Gates in map coordinates:")
    for gate in gates:
        print(f"      {gate['name']} (S{gate['sensor']}): ({gate['p1'][0]:.1f}, {gate['p1'][1]:.1f}) -> ({gate['p2'][0]:.1f}, {gate['p2'][1]:.1f})")
    
    # Show data range
    print(f"\n   Track data range:")
    print(f"      X: {df['CorrX'].min():.1f} to {df['CorrX'].max():.1f}")
    print(f"      Y: {df['CorrY'].min():.1f} to {df['CorrY'].max():.1f}")
    
    # Check if any tracks are even near the gates
    gate_x_min = min(min(g['p1'][0], g['p2'][0]) for g in gates)
    gate_x_max = max(max(g['p1'][0], g['p2'][0]) for g in gates)
    gate_y_min = min(min(g['p1'][1], g['p2'][1]) for g in gates)
    gate_y_max = max(max(g['p1'][1], g['p2'][1]) for g in gates)
    
    print(f"\n   Gate bounding box:")
    print(f"      X: {gate_x_min:.1f} to {gate_x_max:.1f}")
    print(f"      Y: {gate_y_min:.1f} to {gate_y_max:.1f}")
    
    # Count tracks near gates
    near_gates = df[
        (df['CorrX'] >= gate_x_min - 50) & (df['CorrX'] <= gate_x_max + 50) &
        (df['CorrY'] >= gate_y_min - 50) & (df['CorrY'] <= gate_y_max + 50)
    ]
    print(f"\n   Track points within 50m of gates: {len(near_gates)} / {len(df)} ({100*len(near_gates)/len(df):.1f}%)")
    
    tracks = {}
    sample_debug_count = 0
    
    for (sensor, oid), group in df.groupby(['Sensor', 'ID']):
        track = group.sort_values('Time').reset_index(drop=True)
        
        # Skip very short tracks
        if len(track) < 2:
            continue
            
        crossings = check_gate_crossings(track, gates)
        
        # Count unique gates crossed using gate_idx (handles duplicate names)
        gates_crossed = set((c['gate_idx'], c['gate_name']) for c in crossings)
        sensors_crossed = set(c['sensor'] for c in crossings)
        num_gates = len(gates_crossed)
        
        # Debug first few tracks that cross 2+ gates
        if num_gates >= 2 and sample_debug_count < 3:
            print(f"\n   DEBUG Track S{sensor}#{oid}:")
            print(f"      Crossed {num_gates} gates: {[c['gate_name'] + '(idx=' + str(c['gate_idx']) + ')' for c in crossings]}")
            print(f"      Gate sensors: {sensors_crossed}")
            print(f"      Tracking sensor: {sensor}")
            sample_debug_count += 1
        
        # Classify based on:
        # 1. How many gates crossed
        # 2. Whether gate sensors match tracking sensor
        # 3. Whether multiple gate sensors involved
        
        track_type = 'fragment'  # Default
        
        if num_gates >= 2:
            # Check if all gates belong to the same sensor
            if len(sensors_crossed) == 1:
                gate_sensor = list(sensors_crossed)[0]
                
                # Valid internal: tracking sensor matches gate sensor
                if gate_sensor == sensor:
                    track_type = 'valid_internal'
                    if sample_debug_count < 5:
                        print(f"      → VALID INTERNAL (S{sensor} tracking S{gate_sensor} gates)")
                else:
                    # Sensor mismatch: S1 tracking across S0 gates = redundant/transition
                    track_type = 'transition'
                    if sample_debug_count < 5:
                        print(f"      → TRANSITION (S{sensor} tracking S{gate_sensor} gates - mismatch)")
            else:
                # Crosses gates from different sensors = transition
                track_type = 'transition'
                if sample_debug_count < 5:
                    print(f"      → TRANSITION (crosses multiple sensor gates: {sensors_crossed})")
        elif num_gates == 1:
            # Single gate crossing
            gate_sensor = list(sensors_crossed)[0] if sensors_crossed else None
            
            if gate_sensor == sensor:
                # Same sensor: keep as fragment for handoff matching
                track_type = 'fragment'
            else:
                # Different sensor: this is a transition candidate
                track_type = 'transition'
        # else: num_gates == 0, remains 'fragment'
        
        tracks[(sensor, oid)] = {
            'df': track,
            'type': track_type,
            'crossings': crossings,
            'gates_crossed': gates_crossed,
            'sensors_crossed': sensors_crossed,
            'num_gates': num_gates,
            'tracking_sensor': sensor
        }
    
    print(f"\n   Total tracks processed: {len(tracks)}")
    
    valid_count = sum(1 for t in tracks.values() if t['type'] == 'valid_internal')
    transition_count = sum(1 for t in tracks.values() if t['type'] == 'transition')
    fragment_count = sum(1 for t in tracks.values() if t['type'] == 'fragment')
    
    print(f"   Valid internal tracks: {valid_count}")
    print(f"   Transition tracks (need fusion): {transition_count}")
    print(f"   Fragments (for handoff matching): {fragment_count}")
    
    return tracks
    """
    Classify each track based on gate crossings:
    - 'valid_internal': crosses 2+ gates from SAME sensor AND tracking sensor matches gate sensor
    - 'transition': crosses gates from DIFFERENT sensors OR tracking sensor doesn't match gate sensor
    - 'fragment': crosses only 1 gate (keep for handoff matching, don't discard)
    """
    print("\n--- Classifying Tracks by Gate Crossings ---")
    print(f"   Gates in map coordinates:")
    for gate in gates:
        print(f"      {gate['name']} (S{gate['sensor']}): ({gate['p1'][0]:.1f}, {gate['p1'][1]:.1f}) -> ({gate['p2'][0]:.1f}, {gate['p2'][1]:.1f})")
    
    # Show data range
    print(f"\n   Track data range:")
    print(f"      X: {df['CorrX'].min():.1f} to {df['CorrX'].max():.1f}")
    print(f"      Y: {df['CorrY'].min():.1f} to {df['CorrY'].max():.1f}")
    
    # Check if any tracks are even near the gates
    gate_x_min = min(min(g['p1'][0], g['p2'][0]) for g in gates)
    gate_x_max = max(max(g['p1'][0], g['p2'][0]) for g in gates)
    gate_y_min = min(min(g['p1'][1], g['p2'][1]) for g in gates)
    gate_y_max = max(max(g['p1'][1], g['p2'][1]) for g in gates)
    
    print(f"\n   Gate bounding box:")
    print(f"      X: {gate_x_min:.1f} to {gate_x_max:.1f}")
    print(f"      Y: {gate_y_min:.1f} to {gate_y_max:.1f}")
    
    # Count tracks near gates
    near_gates = df[
        (df['CorrX'] >= gate_x_min - 50) & (df['CorrX'] <= gate_x_max + 50) &
        (df['CorrY'] >= gate_y_min - 50) & (df['CorrY'] <= gate_y_max + 50)
    ]
    print(f"\n   Track points within 50m of gates: {len(near_gates)} / {len(df)} ({100*len(near_gates)/len(df):.1f}%)")
    
    if len(near_gates) < len(df) * 0.01:
        print("\n   ⚠️ WARNING: Less than 1% of track data is near gates!")
        print("   This suggests a coordinate system mismatch.")
        print("   Tracks might need Y-axis transformation to match gate coordinates.")
    
    tracks = {}
    
    for (sensor, oid), group in df.groupby(['Sensor', 'ID']):
        track = group.sort_values('Time').reset_index(drop=True)
        
        # Skip very short tracks
        if len(track) < 2:
            continue
            
        crossings = check_gate_crossings(track, gates)
        
        # Count unique gates crossed
        gates_crossed = set((c['sensor'], c['gate_name']) for c in crossings)
        sensors_crossed = set(c['sensor'] for c in crossings)
        num_gates = len(gates_crossed)
        
        # Classify based on:
        # 1. How many gates crossed
        # 2. Whether gate sensors match tracking sensor
        # 3. Whether multiple gate sensors involved
        
        track_type = 'fragment'  # Default
        
        if num_gates >= 2:
            # Check if all gates belong to the same sensor
            if len(sensors_crossed) == 1:
                gate_sensor = list(sensors_crossed)[0]
                
                # Valid internal: tracking sensor matches gate sensor
                if gate_sensor == sensor:
                    track_type = 'valid_internal'
                else:
                    # Sensor mismatch: S1 tracking across S0 gates = redundant/transition
                    track_type = 'transition'
            else:
                # Crosses gates from different sensors = transition
                track_type = 'transition'
        elif num_gates == 1:
            # Single gate crossing
            gate_sensor = list(sensors_crossed)[0] if sensors_crossed else None
            
            if gate_sensor == sensor:
                # Same sensor: keep as fragment for handoff matching
                track_type = 'fragment'
            else:
                # Different sensor: this is a transition candidate
                track_type = 'transition'
        # else: num_gates == 0, remains 'fragment'
        
        tracks[(sensor, oid)] = {
            'df': track,
            'type': track_type,
            'crossings': crossings,
            'gates_crossed': gates_crossed,
            'sensors_crossed': sensors_crossed,
            'num_gates': num_gates,
            'tracking_sensor': sensor
        }
    
    print(f"\n   Total tracks processed: {len(tracks)}")
    
    valid_count = sum(1 for t in tracks.values() if t['type'] == 'valid_internal')
    transition_count = sum(1 for t in tracks.values() if t['type'] == 'transition')
    fragment_count = sum(1 for t in tracks.values() if t['type'] == 'fragment')
    
    print(f"   Valid internal tracks: {valid_count}")
    print(f"   Transition tracks (need fusion): {transition_count}")
    print(f"   Fragments (for handoff matching): {fragment_count}")
    
    return tracks

def fuse_tracks_with_gates(tracks):
    """
    Fuse tracks based on gate-crossing logic with optimized matching.
    
    Optimizations:
    - Pre-filter by time overlap before distance calculations
    - Skip obviously incompatible class combinations early
    - Use bounding boxes for quick spatial filtering
    """
    print("\n--- Fusing Transition Tracks ---")
    
    valid_internal = {k: v for k, v in tracks.items() if v['type'] == 'valid_internal'}
    transition_tracks = {k: v for k, v in tracks.items() if v['type'] == 'transition'}
    fragments = {k: v for k, v in tracks.items() if v['type'] == 'fragment'}
    
    print(f"   Valid internal: {len(valid_internal)}")
    print(f"   Transitions (need fusion/discard): {len(transition_tracks)}")
    print(f"   Fragments (for handoff): {len(fragments)}")
    
    # Helper function to check if two vehicle classes are compatible for fusion
    def classes_compatible(class1, class2):
        """
        Pedestrians (10) and bicycles (~15?) should not fuse with motor vehicles (30+).
        Motor vehicles can fuse with each other.
        """
        # Define class categories
        NON_MOTORIZED = [10, 15, 20]  # pedestrian, bicycle, etc.
        MOTORIZED_THRESHOLD = 25  # anything >= 30 is a motor vehicle
        
        is_non_motor1 = class1 in NON_MOTORIZED or class1 < MOTORIZED_THRESHOLD
        is_non_motor2 = class2 in NON_MOTORIZED or class2 < MOTORIZED_THRESHOLD
        
        # If one is non-motorized and the other is motorized, they're incompatible
        if is_non_motor1 != is_non_motor2:
            return False
        
        return True
    
    # Separate transitions into:
    # 1. Cross-sensor transitions (S0→S1 gates): need fusion
    # 2. Redundant tracks (S1 tracking S0 gates): discard
    
    cross_sensor = {}
    redundant = {}
    
    for key, track in transition_tracks.items():
        tracking_sensor = track['tracking_sensor']
        sensors_in_gates = track['sensors_crossed']
        
        # If track crosses gates from different sensors, it's a genuine transition
        if len(sensors_in_gates) > 1:
            cross_sensor[key] = track
        else:
            # Only one gate sensor, but doesn't match tracking sensor
            gate_sensor = list(sensors_in_gates)[0] if sensors_in_gates else None
            if gate_sensor != tracking_sensor:
                # E.g., S1 tracking across S0 gates = redundant
                redundant[key] = track
            else:
                # This shouldn't happen based on classification, but keep it safe
                cross_sensor[key] = track
    
    print(f"   Cross-sensor transitions: {len(cross_sensor)}")
    print(f"   Redundant (will discard): {len(redundant)}")
    
    # Combine cross-sensor transitions and fragments for fusion matching
    fusion_candidates = {**cross_sensor, **fragments}
    
    # Pre-compute metadata for each track for faster matching
    track_metadata = {}
    for key, track in fusion_candidates.items():
        df = track['df']
        track_metadata[key] = {
            'sensor': key[0],
            'time_min': df['Time'].min(),
            'time_max': df['Time'].max(),
            'x_min': df['CorrX'].min(),
            'x_max': df['CorrX'].max(),
            'y_min': df['CorrY'].min(),
            'y_max': df['CorrY'].max(),
            'class': determine_track_class(df),
            'track': track
        }
    
    print(f"   Matching {len(fusion_candidates)} candidates...")
    
    matches = []
    consumed = set()
    match_count = 0
    
    # Match tracks that should be fused (handoffs between sensors)
    for key1, meta1 in track_metadata.items():
        if key1 in consumed:
            continue
        
        match_count += 1
        if match_count % 50 == 0:
            print(f"      Processed {match_count}/{len(fusion_candidates)} tracks...")
            
        sensor1 = meta1['sensor']
        df1 = meta1['track']['df']
        class1 = meta1['class']
        
        best_match = None
        best_overlap = 0
        
        # Look for matches in other sensors
        for key2, meta2 in track_metadata.items():
            if key2 in consumed or key2 == key1:
                continue
            
            sensor2 = meta2['sensor']
            if sensor1 == sensor2:  # Same sensor, skip
                continue
            
            # Quick temporal overlap check
            if meta1['time_max'] < meta2['time_min'] or meta2['time_max'] < meta1['time_min']:
                continue  # No temporal overlap
            
            # Quick spatial bounding box check (with 50m buffer)
            SPATIAL_BUFFER = 50.0
            if (meta1['x_max'] + SPATIAL_BUFFER < meta2['x_min'] or 
                meta2['x_max'] + SPATIAL_BUFFER < meta1['x_min'] or
                meta1['y_max'] + SPATIAL_BUFFER < meta2['y_min'] or
                meta2['y_max'] + SPATIAL_BUFFER < meta1['y_min']):
                continue  # No spatial overlap
            
            # Check class compatibility
            class2 = meta2['class']
            if not classes_compatible(class1, class2):
                continue
            
            df2 = meta2['track']['df']
            
            # Find temporal overlap
            common_times = np.intersect1d(df1['Time'].values, df2['Time'].values)
            if len(common_times) < 3:
                continue
            
            # Check spatial proximity using corrected coordinates
            subset1 = df1[df1['Time'].isin(common_times)].drop_duplicates('Time').sort_values('Time').reset_index(drop=True)
            subset2 = df2[df2['Time'].isin(common_times)].drop_duplicates('Time').sort_values('Time').reset_index(drop=True)
            
            # Ensure they have the same length after deduplication
            min_len = min(len(subset1), len(subset2))
            if min_len < 3:
                continue
            
            subset1 = subset1.iloc[:min_len]
            subset2 = subset2.iloc[:min_len]
            
            dists = np.sqrt((subset1['CorrX'].values - subset2['CorrX'].values)**2 + 
                           (subset1['CorrY'].values - subset2['CorrY'].values)**2)
            
            avg_dist = np.mean(dists)
            
            if avg_dist < FINE_MATCH_DIST and min_len > best_overlap:
                best_overlap = min_len
                best_match = (key2, meta2['track'], common_times, avg_dist)
        
        if best_match:
            key2, track2, common_times, avg_dist = best_match
            matches.append({
                'key1': key1,
                'key2': key2,
                'track1': meta1['track'],
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
                    'X': p1.iloc[0]['CorrX'],
                    'Y': p1.iloc[0]['CorrY'],
                    'Type': 'Fused',
                    'Hover': f"Fused {id1}→{id2} (S{s1})",
                    'ColorID': f"{id1}_{id2}"
                })
            elif p1.empty and not p2.empty:
                # After handoff - use second sensor
                fused_data.append({
                    'Time': t,
                    'X': p2.iloc[0]['CorrX'],
                    'Y': p2.iloc[0]['CorrY'],
                    'Type': 'Fused',
                    'Hover': f"Fused {id1}→{id2} (S{s2})",
                    'ColorID': f"{id1}_{id2}"
                })
            elif not p1.empty and not p2.empty:
                # Handoff zone - blend
                alpha = (t - overlap_start) / duration if duration > 0 else 0.5
                alpha = max(0.0, min(1.0, alpha))
                
                x = (1 - alpha) * p1.iloc[0]['CorrX'] + alpha * p2.iloc[0]['CorrX']
                y = (1 - alpha) * p1.iloc[0]['CorrY'] + alpha * p2.iloc[0]['CorrY']
                
                fused_data.append({
                    'Time': t,
                    'X': x,
                    'Y': y,
                    'Type': 'Fused',
                    'Hover': f"Handoff {alpha:.2f} ({id1}→{id2})",
                    'ColorID': f"{id1}_{id2}"
                })
    
    fused_df = pd.DataFrame(fused_data)
    
    # Keep only valid internal tracks
    internal_data = []
    
    for key, track in valid_internal.items():
        df = track['df'].copy()
        sensor, oid = key
        
        for _, row in df.iterrows():
            internal_data.append({
                'Time': row['Time'],
                'X': row['CorrX'],
                'Y': row['CorrY'],
                'Type': 'Valid Internal',
                'Hover': f"S{sensor} #{oid} (internal)",
                'ColorID': oid
            })
    
    internal_df = pd.DataFrame(internal_data)
    
    # Collect discarded tracks for visualization
    discarded_data = []
    
    # Add redundant tracks
    for key, track in redundant.items():
        df = track['df'].copy()
        sensor, oid = key
        for _, row in df.iterrows():
            discarded_data.append({
                'Time': row['Time'],
                'X': row['CorrX'],
                'Y': row['CorrY'],
                'Type': 'Discarded (Redundant)',
                'Hover': f"S{sensor} #{oid} (redundant)",
                'ColorID': oid
            })
    
    # Add unmatched fragments
    for key in fusion_candidates.keys():
        if key not in consumed and key in fragments:
            track = fragments[key]
            df = track['df'].copy()
            sensor, oid = key
            for _, row in df.iterrows():
                discarded_data.append({
                    'Time': row['Time'],
                    'X': row['CorrX'],
                    'Y': row['CorrY'],
                    'Type': 'Discarded (Fragment)',
                    'Hover': f"S{sensor} #{oid} (fragment)",
                    'ColorID': oid
                })
    
    # Add unmatched transitions
    for key in cross_sensor.keys():
        if key not in consumed:
            track = cross_sensor[key]
            df = track['df'].copy()
            sensor, oid = key
            for _, row in df.iterrows():
                discarded_data.append({
                    'Time': row['Time'],
                    'X': row['CorrX'],
                    'Y': row['CorrY'],
                    'Type': 'Discarded (Unmatched)',
                    'Hover': f"S{sensor} #{oid} (no match)",
                    'ColorID': oid
                })
    
    discarded_df = pd.DataFrame(discarded_data)
    
    # Count what we're discarding
    discarded_redundant = len(redundant)
    discarded_fragments = sum(1 for k in fusion_candidates.keys() if k not in consumed and k in fragments)
    discarded_unmatched = sum(1 for k in cross_sensor.keys() if k not in consumed)
    
    print(f"   Fused data points: {len(fused_df)}")
    print(f"   Valid internal data points: {len(internal_df)}")
    print(f"   Discarded data points: {len(discarded_df)}")
    print(f"   Discarded redundant tracks: {discarded_redundant}")
    print(f"   Discarded unmatched fragments: {discarded_fragments}")
    print(f"   Discarded unmatched transitions: {discarded_unmatched}")
    
    return fused_df, internal_df, discarded_df
    """
    Fuse tracks based on gate-crossing logic:
    - Valid internal tracks: keep as-is (S0 tracking across S0 gates)
    - Transition tracks: fuse across sensors OR discard if redundant
    - Fragments: use for handoff matching, then discard if unmatched
    
    Key insight: If S1 tracks across S0 gates, it's redundant (S0 should see it).
                 Only fuse when there's a legitimate handoff between sensor zones.
    
    Vehicle class compatibility:
    - Pedestrians (10) and bicycles should NEVER fuse with motor vehicles (30+)
    - Motor vehicles can fuse with each other (e.g., car↔truck is OK)
    """
    print("\n--- Fusing Transition Tracks ---")
    
    valid_internal = {k: v for k, v in tracks.items() if v['type'] == 'valid_internal'}
    transition_tracks = {k: v for k, v in tracks.items() if v['type'] == 'transition'}
    fragments = {k: v for k, v in tracks.items() if v['type'] == 'fragment'}
    
    print(f"   Valid internal: {len(valid_internal)}")
    print(f"   Transitions (need fusion/discard): {len(transition_tracks)}")
    print(f"   Fragments (for handoff): {len(fragments)}")
    
    # Helper function to check if two vehicle classes are compatible for fusion
    def classes_compatible(class1, class2):
        """
        Pedestrians (10) and bicycles (~15?) should not fuse with motor vehicles (30+).
        Motor vehicles can fuse with each other.
        """
        # Define class categories
        NON_MOTORIZED = [10, 15, 20]  # pedestrian, bicycle, etc.
        MOTORIZED_THRESHOLD = 25  # anything >= 30 is a motor vehicle
        
        is_non_motor1 = class1 in NON_MOTORIZED or class1 < MOTORIZED_THRESHOLD
        is_non_motor2 = class2 in NON_MOTORIZED or class2 < MOTORIZED_THRESHOLD
        
        # If one is non-motorized and the other is motorized, they're incompatible
        if is_non_motor1 != is_non_motor2:
            return False
        
        return True
    
    # Separate transitions into:
    # 1. Cross-sensor transitions (S0→S1 gates): need fusion
    # 2. Redundant tracks (S1 tracking S0 gates): discard
    
    cross_sensor = {}
    redundant = {}
    
    for key, track in transition_tracks.items():
        tracking_sensor = track['tracking_sensor']
        sensors_in_gates = track['sensors_crossed']
        
        # If track crosses gates from different sensors, it's a genuine transition
        if len(sensors_in_gates) > 1:
            cross_sensor[key] = track
        else:
            # Only one gate sensor, but doesn't match tracking sensor
            gate_sensor = list(sensors_in_gates)[0]
            if gate_sensor != tracking_sensor:
                # E.g., S1 tracking across S0 gates = redundant
                redundant[key] = track
            else:
                # This shouldn't happen based on classification, but keep it safe
                cross_sensor[key] = track
    
    print(f"   Cross-sensor transitions: {len(cross_sensor)}")
    print(f"   Redundant (will discard): {len(redundant)}")
    
    # Combine cross-sensor transitions and fragments for fusion matching
    fusion_candidates = {**cross_sensor, **fragments}
    
    matches = []
    consumed = set()
    
    # Match tracks that should be fused (handoffs between sensors)
    for key1, track1 in fusion_candidates.items():
        if key1 in consumed:
            continue
            
        sensor1, id1 = key1
        df1 = track1['df']
        
        # Get predominant class for track1
        class1 = df1['Class'].mode()[0] if len(df1['Class'].mode()) > 0 else df1['Class'].iloc[0]
        
        best_match = None
        best_overlap = 0
        
        # Look for matches in other sensors
        for key2, track2 in fusion_candidates.items():
            if key2 in consumed or key2 == key1:
                continue
                
            sensor2, id2 = key2
            if sensor1 == sensor2:  # Same sensor, skip
                continue
                
            df2 = track2['df']
            
            # Get predominant class for track2
            class2 = df2['Class'].mode()[0] if len(df2['Class'].mode()) > 0 else df2['Class'].iloc[0]
            
            # Check class compatibility
            if not classes_compatible(class1, class2):
                continue  # Skip this match - incompatible vehicle types
            
            # Find temporal overlap
            common_times = np.intersect1d(df1['Time'].values, df2['Time'].values)
            if len(common_times) < 3:
                continue
            
            # Check spatial proximity using corrected coordinates
            # Make sure to handle duplicates by taking only the first occurrence
            subset1 = df1[df1['Time'].isin(common_times)].drop_duplicates('Time').sort_values('Time').reset_index(drop=True)
            subset2 = df2[df2['Time'].isin(common_times)].drop_duplicates('Time').sort_values('Time').reset_index(drop=True)
            
            # Ensure they have the same length after deduplication
            min_len = min(len(subset1), len(subset2))
            if min_len < 3:
                continue
            
            subset1 = subset1.iloc[:min_len]
            subset2 = subset2.iloc[:min_len]
            
            dists = np.sqrt((subset1['CorrX'].values - subset2['CorrX'].values)**2 + 
                           (subset1['CorrY'].values - subset2['CorrY'].values)**2)
            
            avg_dist = np.mean(dists)
            
            if avg_dist < FINE_MATCH_DIST and min_len > best_overlap:
                best_overlap = min_len
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
                    'X': p1.iloc[0]['CorrX'],
                    'Y': p1.iloc[0]['CorrY'],
                    'Type': 'Fused',
                    'Hover': f"Fused {id1}→{id2} (S{s1})",
                    'ColorID': f"{id1}_{id2}"
                })
            elif p1.empty and not p2.empty:
                # After handoff - use second sensor
                fused_data.append({
                    'Time': t,
                    'X': p2.iloc[0]['CorrX'],
                    'Y': p2.iloc[0]['CorrY'],
                    'Type': 'Fused',
                    'Hover': f"Fused {id1}→{id2} (S{s2})",
                    'ColorID': f"{id1}_{id2}"
                })
            elif not p1.empty and not p2.empty:
                # Handoff zone - blend
                alpha = (t - overlap_start) / duration if duration > 0 else 0.5
                alpha = max(0.0, min(1.0, alpha))
                
                x = (1 - alpha) * p1.iloc[0]['CorrX'] + alpha * p2.iloc[0]['CorrX']
                y = (1 - alpha) * p1.iloc[0]['CorrY'] + alpha * p2.iloc[0]['CorrY']
                
                fused_data.append({
                    'Time': t,
                    'X': x,
                    'Y': y,
                    'Type': 'Fused',
                    'Hover': f"Handoff {alpha:.2f} ({id1}→{id2})",
                    'ColorID': f"{id1}_{id2}"
                })
    
    fused_df = pd.DataFrame(fused_data)
    
    # Keep only valid internal tracks
    internal_data = []
    
    for key, track in valid_internal.items():
        df = track['df'].copy()
        sensor, oid = key
        
        for _, row in df.iterrows():
            internal_data.append({
                'Time': row['Time'],
                'X': row['CorrX'],
                'Y': row['CorrY'],
                'Type': 'Valid Internal',
                'Hover': f"S{sensor} #{oid} (internal)",
                'ColorID': oid
            })
    
    internal_df = pd.DataFrame(internal_data)
    
    # Count what we're discarding
    discarded_redundant = len(redundant)
    discarded_fragments = sum(1 for k in fusion_candidates.keys() if k not in consumed and k in fragments)
    discarded_unmatched = sum(1 for k in cross_sensor.keys() if k not in consumed)
    
    print(f"   Fused data points: {len(fused_df)}")
    print(f"   Valid internal data points: {len(internal_df)}")
    print(f"   Discarded redundant tracks: {discarded_redundant}")
    print(f"   Discarded unmatched fragments: {discarded_fragments}")
    print(f"   Discarded unmatched transitions: {discarded_unmatched}")
    
    return fused_df, internal_df

def plot_final(fused, internal, discarded, map_config, bg_image, gates, templates=None):
    print("\n--- Plotting ---")
    
    print(f"   Input data:")
    print(f"      Fused: {len(fused)} points")
    print(f"      Internal: {len(internal)} points")
    print(f"      Discarded: {len(discarded)} points")
    if templates:
        print(f"      Path templates: {len(templates)}")
    
    # Helper to handle String IDs (from stitching) vs Integer IDs
    def get_color_index(val):
        try:
            return int(val) % 10
        except:
            return hash(str(val)) % 10

    # Assign colors and properties
    if not fused.empty:
        fused = fused.copy()
        fused['ColorVal'] = 'white'
        fused['MarkerSize'] = 10
    if not internal.empty:
        internal = internal.copy()
        # FIX: Handle string IDs safely
        internal['ColorVal'] = internal.apply(lambda r: 
            {0:'cyan', 1:'yellow', 2:'lime', 3:'magenta'}.get(get_color_index(r['ColorID']), 'gray'), axis=1)
        internal['MarkerSize'] = 8
    if not discarded.empty:
        discarded = discarded.copy()
        discarded['ColorVal'] = 'red'
        discarded['MarkerSize'] = 6
    
    # Combine data - put discarded first so valid tracks render on top
    df_list = []
    
    # OPTIONAL: Comment out this line if you want to HIDE the "Bouncing Balls" (Discarded Noise)
    # df_list.append(discarded) 
    
    if not internal.empty:
        df_list.append(internal)
    if not fused.empty:
        df_list.append(fused)
    
    if not df_list:
        print("   ERROR: No data to plot!")
        return
    
    df = pd.concat(df_list, ignore_index=True)
    df = df.sort_values('Time')
    
    print(f"\n   Combined dataframe: {len(df)} points")
    print(f"   Unique types: {df['Type'].unique()}")
    
    # Downsample for performance
    times = df['Time'].unique()
    sampled_times = times[::3]
    df_plot = df[df['Time'].isin(sampled_times)].copy()
    
    print(f"\n   After downsampling: {len(df_plot)} points across {len(df_plot['Time'].unique())} frames")
    for track_type in df_plot['Type'].unique():
        count = len(df_plot[df_plot['Type'] == track_type])
        print(f"      {track_type}: {count} points")
    
    fig = px.scatter(
        df_plot, 
        x='X', y='Y', 
        animation_frame='Time', 
        animation_group='Hover',
        color='ColorVal',
        size='MarkerSize',
        hover_name='Hover',
        color_discrete_map='identity',
        title="Gate-Based Fusion (White=Fused, Colored=Valid, Red=Discarded)"
    )
    
    fig.update_traces(marker=dict(line=dict(width=0.5, color='black'), opacity=0.7))
    
    # Handle potentially missing keys in map_config
    w = map_config.get('width', 1000) * map_config.get('scale', 0.1)
    h = map_config.get('height', 1000) * map_config.get('scale', 0.1)
    
    # Add gate lines
    for gate in gates:
        fig.add_shape(
            type="line",
            x0=gate['p1'][0], y0=gate['p1'][1],
            x1=gate['p2'][0], y1=gate['p2'][1],
            line=dict(color="lime" if gate['sensor'] == 1 else "orange", width=5),
            name=gate['name']
        )
        # Add text label
        fig.add_annotation(
            x=(gate['p1'][0] + gate['p2'][0])/2,
            y=(gate['p1'][1] + gate['p2'][1])/2,
            text=gate['name'],
            showarrow=False,
            font=dict(color="white", size=14, family="Arial Black"),
            bgcolor="rgba(0,0,0,0.7)"
        )
    
    # Add path templates as dashed lines
    if templates:
        for template in templates:
            x_coords = [pt['x'] for pt in template.points]
            y_coords = [pt['y'] for pt in template.points]
            
            # Add as a line trace (static, not animated)
            fig.add_trace(px.line(
                x=x_coords, y=y_coords
            ).data[0])
            
            # Style it
            fig.data[-1].line.color = 'rgba(100,200,255,0.5)'
            fig.data[-1].line.width = 2
            fig.data[-1].line.dash = 'dash'
            fig.data[-1].name = f"{template.template_id} ({template.samples} samples)"
            fig.data[-1].showlegend = False
    
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
    print("\n✓ Saved to fusion_gate_based.html")

if __name__ == "__main__":
    # Load configuration
    cfg, img = parse_xml_config(XML_FILE)
    gates = load_gates(GATES_FILE, cfg)
    
    # Load existing path templates
    template_data = load_path_templates(TEMPLATES_FILE)
    
    # Load and parse data
    df = parse_and_align_data(DATA_FILE, cfg)
    
    if df.empty:
        print("ERROR: No data loaded. Exiting.")
        exit(1)
    
    # 1. Stitch same-sensor tracks FIRST (velocity-aware, before spatial correction)
    df = stitch_same_sensor_tracks(df)
    
    # 2. Learn spatial bias correction
    models = train_spatial_bias_model(df)
    
    # 3. Apply correction to all data
    df_corr = apply_spatial_correction(df, models)
    
    # 4. Path-based stitching using learned templates (AFTER spatial correction)
    if template_data['path_templates']:
        df_corr = stitch_with_path_templates(df_corr, template_data['path_templates'])
    
    # 5. Classify tracks by gate crossings
    tracks = classify_tracks_by_gates(df_corr, gates)
    
    # 6. Build/update path templates from high-confidence tracks
    template_data = build_path_templates(tracks, template_data, gates)
    
    # 7. Save updated templates
    save_path_templates(TEMPLATES_FILE, template_data)
    
    # 8. Fuse transition tracks, keep valid internal, collect discarded
    fused, internal, discarded = fuse_tracks_with_gates(tracks)
    
    # 9. Visualize (including path templates and discarded for troubleshooting)
    plot_final(fused, internal, discarded, cfg, img, gates, template_data['path_templates'])