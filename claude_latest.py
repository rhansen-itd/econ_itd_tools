"""
RADAR FUSION SYSTEM - Multi-Sensor Track Fusion with Path Learning
====================================================================

This system fuses radar tracks from multiple sensors, learns common paths
through the intersection, and applies spatial bias correction.

INSTRUCTIONS:
1. Set your file paths and parameters below in the CONFIG section
2. Run the script: python fusion_improved.py
3. View results in the generated HTML files

Configuration files are automatically created/updated:
- path_templates.json: Learned trajectory paths
- spatial_models.json: Sensor bias correction models
"""

# ============================================================================
# USER CONFIGURATION - EDIT THESE VALUES
# ============================================================================

# --- INPUT FILES ---
INT_DIR = "./86_US95&SH8/"  # Directory containing input files
XML_FILE = INT_DIR + "us95&sh8_iprj.txt"       # EVO project configuration file
DATA_FILE = INT_DIR + "10_37_2_86_EVO_1770311735.txt"  # Raw radar detection data
GATES_FILE = INT_DIR + "gates.json"             # Gate definitions (drawn positions)

# --- OUTPUT FILES ---
OUTPUT_PREFIX = "fusion"              # Prefix for output files
TEMPLATES_FILE = "path_templates.json"  # Learned path templates
SPATIAL_MODEL_FILE = "spatial_models.json"  # Spatial bias correction

# --- PROCESSING MODES ---
# Options: 'use_only', 'augment', 'new', 'replace'
PATH_TEMPLATE_MODE = 'use_only'        # How to handle existing path templates
SPATIAL_MODEL_MODE = 'use_only'        # How to handle existing spatial models
PLOT = False
MP4 = True                          # Whether to generate MP4 video of fusion process

# --- VISUALIZATION ---
TIME_BIN_MINUTES = 5                  # Split output into N-minute chunks
SHOW_DISCARDED = False                # Show discarded tracks (red dots)

# --- FUSION PARAMETERS (Advanced) ---
FINE_MATCH_DIST = 5.0                 # Fusion matching threshold (meters)
ISOLATION_RADIUS = 15.0               # Distance to be considered "isolated"
LATERAL_BUFFER = 2.0                  # Path template width (half lane)
LOOKAHEAD_TIME = 5.0                  # Max time gap for path stitching (sec)
MIN_TRACK_DURATION = 3.0              # Min duration for high confidence (sec)

# ============================================================================
# END USER CONFIGURATION
# ============================================================================

import pandas as pd
import numpy as np
import re
import base64
import io
import json
import plotly.express as px
from scipy.interpolate import Rbf
from shapely.geometry import LineString, Point
from shapely.affinity import scale
from PIL import Image
from datetime import datetime, timedelta
import os
import cv2

# Internal constants (derived from user config)
COARSE_MATCH_DIST = 10.0  # Initial search radius for calibration
MIN_CALIB_POINTS = 10     # Minimum calibration points for RBF
SMOOTHING = 5.0           # RBF smoothing factor
MIN_TEMPLATE_POINTS = 10  # Minimum points to create template

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


# --- SPATIAL MODEL PERSISTENCE ---

def load_spatial_models(filepath, mode):
    """
    Load spatial bias models from JSON file.
    
    mode: 'use_only', 'augment', 'new', 'replace'
    """
    if mode == 'new' or not os.path.exists(filepath):
        return None
    
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        print(f"\n--- Loaded Spatial Models from {filepath} ---")
        print(f"   Created: {data.get('created', 'unknown')}")
        print(f"   Calibration points: {data.get('calibration_points', 0)}")
        
        return data
    except Exception as e:
        print(f"\n⚠️ Warning: Could not load spatial models: {e}")
        return None


def save_spatial_models(filepath, models, calibration_info):
    """Save spatial bias models to JSON file"""
    save_data = {
        'created': datetime.now().isoformat(),
        'calibration_points': calibration_info.get('num_points', 0),
        'models': {}
    }
    
    # Save RBF model parameters (we can't serialize RBF directly, so save training data)
    for sensor_id, model_data in models.items():
        if model_data is not None:
            save_data['models'][str(sensor_id)] = {
                'training_x': model_data['training_x'].tolist() if hasattr(model_data['training_x'], 'tolist') else list(model_data['training_x']),
                'training_y': model_data['training_y'].tolist() if hasattr(model_data['training_y'], 'tolist') else list(model_data['training_y']),
                'delta_x': model_data['delta_x'].tolist() if hasattr(model_data['delta_x'], 'tolist') else list(model_data['delta_x']),
                'delta_y': model_data['delta_y'].tolist() if hasattr(model_data['delta_y'], 'tolist') else list(model_data['delta_y'])
            }
    
    with open(filepath, 'w') as f:
        json.dump(save_data, f, indent=2)
    
    print(f"\n✓ Saved spatial models to {filepath}")


def rebuild_rbf_from_saved(saved_model_data):
    """Rebuild RBF interpolators from saved training data"""
    models = {}
    
    for sensor_id, data in saved_model_data.get('models', {}).items():
        training_x = np.array(data['training_x'])
        training_y = np.array(data['training_y'])
        delta_x = np.array(data['delta_x'])
        delta_y = np.array(data['delta_y'])
        
        rbf_dx = Rbf(training_x, training_y, delta_x, function='multiquadric', smooth=SMOOTHING)
        rbf_dy = Rbf(training_x, training_y, delta_y, function='multiquadric', smooth=SMOOTHING)
        
        models[int(sensor_id)] = {
            'rbf_dx': rbf_dx,
            'rbf_dy': rbf_dy,
            'training_x': training_x,
            'training_y': training_y,
            'delta_x': delta_x,
            'delta_y': delta_y
        }
    
    return models


