import re
import base64
import io
import math
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from collections import defaultdict

# --- CONFIGURATION ---
# Merge Thresholds
MERGE_DIST = 15.0  # Meters
MERGE_TIME = 2.0   # Seconds

class EvoPrecisionReplay:
    def __init__(self):
        # Image / Map Properties
        self.bg_image = None
        self.m_per_px = 0.1      # Default, will overwrite from XML
        self.bg_pos_x = 0.0      # Viewport Top-Left X in Map Space
        self.bg_pos_y = 0.0      # Viewport Top-Left Y in Map Space
        
        # Data Containers
        self.xml_sensors = {}    # {id: {x, y, az}} (Map Space)
        self.evo_sensors = {}    # {id: {x, y, az}} (EVO Space from C-Msg)
        self.raw_traces = {}
        self.merged_traces = {}
        
        # Transform (EVO Space -> Map Space)
        self.offset_x = 0.0
        self.offset_y = 0.0

    def parse_xml_configs(self, filenames):
        """Extracts Image, Scale, and Sensor Map-Coordinates"""
        print(f"--- Parsing XML Configs: {filenames} ---")
        
        for fname in filenames:
            try:
                with open(fname, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # 1. Background Image & Scale
                if self.bg_image is None:
                    # Image Data
                    img_m = re.search(r'BackgroundImage="([^"]+)"', content)
                    if img_m:
                        print(f"  Found Background Image in {fname}")
                        img_bytes = base64.b64decode(img_m.group(1))
                        self.bg_image = Image.open(io.BytesIO(img_bytes))
                    
                    # Scale (Meters Per Pixel)
                    # Try explicit tag first, fallback to standard if not found
                    mpp_m = re.search(r'BackgroundImageMeterPerPixel="([^"]+)"', content)
                    if mpp_m:
                        self.m_per_px = float(mpp_m.group(1))
                        print(f"  Scale: {self.m_per_px} Meters/Pixel")
                    
                    # Viewport Position (Top-Left of Image in Map Space)
                    pos_x_m = re.search(r'BackgroundImagePosX="([^"]+)"', content)
                    pos_y_m = re.search(r'BackgroundImagePosY="([^"]+)"', content)
                    if pos_x_m and pos_y_m:
                        self.bg_pos_x = float(pos_x_m.group(1))
                        self.bg_pos_y = float(pos_y_m.group(1))
                        print(f"  Viewport Offset: ({self.bg_pos_x}, {self.bg_pos_y})")

                # 2. Sensor Positions (Map Space)
                # Find all sensor definitions
                # We assume file 1 has ID 0,1 and file 2 has ID 0,1 (mapped to 2,3)
                # Heuristic: Map file index to global ID offset
                global_offset = 0
                if '3_4' in fname: global_offset = 2 
                
                # Regex to find all sensor blocks is hard, iterate by index
                for local_id in range(2): 
                    # Check if this sensor exists
                    px_m = re.search(f'Radarsensor_{local_id}_Position_X="([^"]+)"', content)
                    if px_m:
                        px = float(px_m.group(1))
                        py = float(re.search(f'Radarsensor_{local_id}_Position_Y="([^"]+)"', content).group(1))
                        az = float(re.search(f'Radarsensor_{local_id}_AzimuthAngle="([^"]+)"', content).group(1))
                        
                        global_id = local_id + global_offset
                        self.xml_sensors[global_id] = {'x': px, 'y': py, 'az': az}
                        print(f"  XML Sensor {global_id}: Map({px:.1f}, {py:.1f})")

            except Exception as e:
                print(f"Error parsing {fname}: {e}")

    def parse_evo_data(self, filename):
        """Extracts Traces and EVO Sensor Locations"""
        print(f"--- Parsing EVO Data: {filename} ---")
        with open(filename, 'r') as f:
            lines = f.readlines()
            
        current_time = 0.0
        
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # 1. Parse Config Message (C) for Sensor Locations
            if line.startswith('C;'):
                # C; [R0_x,R0_y,R0_a], [R1...], [R2...], [R3...]
                parts = line.split(';')
                # Data part is index 1
                if len(parts) > 1:
                    vals = [float(x) for x in parts[1].split(',')]
                    # Expecting 4 sensors * 3 values
                    for i in range(4):
                        if (i*3 + 2) < len(vals):
                            self.evo_sensors[i] = {
                                'x': vals[i*3],
                                'y': vals[i*3+1],
                                'az': vals[i*3+2] # Note: EVO az might be radians
                            }
                    print(f"  Found EVO Config: {len(self.evo_sensors)} sensors")

            # 2. Parse Timestamp
            if re.match(r'\d{2}:\d{2}:\d{2}', line):
                try:
                    parts = line.split(':')
                    current_time = float(parts[0])*3600 + float(parts[1])*60 + float(parts[2])
                except: pass
                continue

            # 3. Parse Frame Data (F)
            if line.startswith('F;'):
                parts = line.split(';')
                if len(parts) < 3: continue
                for ent in parts[2:]:
                    if not ent: continue
                    p = ent.split(',')
                    if len(p) < 4: continue
                    try:
                        oid = int(p[0])
                        x = float(p[2])
                        y = float(p[3])
                        
                        if oid not in self.raw_traces:
                            self.raw_traces[oid] = {'x':[], 'y':[], 't':[], 'cls': int(p[1])}
                        
                        self.raw_traces[oid]['x'].append(x)
                        self.raw_traces[oid]['y'].append(y)
                        self.raw_traces[oid]['t'].append(current_time)
                    except: pass

    def align_coordinates(self):
        """Calculates offset between EVO World (0,0) and XML Map Space"""
        # We align based on the Centroid of the sensors common to both
        evo_points = []
        xml_points = []
        
        common_ids = set(self.evo_sensors.keys()) & set(self.xml_sensors.keys())
        if not common_ids:
            print("Warning: No matching sensor IDs found. Using default offset.")
            return

        print(f"--- Aligning Coordinate Systems using Sensors: {list(common_ids)} ---")
        
        for sid in common_ids:
            evo_points.append([self.evo_sensors[sid]['x'], self.evo_sensors[sid]['y']])
            xml_points.append([self.xml_sensors[sid]['x'], self.xml_sensors[sid]['y']])
            
        evo_center = np.mean(evo_points, axis=0)
        xml_center = np.mean(xml_points, axis=0)
        
        # Translation Vector: XML_Center - EVO_Center
        self.offset_x = xml_center[0] - evo_center[0]
        self.offset_y = xml_center[1] - evo_center[1]
        
        print(f"  Calculated Offset: X={self.offset_x:.2f}, Y={self.offset_y:.2f}")

    def merge_traces(self):
        """Stitches broken traces"""
        sorted_ids = sorted(self.raw_traces.keys(), key=lambda k: self.raw_traces[k]['t'][0])
        active = {} 
        
        for oid in sorted_ids:
            tr = self.raw_traces[oid]
            start_x, start_y, start_t = tr['x'][0], tr['y'][0], tr['t'][0]
            
            best_match = None
            min_dist = MERGE_DIST
            
            # Find merge candidate
            for mid, state in active.items():
                dt = start_t - state['t']
                if 0 < dt < MERGE_TIME:
                    dist = math.hypot(start_x - state['x'], start_y - state['y'])
                    if dist < min_dist:
                        min_dist = dist
                        best_match = mid
            
            if best_match:
                # Merge
                self.merged_traces[best_match]['x'].extend(tr['x'])
                self.merged_traces[best_match]['y'].extend(tr['y'])
                self.merged_traces[best_match]['t'].extend(tr['t'])
                active[best_match] = {'x': tr['x'][-1], 'y': tr['y'][-1], 't': tr['t'][-1]}
            else:
                # New
                self.merged_traces[oid] = tr.copy()
                active[oid] = {'x': tr['x'][-1], 'y': tr['y'][-1], 't': tr['t'][-1]}
                
        print(f"--- Merged {len(self.raw_traces)} raw traces into {len(self.merged_traces)} objects ---")

    def world_to_pixel(self, x_evo, y_evo):
        """Transforms EVO Metric Coord -> Image Pixel Coord"""
        # 1. Transform EVO -> Map Space
        map_x = x_evo + self.offset_x
        map_y = y_evo + self.offset_y
        
        # 2. Transform Map Space -> Image Pixel
        # Pixel = (Map - ViewportPos) / MeterPerPixel
        px = (map_x - self.bg_pos_x) / self.m_per_px
        py = (map_y - self.bg_pos_y) / self.m_per_px
        
        return px, py

    def plot(self):
        if not self.bg_image:
            print("No Background Image loaded.")
            return

        fig, ax = plt.subplots(figsize=(12, 10))
        
        # 1. Show Image
        # Extent is purely in Pixel Space (0, Width, Height, 0)
        # Note: Matplotlib origin is usually Bottom-Left, but Images are Top-Left.
        # We display image normally and plot using pixel coords.
        ax.imshow(self.bg_image)
        
        # 2. Plot Traces
        for tid, t in self.merged_traces.items():
            # Convert entire trace to pixels
            px_list, py_list = [], []
            for i in range(len(t['x'])):
                px, py = self.world_to_pixel(t['x'][i], t['y'][i])
                px_list.append(px)
                py_list.append(py)
                
            color = 'yellow' if t['cls'] == 10 else 'cyan'
            ax.plot(px_list, py_list, c=color, lw=1.5, alpha=0.6)

        # 3. Plot Sensors (Using XML Coords converted to Pixels)
        for sid, s in self.xml_sensors.items():
            sx = (s['x'] - self.bg_pos_x) / self.m_per_px
            sy = (s['y'] - self.bg_pos_y) / self.m_per_px
            ax.scatter(sx, sy, c='magenta', marker='^', s=100, edgecolors='white', zorder=5)

        ax.set_title("Aligned Replay on Background Image")
        plt.show()

# --- RUN ---
if __name__ == "__main__":
    app = EvoPrecisionReplay()
    app.parse_xml_configs(['us95&sh8.iprj'])
    app.parse_evo_data('EVO_raw_data_1770174722.txt')
    app.align_coordinates() # Critical Step
    app.merge_traces()
    app.plot()