# --- END SPATIAL MODEL PERSISTENCE ---

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
def train_spatial_bias_model(df, mode='augment', saved_models=None):
    """
    Builds an RBF Interpolator to predict the error (dx, dy) 
    between sensors based on location (x, y).
    
    mode: 'use_only' - only use saved models
          'augment' - add new data to saved models
          'new' - ignore saved models, train fresh
          'replace' - train fresh and replace saved
    """
    print(f"\n--- Training Spatial Bias Model (mode={mode}) ---")
    
    # Use only existing models
    if mode == 'use_only' and saved_models:
        print("   Using existing spatial models only")
        return rebuild_rbf_from_saved(saved_models), saved_models
    
    # Train new models
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

    print(f"   Found {len(training_points)} new calibration points.")
    
    # Augment with saved data if mode is 'augment'
    if mode == 'augment' and saved_models and 'models' in saved_models:
        print("   Augmenting with saved calibration data...")
        for sensor_id, data in saved_models['models'].items():
            for i in range(len(data['training_x'])):
                training_points.append({
                    'x': data['training_x'][i],
                    'y': data['training_y'][i],
                    'dx': data['delta_x'][i],
                    'dy': data['delta_y'][i],
                    'sensor': int(sensor_id)
                })
        print(f"   Total calibration points: {len(training_points)}")
    
    train_df = pd.DataFrame(training_points)
    
    if train_df.empty:
        print("⚠️ Not enough calibration data found. Using Raw alignment.")
        return None, {'num_points': 0}

    models = {}
    calibration_info = {'num_points': len(train_df)}
    
    for sid in train_df['sensor'].unique():
        s_data = train_df[train_df['sensor'] == sid]
        if len(s_data) < MIN_CALIB_POINTS:
            print(f"   Skipping S{sid} (only {len(s_data)} points)")
            continue
            
        print(f"   Fitting Spatial Model for Sensor {sid} ({len(s_data)} pts)...")
        try:
            training_x = s_data['x'].values
            training_y = s_data['y'].values
            delta_x = s_data['dx'].values
            delta_y = s_data['dy'].values
            
            rbf_dx = Rbf(training_x, training_y, delta_x, function='multiquadric', smooth=SMOOTHING)
            rbf_dy = Rbf(training_x, training_y, delta_y, function='multiquadric', smooth=SMOOTHING)
            
            models[sid] = {
                'rbf_dx': rbf_dx,
                'rbf_dy': rbf_dy,
                'training_x': training_x,
                'training_y': training_y,
                'delta_x': delta_x,
                'delta_y': delta_y
            }
        except Exception as e:
            print(f"   RBF Error S{sid}: {e}")
            
    return models, calibration_info

def apply_spatial_correction(df, models):
    """
    Applies the learned RBF warp to align all sensors to S0.
    """
    if not models:
        df['CorrX'] = df['X']
        df['CorrY'] = df['Y']
        return df
        
    print("\n--- Applying Spatial Correction ---")
    
    corr_x_list = []
    corr_y_list = []
    
    for _, row in df.iterrows():
        sid = row['Sensor']
        x, y = row['X'], row['Y']
        
        if sid == 0 or sid not in models:
            corr_x_list.append(x)
            corr_y_list.append(y)
        else:
            model_data = models[sid]
            rbf_dx = model_data['rbf_dx']
            rbf_dy = model_data['rbf_dy']
            dx = rbf_dx(x, y)
            dy = rbf_dy(x, y)
            
            corr_x_list.append(x + dx)
            corr_y_list.append(y + dy)
            
    df['CorrX'] = corr_x_list
    df['CorrY'] = corr_y_list
    return df


def check_gate_crossings(track_df, gates, tolerance=0.1):
    """
    Detect precise gate crossings for a track.
    
    Returns list of dicts with: time, gate_name, gate_idx, sensor, crossing_point
    """
    if len(track_df) < 2:
        return []
    
    crossings = []
    
    # Buffer gates if using tolerance
    if tolerance > 0:
        buffered_gates = [g['line'].buffer(tolerance) for g in gates]
    else:
        buffered_gates = [g['line'] for g in gates]
    
    for i in range(len(track_df) - 1):
        p1 = Point(track_df.iloc[i]['CorrX'], track_df.iloc[i]['CorrY'])
        p2 = Point(track_df.iloc[i+1]['CorrX'], track_df.iloc[i+1]['CorrY'])
        segment = LineString([p1, p2])
        
        t1 = track_df.iloc[i]['Time']
        t2 = track_df.iloc[i+1]['Time']
        dt = t2 - t1 if t2 > t1 else 1e-6
        
        for j, gate_geom in enumerate(buffered_gates):
            if not segment.intersects(gate_geom):
                continue

            inter = segment.intersection(gate_geom)
            if inter.is_empty:
                continue

            # Representative point handles all common intersection types safely
            cross_pt = inter.representative_point()
            if cross_pt.is_empty:
                continue

            cross_x, cross_y = cross_pt.x, cross_pt.y

            dist_p1 = p1.distance(Point(cross_x, cross_y))
            frac = dist_p1 / segment.length if segment.length > 0 else 0.5
            cross_time = t1 + frac * dt

            crossings.append({
                'time': cross_time,
                'gate_name': gates[j]['name'],
                'gate_idx': gates[j]['idx'],
                'sensor': gates[j]['sensor'],          # ← This was missing
                'crossing_point': (cross_x, cross_y)
            })
    
    crossings.sort(key=lambda c: c['time'])
    
    # Optional: remove consecutive duplicates on same gate
    unique = []
    last_gate = None
    for c in crossings:
        if c['gate_name'] != last_gate:
            unique.append(c)
            last_gate = c['gate_name']
    
    return unique
    

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
            gate_list = [f"{c['gate_name']}(idx={c['gate_idx']})" for c in crossings]
            print(f"      Crossed {num_gates} gates: {gate_list}")
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
    

def plot_final(fused, internal, discarded, map_config, bg_image, gates, templates=None, 
               time_bin_minutes=5, show_discarded=False, output_prefix="fusion"):
    """
    Create animated visualization with time binning.
    
    Parameters:
    - time_bin_minutes: Split data into N-minute chunks (separate HTML files)
    - show_discarded: Whether to show discarded tracks
    - output_prefix: Prefix for output filenames
    """
    print("\n--- Plotting ---")
    
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
        internal['ColorVal'] = internal.apply(lambda r: 
            {0:'cyan', 1:'yellow', 2:'lime', 3:'magenta'}.get(get_color_index(r['ColorID']), 'gray'), axis=1)
        internal['MarkerSize'] = 8
    if not discarded.empty:
        discarded = discarded.copy()
        discarded['ColorVal'] = 'red'
        discarded['MarkerSize'] = 6
    
    # Combine data
    df_list = []
    if show_discarded and not discarded.empty:
        df_list.append(discarded)
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
    
    # Split into time bins
    time_range_seconds = df['Time'].max() - df['Time'].min()
    bin_seconds = time_bin_minutes * 60
    num_bins = max(1, int(np.ceil(time_range_seconds / bin_seconds)))
    
    print(f"   Creating {num_bins} time bins ({time_bin_minutes} min each)")
    
    w = map_config.get('width', 1000) * map_config.get('scale', 0.1)
    h = map_config.get('height', 1000) * map_config.get('scale', 0.1)
    
    global_start_time = df['Time'].min()

    for bin_idx in range(num_bins):
        bin_start = global_start_time + bin_idx * bin_seconds
        bin_end = bin_start + bin_seconds
        
        df_bin = df[(df['Time'] >= bin_start) & (df['Time'] < bin_end)].copy()
        
        if df_bin.empty:
            continue
        
        # --- DOWNSAMPLING ---
        unique_times = np.sort(df_bin['Time'].unique())
        
        # Calculate the real time step (dt) of the RAW data
        if len(unique_times) > 1:
            raw_dt_ms = (unique_times[1] - unique_times[0]) * 1000
        else:
            raw_dt_ms = 100
            
        # Downsample: Take every 3rd frame
        # Effectively, our new 'dt' is 3 * raw_dt
        sampled_times = unique_times[::3]
        
        # Calculate the duration required for 1x (Real-Time) playback
        # If we skipped frames, the time gap is larger, so we wait longer.
        if len(sampled_times) > 1:
            avg_dt_seconds = np.mean(np.diff(sampled_times))
            duration_1x_ms = int(avg_dt_seconds * 1000)
        else:
            duration_1x_ms = 100
            
        # Cap minimum duration to prevent browser freeze (20ms = 50fps)
        duration_1x_ms = max(20, duration_1x_ms)
        
        print(f"      Calculated 1x frame duration: {duration_1x_ms}ms (based on avg dt: {avg_dt_seconds:.3f}s)")

        df_plot = df_bin[df_bin['Time'].isin(sampled_times)].copy()
        df_plot['TimeDisplay'] = df_plot['Time'].apply(lambda t: f"{(t - global_start_time):.1f}s")
        
        print(f"\n   Bin {bin_idx + 1}/{num_bins}: {bin_start:.1f} - {bin_end:.1f}")
        print(f"      Points: {len(df_plot)} across {len(sampled_times)} frames")
        
        fig = px.scatter(
            df_plot, 
            x='X', y='Y', 
            animation_frame='TimeDisplay',
            animation_group='Hover',
            color='ColorVal',
            size='MarkerSize',
            hover_name='Hover',
            color_discrete_map='identity',
            title=f"Radar Fusion - Bin {bin_idx+1}"
        )
        
        fig.update_traces(marker=dict(line=dict(width=0.5, color='black'), opacity=0.7))
        
        # Add gate lines
        for gate in gates:
            fig.add_shape(
                type="line",
                x0=gate['p1'][0], y0=gate['p1'][1],
                x1=gate['p2'][0], y1=gate['p2'][1],
                line=dict(color="lime" if gate['sensor'] == 1 else "orange", width=5),
                name=gate['name']
            )
            fig.add_annotation(
                x=(gate['p1'][0] + gate['p2'][0])/2,
                y=(gate['p1'][1] + gate['p2'][1])/2,
                text=gate['name'],
                showarrow=False,
                font=dict(color="white", size=14, family="Arial Black"),
                bgcolor="rgba(0,0,0,0.5)"
            )
        
        if templates:
            for template in templates:
                x_coords = [pt['x'] for pt in template.points]
                y_coords = [pt['y'] for pt in template.points]
                
                fig.add_trace(px.line(x=x_coords, y=y_coords).data[0])
                fig.data[-1].line.color = 'rgba(100,200,255,0.4)'
                fig.data[-1].line.width = 2
                fig.data[-1].line.dash = 'dash'
                fig.data[-1].showlegend = False
        
        # --- CONTROL BUTTONS ---
        
        # Define the Animation Settings for different speeds
        # We use 'transition': {'duration': 0} to make it snappy
        def create_play_args(duration):
            return [
                None, 
                {"frame": {"duration": duration, "redraw": True}, 
                 "fromcurrent": True, 
                 "transition": {"duration": 0}}
            ]

        updatemenus = [
            # Play/Pause Group
            {
                "type": "buttons",
                "direction": "left",
                "pad": {"r": 10, "t": 60},
                "showactive": False,
                "x": 0.1, "y": 0.15, "xanchor": "right", "yanchor": "top",
                "buttons": [
                    {
                        "label": "▶ Play (1x)",
                        "method": "animate",
                        "args": create_play_args(duration_1x_ms)
                    },
                    {
                        "label": "⏸ Pause",
                        "method": "animate",
                        "args": [[None], {"frame": {"duration": 0, "redraw": False}, "mode": "immediate", "transition": {"duration": 0}}]
                    }
                ]
            },
            # Speed Control Group
            {
                "type": "buttons",
                "direction": "left",
                "pad": {"r": 10, "t": 60},
                "showactive": True,
                "x": 0.11, "y": 0.15, "xanchor": "left", "yanchor": "top",
                "buttons": [
                    {
                        "label": "2x",
                        "method": "animate",
                        "args": create_play_args(int(duration_1x_ms / 2))
                    },
                    {
                        "label": "5x",
                        "method": "animate",
                        "args": create_play_args(int(duration_1x_ms / 5))
                    },
                    {
                        "label": "10x",
                        "method": "animate",
                        "args": create_play_args(int(duration_1x_ms / 10))
                    }
                ]
            }
        ]

        # --- TIMELINE SLIDER ---
        step_names = sorted(df_plot['TimeDisplay'].unique(), key=lambda x: float(x[:-1]))
        timeline_steps = []
        for t_str in step_names:
            step = {
                "method": "animate",
                "args": [
                    [t_str],
                    {"mode": "immediate", "frame": {"duration": 0, "redraw": True}, "transition": {"duration": 0}}
                ],
                "label": t_str
            }
            timeline_steps.append(step)

        timeline_slider = {
            'active': 0,
            'yanchor': 'top',
            'xanchor': 'left',
            'currentvalue': {
                'font': {'size': 20},
                'prefix': 'Time: ',
                'visible': True,
                'xanchor': 'right'
            },
            'transition': {'duration': 0, 'easing': 'linear'},
            'pad': {'b': 10, 't': 50},
            'len': 0.9,
            'x': 0.1,
            'y': 0,
            'steps': timeline_steps
        }

        # Update layout
        fig.update_layout(
            images=[dict(source=bg_image, xref="x", yref="y", x=0, y=0, sizex=w, sizey=h, 
                        sizing="stretch", opacity=0.8, layer="below")],
            xaxis=dict(range=[0, w], showgrid=False, zeroline=False, visible=False),
            yaxis=dict(range=[h, 0], showgrid=False, zeroline=False, visible=False),
            template="plotly_dark", 
            height=850,
            updatemenus=updatemenus, # Explicitly add Play buttons
            sliders=[timeline_slider] # Only timeline slider
        )

        filename = INT_DIR + f"{output_prefix}_bin{bin_idx + 1:03d}.html"
        fig.write_html(filename)
        print(f"      ✓ Saved to {filename}")
    
    print(f"\n✓ Created {num_bins} visualization file(s)")

def create_mp4_video(fused, internal, discarded, map_config, bg_image_data, gates, 
                     output_file="fusion_video.mp4", fps=20):
    """
    Generates an MP4 video of the traffic fusion with overlays.
    """
    print("\n--- Generating MP4 Video ---")
    
    # 1. Setup Data
    df_list = []
    if not fused.empty:
        f = fused.copy()
        f['DrawType'] = 'Fused'
        df_list.append(f)
    if not internal.empty:
        i = internal.copy()
        i['DrawType'] = 'Internal'
        # Check if stitched
        if 'stitched' in i.columns:
            i.loc[i['stitched'] == True, 'DrawType'] = 'Stitched'
        df_list.append(i)
    if not discarded.empty:
        d = discarded.copy()
        d['DrawType'] = 'Discarded'
        df_list.append(d)
        
    if not df_list:
        print("No data to render.")
        return

    df = pd.concat(df_list).sort_values('Time')
    unique_times = df['Time'].unique()
    print(f"   Rendering {len(unique_times)} frames...")
    
    # 2. Decode Background
    if not bg_image_data:
        print("No background image found. Creating black canvas.")
        bg_h, bg_w = int(map_config.get('height', 2000)), int(map_config.get('width', 2000))
        background = np.zeros((bg_h, bg_w, 3), dtype=np.uint8)
    else:
        try:
            if ',' in bg_image_data: bg_image_data = bg_image_data.split(',')[1]
            img_bytes = base64.b64decode(bg_image_data)
            np_arr = np.frombuffer(img_bytes, np.uint8)
            background = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            bg_h, bg_w = background.shape[:2]
        except Exception as e:
            print(f"Error decoding background: {e}")
            return

    # 3. Coordinate Transformer
    scale = map_config.get('scale', 0.1)
    off_x = map_config.get('bg_off_x', 0)
    off_y = map_config.get('bg_off_y', 0)

    def to_pix(mx, my):
        # Maps Meter coordinates to Pixel coordinates
        px = int((mx / scale) + off_x)
        py = int((my / scale) + off_y)
        return px, py

    # 4. Initialize Video
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_file, fourcc, fps, (bg_w, bg_h))
    
    # Pre-draw Gates
    static_bg = background.copy()
    for g in gates:
        p1 = to_pix(g['p1'][0], g['p1'][1])
        p2 = to_pix(g['p2'][0], g['p2'][1])
        color = (0, 255, 0) if g.get('sensor', 0) == 1 else (0, 165, 255) # Lime vs Orange
        cv2.line(static_bg, p1, p2, color, 2)
        cx, cy = (p1[0]+p2[0])//2, (p1[1]+p2[1])//2
        cv2.putText(static_bg, g['name'], (cx, cy-5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

    # 5. Render Loop
    frame_count = 0
    for t in unique_times:
        frame = static_bg.copy()
        current_objs = df[df['Time'] == t]
        
        for _, row in current_objs.iterrows():
            # FIX: Use 'X'/'Y' if available, fallback to 'CorrX'/'CorrY'
            mx = row.get('X', row.get('CorrX', 0))
            my = row.get('Y', row.get('CorrY', 0))
            
            px, py = to_pix(mx, my)
            
            if px < 0 or px >= bg_w or py < 0 or py >= bg_h: continue

            draw_type = row['DrawType']
            
            # Determine Color (BGR)
            # Default Gray
            color = (200, 200, 200) 
            
            # Logic: Input S0=Blue, Input S1=Yellow, Fused=Blend
            # Try to grab Alpha if calculated by gradient logic
            alpha = row.get('Alpha', -1)
            
            # Determine Sensor ID if alpha missing
            sensor_id = 0
            if hasattr(row, 'ColorID'):
                try: sensor_id = int(row['ColorID']) % 2
                except: pass
            
            if draw_type == 'Fused':
                if alpha != -1:
                    # Blend Blue(255,0,0) -> Yellow(0,255,255)
                    b = int(255 * (1 - alpha))
                    g = int(255 * alpha)
                    r = int(255 * alpha)
                    color = (b, g, r) 
                else:
                    color = (255, 255, 255) # White
            elif draw_type == 'Internal' or draw_type == 'Stitched':
                if sensor_id == 0: color = (255, 200, 0) # Blue-ish
                else: color = (0, 255, 255) # Yellow
            elif draw_type == 'Discarded':
                color = (0, 0, 255) # Red

            # Shape Logic
            if draw_type == 'Fused':
                # Star-like (Circle + Cross)
                cv2.circle(frame, (px, py), 6, color, -1)
                cv2.line(frame, (px-8, py), (px+8, py), (0,0,0), 1)
                cv2.line(frame, (px, py-8), (px, py+8), (0,0,0), 1)
            elif draw_type == 'Stitched':
                # Diamond
                pts = np.array([[px, py-8], [px+8, py], [px, py+8], [px-8, py]], np.int32)
                cv2.fillPoly(frame, [pts], color)
                cv2.polylines(frame, [pts], True, (0,0,0), 1)
            elif draw_type == 'Discarded':
                # X
                cv2.line(frame, (px-5, py-5), (px+5, py+5), color, 2)
                cv2.line(frame, (px+5, py-5), (px-5, py+5), color, 2)
            else:
                # Circle (Internal)
                cv2.circle(frame, (px, py), 5, color, -1)
                cv2.circle(frame, (px, py), 5, (0,0,0), 1)

            # Floating ID (Last 3 chars)
            if 'ID' in row: obj_id = str(row['ID'])
            elif 'ColorID' in row: obj_id = str(row['ColorID'])
            else: obj_id = "?"
            
            short_id = obj_id[-3:] if len(obj_id) > 3 else obj_id
            cv2.putText(frame, short_id, (px+8, py-8), cv2.FONT_HERSHEY_PLAIN, 1.0, color, 1)

        # HUD Overlay
        total_seconds = int(t)
        ms = int((t - total_seconds) * 1000)
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        time_str = f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
        
        cv2.rectangle(frame, (0, 0), (220, 40), (0, 0, 0), -1)
        cv2.putText(frame, time_str, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        
        out.write(frame)
        frame_count += 1
        if frame_count % 100 == 0:
            print(f"   Rendered {frame_count} frames...")

    out.release()
    print(f"✓ Video saved to {output_file}")

def plot_final_video(fused, internal, discarded, map_config, bg_image, gates, fields, templates=None,
                     time_bin_minutes=5, fps=10, show_discarded=False, output_prefix="fusion"):
    """
    Create MP4 video visualization using OpenCV.
    """
    print("\n--- Creating Video Output ---")
    
    try:
        import cv2
    except ImportError:
        print("    ⚠️  OpenCV not installed. Run: pip install opencv-python")
        return
    
    # Helper to handle String IDs
    def get_color_index(val):
        try:
            return int(val) % 10
        except:
            return hash(str(val)) % 10
    
    # Prepare data
    if not fused.empty:
        fused = fused.copy()
        fused['TrackStatus'] = 'Fused'
        fused['MarkerShape'] = 'diamond'
    if not internal.empty:
        internal = internal.copy()
        internal['TrackStatus'] = 'Internal'
        internal['MarkerShape'] = 'circle'
    if not discarded.empty:
        discarded = discarded.copy()
        discarded['TrackStatus'] = 'Discarded'
        discarded['MarkerShape'] = 'square'
    
    # Combine data
    df_list = []
    if show_discarded and not discarded.empty:
        df_list.append(discarded)
    if not internal.empty:
        df_list.append(internal)
    if not fused.empty:
        df_list.append(fused)
    
    if not df_list:
        print("    ERROR: No data to plot!")
        return
    
    df = pd.concat(df_list, ignore_index=True)
    df = df.sort_values('Time')
    
    # Decode background image
    w_pixels = map_config.get('width', 1000)
    h_pixels = map_config.get('height', 1000)
    scale = map_config.get('scale', 0.1)
    
    if bg_image:
        # --- FIX START ---
        # Strip the "data:image/png;base64," header if present
        if ',' in bg_image:
            bg_image_clean = bg_image.split(',')[1]
        else:
            bg_image_clean = bg_image
            
        try:
            img_data = base64.b64decode(bg_image_clean)
            img = Image.open(io.BytesIO(img_data))
            bg_array = np.array(img.convert('RGB'))
            bg_array = cv2.cvtColor(bg_array, cv2.COLOR_RGB2BGR)
            h_pixels, w_pixels = bg_array.shape[:2]
        except Exception as e:
            print(f"    ⚠️ Error decoding background image: {e}")
            bg_array = np.zeros((h_pixels, w_pixels, 3), dtype=np.uint8)
        # --- FIX END ---
    else:
        # Create blank background
        bg_array = np.zeros((h_pixels, w_pixels, 3), dtype=np.uint8)
    
    print(f"    Video size: {w_pixels}x{h_pixels}")
    
    # Define colors (BGR format for OpenCV)
    SENSOR_COLORS = {
        0: (255, 100, 100),   # Blue for S0
        1: (100, 100, 255),   # Red for S1
        2: (100, 255, 100),   # Green for S2
        3: (100, 255, 255)    # Yellow for S3
    }
    
    STATUS_COLORS = {
        'Fused': (255, 255, 255),      # White
        'Internal': (200, 200, 200),   # Light gray
        'Discarded': (100, 100, 100)   # Dark gray
    }
    
    # Split into time bins
    time_range = df['Time'].max() - df['Time'].min()
    bin_seconds = time_bin_minutes * 60
    num_bins = max(1, int(np.ceil(time_range / bin_seconds)))
    
    print(f"    Creating {num_bins} video bins ({time_bin_minutes} min each)")
    
    global_start = df['Time'].min()
    
    for bin_idx in range(num_bins):
        bin_start = global_start + bin_idx * bin_seconds
        bin_end = bin_start + bin_seconds
        
        df_bin = df[(df['Time'] >= bin_start) & (df['Time'] < bin_end)].copy()
        
        if df_bin.empty:
            continue
        
        # Get unique times (frames)
        unique_times = sorted(df_bin['Time'].unique())
        
        # Downsample if too many frames
        if len(unique_times) > 600:
            unique_times = unique_times[::len(unique_times)//600]
        
        print(f"\n    Bin {bin_idx + 1}/{num_bins}: {len(unique_times)} frames")
        
        # Create video writer
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        video_filename = f"{output_prefix}_bin{bin_idx + 1:03d}.mp4"
        video = cv2.VideoWriter(video_filename, fourcc, fps, (w_pixels, h_pixels))
        
        for frame_idx, t in enumerate(unique_times):
            # Start with background
            frame = bg_array.copy()
            
            # Get data for this frame
            frame_data = df_bin[df_bin['Time'] == t]
            
            # Draw field polygons (semi-transparent)
            if fields:
                overlay = frame.copy()
                for field in fields:
                    coords = list(field['polygon'].exterior.coords)
                    pts = np.array([(int(x/scale), int((map_config.get('height', 1000)*scale - y)/scale)) 
                                   for x, y in coords], dtype=np.int32)
                    
                    sensor_id = field['sensor_id']
                    color = SENSOR_COLORS.get(sensor_id, (150, 150, 150))
                    cv2.fillPoly(overlay, [pts], color)
                
                cv2.addWeighted(overlay, 0.15, frame, 0.85, 0, frame)
            
            # Draw gates
            for gate in gates:
                x1 = int(gate['p1'][0] / scale)
                y1 = int((map_config.get('height', 1000)*scale - gate['p1'][1]) / scale)
                x2 = int(gate['p2'][0] / scale)
                y2 = int((map_config.get('height', 1000)*scale - gate['p2'][1]) / scale)
                
                color = (100, 255, 100) if gate['sensor'] == 1 else (100, 200, 255)
                cv2.line(frame, (x1, y1), (x2, y2), color, 3)
            
            # Draw path templates
            if templates:
                for template in templates:
                    pts = []
                    for pt in template.points:
                        px = int(pt['x'] / scale)
                        py = int((map_config.get('height', 1000)*scale - pt['y']) / scale)
                        pts.append((px, py))
                    
                    if len(pts) > 0:
                        pts = np.array(pts, dtype=np.int32)
                        cv2.polylines(frame, [pts], False, (255, 200, 100), 2, cv2.LINE_AA)
            
            # Draw objects
            for _, obj in frame_data.iterrows():
                x_map = obj['X']
                y_map = obj['Y']
                
                # Convert to pixel coordinates
                px = int(x_map / scale)
                py = int((map_config.get('height', 1000)*scale - y_map) / scale)
                
                if px < 0 or px >= w_pixels or py < 0 or py >= h_pixels:
                    continue
                
                # Get sensor color
                sensor_id = obj.get('Sensor', 0)
                color = SENSOR_COLORS.get(sensor_id, (200, 200, 200))
                
                # Adjust by status
                status = obj.get('TrackStatus', 'Internal')
                if status == 'Fused':
                    color = (255, 255, 255)  # White for fused
                elif status == 'Discarded':
                    color = (100, 100, 100)  # Gray for discarded
                
                # Draw shape based on track status
                shape = obj.get('MarkerShape', 'circle')
                size = 8
                
                if shape == 'circle':
                    cv2.circle(frame, (px, py), size, color, -1)
                    cv2.circle(frame, (px, py), size, (0, 0, 0), 1)
                elif shape == 'diamond':
                    pts = np.array([
                        [px, py - size],
                        [px + size, py],
                        [px, py + size],
                        [px - size, py]
                    ], dtype=np.int32)
                    cv2.fillPoly(frame, [pts], color)
                    cv2.polylines(frame, [pts], True, (0, 0, 0), 1)
                elif shape == 'square':
                    cv2.rectangle(frame, (px - size, py - size), (px + size, py + size), color, -1)
                    cv2.rectangle(frame, (px - size, py - size), (px + size, py + size), (0, 0, 0), 1)
                
                # Add short text label (last 4 chars of ID)
                obj_id = str(obj.get('ID', ''))
                label = obj_id[-4:] if len(obj_id) > 4 else obj_id
                
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.3
                thickness = 1
                
                (text_w, text_h), _ = cv2.getTextSize(label, font, font_scale, thickness)
                text_x = px - text_w // 2
                text_y = py - size - 3
                
                # Text background
                cv2.rectangle(frame, (text_x - 1, text_y - text_h - 1), 
                             (text_x + text_w + 1, text_y + 2), (0, 0, 0), -1)
                cv2.putText(frame, label, (text_x, text_y), font, font_scale, (255, 255, 255), thickness)
            
            # Add timestamp (top-left corner)
            elapsed = t - global_start
            timestamp_str = f"Time: {int(elapsed//60):02d}:{int(elapsed%60):02d}.{int((elapsed%1)*10):01d}"
            cv2.rectangle(frame, (5, 5), (200, 35), (0, 0, 0), -1)
            cv2.putText(frame, timestamp_str, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 
                       0.6, (255, 255, 255), 2)
            
            # Add legend (top-right corner)
            legend_x = w_pixels - 200
            legend_y = 10
            
            cv2.rectangle(frame, (legend_x - 5, legend_y), 
                         (w_pixels - 5, legend_y + 130), (0, 0, 0), -1)
            
            # Legend title
            cv2.putText(frame, "Legend:", (legend_x, legend_y + 20), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            
            # Shape legend
            y_offset = legend_y + 40
            cv2.circle(frame, (legend_x + 10, y_offset), 5, (200, 200, 200), -1)
            cv2.putText(frame, "Internal", (legend_x + 25, y_offset + 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
            
            y_offset += 20
            pts = np.array([[legend_x + 10, y_offset - 5], [legend_x + 15, y_offset], 
                           [legend_x + 10, y_offset + 5], [legend_x + 5, y_offset]], dtype=np.int32)
            cv2.fillPoly(frame, [pts], (255, 255, 255))
            cv2.putText(frame, "Fused", (legend_x + 25, y_offset + 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
            
            y_offset += 20
            cv2.rectangle(frame, (legend_x + 5, y_offset - 5), 
                         (legend_x + 15, y_offset + 5), (100, 100, 100), -1)
            cv2.putText(frame, "Discarded", (legend_x + 25, y_offset + 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
            
            # Sensor colors
            y_offset += 25
            for sensor_id, color in SENSOR_COLORS.items():
                if 'Sensor' in df_bin.columns and sensor_id in df_bin['Sensor'].unique():
                    cv2.circle(frame, (legend_x + 10, y_offset), 5, color, -1)
                    cv2.putText(frame, f"S{sensor_id}", (legend_x + 25, y_offset + 5), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
                    y_offset += 15
            
            # Write frame
            video.write(frame)
            
            if (frame_idx + 1) % 50 == 0:
                print(f"      Processed {frame_idx + 1}/{len(unique_times)} frames", end='\r')
        
        video.release()
        print(f"\n      ✓ Saved to {video_filename}")
    
    print(f"\n✓ Created {num_bins} video file(s)")

def plot_final(fused, internal, discarded, map_config, bg_image, gates, fields, templates=None, 
               time_bin_minutes=5, animation_speed_ms=100, show_discarded=False, output_prefix="fusion"):
    """
    Create animated visualization with time binning and field-based blending.
    
    Parameters:
    - fields: Sensor field polygons (shows trusted regions for each sensor)
    - time_bin_minutes: Split data into N-minute chunks (separate HTML files)
    - animation_speed_ms: Frame duration in milliseconds
    - show_discarded: Whether to show discarded tracks
    - output_prefix: Prefix for output filenames
    
    Visualization:
    - Field polygons: Semi-transparent colored regions showing sensor coverage
    - Gate lines: Solid lines showing gate positions
    - Path templates: Dashed blue lines showing learned trajectories
    - Track points: Colored by track type (white=fused, colored=valid internal, red=discarded)
    """
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
        internal['ColorVal'] = internal.apply(lambda r: 
            {0:'cyan', 1:'yellow', 2:'lime', 3:'magenta'}.get(get_color_index(r['ColorID']), 'gray'), axis=1)
        internal['MarkerSize'] = 8
    if not discarded.empty:
        discarded = discarded.copy()
        discarded['ColorVal'] = 'red'
        discarded['MarkerSize'] = 6
    
    # Combine data
    df_list = []
    if show_discarded and not discarded.empty:
        df_list.append(discarded)
    if not internal.empty:
        df_list.append(internal)
    if not fused.empty:
        df_list.append(fused)
    
    if not df_list:
        print("   ERROR: No data to plot!")
        return
    
    df = pd.concat(df_list, ignore_index=True)
    df = df.sort_values('Time')
    
    # Convert epoch time to human-readable
    if not df.empty:
        min_time = df['Time'].min()
        # Create datetime-like strings for display
        df['TimeDisplay'] = df['Time'].apply(lambda t: 
            str(timedelta(seconds=int(t - min_time)))[2:])  # Remove leading "0 days, "
    
    print(f"\n   Combined dataframe: {len(df)} points")
    print(f"   Time range: {df['TimeDisplay'].min()} to {df['TimeDisplay'].max()}")
    
    # Split into time bins
    time_range_seconds = df['Time'].max() - df['Time'].min()
    bin_seconds = time_bin_minutes * 60
    num_bins = max(1, int(np.ceil(time_range_seconds / bin_seconds)))
    
    print(f"\n   Creating {num_bins} time bins ({time_bin_minutes} min each)")
    
    w = map_config.get('width', 1000) * map_config.get('scale', 0.1)
    h = map_config.get('height', 1000) * map_config.get('scale', 0.1)
    
    for bin_idx in range(num_bins):
        bin_start = df['Time'].min() + bin_idx * bin_seconds
        bin_end = bin_start + bin_seconds
        
        df_bin = df[(df['Time'] >= bin_start) & (df['Time'] < bin_end)].copy()
        
        if df_bin.empty:
            continue
        
        # Downsample for performance (every 3rd frame)
        times = df_bin['TimeDisplay'].unique()
        sampled_times = times[::3]
        df_plot = df_bin[df_bin['TimeDisplay'].isin(sampled_times)].copy()
        
        start_display = df_bin['TimeDisplay'].min()
        end_display = df_bin['TimeDisplay'].max()
        
        print(f"\n   Bin {bin_idx + 1}/{num_bins}: {start_display} - {end_display}")
        print(f"      Points: {len(df_plot)} across {len(df_plot['TimeDisplay'].unique())} frames")
        
        # Create figure
        fig = px.scatter(
            df_plot, 
            x='X', y='Y', 
            animation_frame='TimeDisplay',
            animation_group='Hover',
            color='ColorVal',
            size='MarkerSize',
            hover_name='Hover',
            color_discrete_map='identity',
            title=f"Radar Fusion - {start_display} to {end_display}"
        )
        
        fig.update_traces(marker=dict(line=dict(width=0.5, color='black'), opacity=0.7))
        
        # Add gate lines
        for gate in gates:
            fig.add_shape(
                type="line",
                x0=gate['p1'][0], y0=gate['p1'][1],
                x1=gate['p2'][0], y1=gate['p2'][1],
                line=dict(color="lime" if gate['sensor'] == 1 else "orange", width=5),
                name=gate['name']
            )
            fig.add_annotation(
                x=(gate['p1'][0] + gate['p2'][0])/2,
                y=(gate['p1'][1] + gate['p2'][1])/2,
                text=gate['name'],
                showarrow=False,
                font=dict(color="white", size=14, family="Arial Black"),
                bgcolor="rgba(0,0,0,0.7)"
            )
        
        # Add sensor field polygons
        if fields:
            field_colors = {
                0: 'rgba(255,100,100,0.15)',  # Red for S0
                1: 'rgba(100,255,100,0.15)',  # Green for S1
                2: 'rgba(100,100,255,0.15)',  # Blue for S2
                3: 'rgba(255,255,100,0.15)'   # Yellow for S3
            }
            field_border_colors = {
                0: 'rgba(255,100,100,0.8)',
                1: 'rgba(100,255,100,0.8)',
                2: 'rgba(100,100,255,0.8)',
                3: 'rgba(255,255,100,0.8)'
            }
            
            for field in fields:
                # Get polygon coordinates
                coords = list(field['polygon'].exterior.coords)
                x_coords = [c[0] for c in coords]
                y_coords = [c[1] for c in coords]
                
                sensor_id = field['sensor_id']
                fill_color = field_colors.get(sensor_id, 'rgba(150,150,150,0.15)')
                border_color = field_border_colors.get(sensor_id, 'rgba(150,150,150,0.8)')
                
                # Add filled polygon
                fig.add_trace(px.line(x=x_coords, y=y_coords).data[0])
                fig.data[-1].fill = 'toself'
                fig.data[-1].fillcolor = fill_color
                fig.data[-1].line.color = border_color
                fig.data[-1].line.width = 2
                fig.data[-1].line.dash = 'dot'
                fig.data[-1].name = field['name']
                fig.data[-1].showlegend = False
                fig.data[-1].hoverinfo = 'name'
        
        # Add path templates
        if templates:
            for template in templates:
                x_coords = [pt['x'] for pt in template.points]
                y_coords = [pt['y'] for pt in template.points]
                
                fig.add_trace(px.line(x=x_coords, y=y_coords).data[0])
                fig.data[-1].line.color = 'rgba(100,200,255,0.5)'
                fig.data[-1].line.width = 2
                fig.data[-1].line.dash = 'dash'
                fig.data[-1].name = f"{template.template_id} ({template.samples} samples)"
                fig.data[-1].showlegend = False
        
        # Update layout
        fig.update_layout(
            images=[dict(source=bg_image, xref="x", yref="y", x=0, y=0, sizex=w, sizey=h, 
                        sizing="stretch", opacity=0.8, layer="below")],
            xaxis=dict(range=[0, w], showgrid=False, zeroline=False, visible=False),  # Hide axis
            yaxis=dict(range=[h, 0], showgrid=False, zeroline=False, visible=False),  # Hide axis
            template="plotly_dark", 
            height=800,
            # Add playback speed slider
            sliders=[{
                'active': 0,
                'yanchor': 'top',
                'y': 0.05,
                'xanchor': 'left',
                'x': 0.01,
                'currentvalue': {
                    'prefix': 'Speed: ',
                    'visible': True,
                    'xanchor': 'right'
                },
                'pad': {'b': 10, 't': 50},
                'len': 0.2,
                'steps': [
                    {'label': '0.5x', 'method': 'animate', 'args': [[None], {'frame': {'duration': animation_speed_ms * 2}}]},
                    {'label': '1x', 'method': 'animate', 'args': [[None], {'frame': {'duration': animation_speed_ms}}]},
                    {'label': '2x', 'method': 'animate', 'args': [[None], {'frame': {'duration': animation_speed_ms // 2}}]},
                    {'label': '4x', 'method': 'animate', 'args': [[None], {'frame': {'duration': animation_speed_ms // 4}}]},
                ]
            }]
        )
        
        # Set default animation speed
        if fig.layout.updatemenus:
            fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = animation_speed_ms
        
        # Save to file
        filename = f"{output_prefix}_bin{bin_idx + 1:03d}.html"
        fig.write_html(filename)
        print(f"      ✓ Saved to {filename}")
    
    print(f"\n✓ Created {num_bins} visualization file(s)")

if __name__ == "__main__":
    # Load configuration
    cfg, img = parse_xml_config(XML_FILE)
    gates = load_gates(GATES_FILE, cfg)
    
    # Load existing path templates (respects PATH_TEMPLATE_MODE)
    template_data = load_path_templates(TEMPLATES_FILE)
    if PATH_TEMPLATE_MODE == 'new':
        template_data['path_templates'] = []
        print("\n⚠️  PATH_TEMPLATE_MODE='new': Ignoring existing templates")
    elif PATH_TEMPLATE_MODE == 'use_only':
        print(f"\n   PATH_TEMPLATE_MODE='use_only': Using {len(template_data['path_templates'])} existing templates")
    
    # Load existing spatial models (respects SPATIAL_MODEL_MODE)
    saved_spatial = load_spatial_models(SPATIAL_MODEL_FILE, SPATIAL_MODEL_MODE)
    
    # Load and parse data
    df = parse_and_align_data(DATA_FILE, cfg)
    
    if df.empty:
        print("ERROR: No data loaded. Exiting.")
        exit(1)
    
    # 1. Stitch same-sensor tracks FIRST (velocity-aware, before spatial correction)
    df = stitch_same_sensor_tracks(df)
    
    # 2. Learn/load spatial bias correction
    models, calibration_info = train_spatial_bias_model(df, SPATIAL_MODEL_MODE, saved_spatial)
    
    # 3. Apply correction to all data
    df_corr = apply_spatial_correction(df, models)
    
    # 4. Path-based stitching using learned templates (AFTER spatial correction)
    if PATH_TEMPLATE_MODE != 'new' and template_data['path_templates']:
        df_corr = stitch_with_path_templates(df_corr, template_data['path_templates'])
    
    # 5. Classify tracks by gate crossings
    tracks = classify_tracks_by_gates(df_corr, gates)
    
    # 6. Build/update path templates from high-confidence tracks
    if PATH_TEMPLATE_MODE in ['augment', 'replace', 'new']:
        if PATH_TEMPLATE_MODE == 'replace':
            template_data['path_templates'] = []
        template_data = build_path_templates(tracks, template_data, gates)
        save_path_templates(TEMPLATES_FILE, template_data)
    
    # 7. Save spatial models if we trained new ones
    if SPATIAL_MODEL_MODE in ['augment', 'replace', 'new'] and models:
        save_spatial_models(SPATIAL_MODEL_FILE, models, calibration_info)
    
    # 8. Fuse transition tracks, keep valid internal, collect discarded
    fused, internal, discarded = fuse_tracks_with_gates(tracks)
    
    if PLOT:
        # 9. Visualize with time binning and all configuration options
        plot_final(fused, internal, discarded, cfg, img, gates, template_data['path_templates'],
                time_bin_minutes=TIME_BIN_MINUTES,
                show_discarded=SHOW_DISCARDED,
                output_prefix=OUTPUT_PREFIX)
    
    if MP4:
        # 10. Generate MP4 Video (NEW)
        #create_mp4_video(fused, internal, discarded, cfg, img, gates, output_file=INT_DIR + "fusion_video.mp4")
        plot_final_video(fused, internal, discarded, cfg, img, gates, fields=None, templates=template_data['path_templates'],
                     time_bin_minutes=TIME_BIN_MINUTES,
                     fps=10,
                     show_discarded=SHOW_DISCARDED,
                     output_prefix=OUTPUT_PREFIX)