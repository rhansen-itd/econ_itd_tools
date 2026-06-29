import matplotlib
# Try QtAgg, fall back to default if not installed
#try:
#    matplotlib.use('QtAgg')
#except ImportError:
#    pass

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
import numpy as np
import json
import os
import sys
import tkinter as tk
from tkinter import simpledialog, messagebox

# --- USER IMPORTS ---
# Ensure this file exists in the same directory
try:
    from legacy.evo_fusion_visualizer import parse_xml_config
except ImportError:
    # Dummy placeholder if user is testing without the helper file
    def parse_xml_config(f):
        return {'width': 1000, 'height': 1000, 'scale': 0.1}, "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="

# --- CONFIG ---
INT_DIR = "../sites/86_US95&SH8/"
XML_FILE = INT_DIR + "us95&sh8_iprj.txt"
GATES_FILE = INT_DIR + "gates.json"
FIELDS_FILE = INT_DIR + "fields.json"

class MapAnnotator:
    def __init__(self):
        print("--- EVO Gate & Field Designer ---")
        
        # --- INITIALIZATION ORDER FIXED ---
        # 1. Define State variables first
        self.mode = 'idle'
        self.current_points = []
        self.temp_artists = []
        self.gates = []
        self.fields = []
        
        # 2. Load Data
        self.load_data()
        
        # 3. Setup GUI
        self.setup_plot()
        
        # 4. Show Instructions
        self.show_instructions()
        
        # 5. Connect Events
        self.fig.canvas.mpl_connect('key_press_event', self.on_key)
        self.fig.canvas.mpl_connect('button_press_event', self.on_click)
        self.fig.canvas.mpl_connect('close_event', self.on_close)
        
        plt.show()

    def setup_plot(self):
        self.cfg, img_b64 = parse_xml_config(XML_FILE)
        
        self.fig, self.ax = plt.subplots(figsize=(12, 10))
        self.fig.canvas.manager.set_window_title("EVO Fusion Map Designer")
        
        # Parse Image
        import base64
        import io
        from PIL import Image
        img_bytes = base64.b64decode(img_b64.split(',')[1])
        bg_img = Image.open(io.BytesIO(img_bytes))
        
        # Calc Extents
        w_m = self.cfg['width'] * self.cfg['scale']
        h_m = self.cfg['height'] * self.cfg['scale']
        
        self.ax.imshow(bg_img, extent=[0, w_m, h_m, 0])
        self.ax.set_xlim(0, w_m)
        self.ax.set_ylim(h_m, 0)
        self.update_title()
        
        # Draw loaded items
        self.redraw_all()

    def load_data(self):
        if os.path.exists(GATES_FILE):
            with open(GATES_FILE, 'r') as f:
                self.gates = json.load(f)
        if os.path.exists(FIELDS_FILE):
            with open(FIELDS_FILE, 'r') as f:
                self.fields = json.load(f)

    def save_data(self):
        with open(GATES_FILE, 'w') as f:
            json.dump(self.gates, f, indent=2)
        with open(FIELDS_FILE, 'w') as f:
            json.dump(self.fields, f, indent=2)
        print("Data saved.")

    def update_title(self):
        self.ax.set_title(f"MODE: {self.mode.upper()} | [G]ate [F]ield [D]elete [S]ave [Esc]Cancel", 
                          color='blue' if self.mode == 'idle' else 'red', fontweight='bold')
        self.fig.canvas.draw()

    def show_instructions(self):
        root = tk.Tk()
        root.withdraw() # Hide main tkinter window
        messagebox.showinfo("Instructions", 
            "Controls:\n\n"
            " 'g' : Start drawing a GATE (Click 2 points)\n"
            " 'f' : Start drawing a FIELD (Click points, Right-click to finish)\n"
            " 'd' : Delete Mode (Click near a gate center or field center to remove)\n"
            " 's' : Save to disk\n"
            " 'Esc' : Cancel current action\n\n"
            "Close this window to start."
        )
        root.destroy()

    def popup_input(self, title, prompt):
        root = tk.Tk()
        root.withdraw()
        val = simpledialog.askstring(title, prompt, parent=root)
        root.destroy()
        return val

    # --- EVENT HANDLERS ---

    def on_key(self, event):
        if event.key == 'g':
            self.mode = 'gate'
            self.current_points = []
        elif event.key == 'f':
            self.mode = 'field'
            self.current_points = []
        elif event.key == 'd':
            self.mode = 'delete'
            self.current_points = []
        elif event.key == 's':
            self.save_data()
            self.mode = 'idle'
            messagebox.showinfo("Saved", "Gates and Fields saved successfully.")
        elif event.key == 'escape':
            self.mode = 'idle'
            self.current_points = []
            self.clear_temp()
            
        self.update_title()

    def on_click(self, event):
        if event.inaxes != self.ax: return
        
        # Left click (1) adds points, Right click (3) finishes polygons
        if event.button == 1:
            if self.mode == 'gate':
                self.handle_gate_click(event.xdata, event.ydata)
            elif self.mode == 'field':
                self.handle_field_click(event.xdata, event.ydata)
            elif self.mode == 'delete':
                self.handle_delete_click(event.xdata, event.ydata)
        
        elif event.button == 3 and self.mode == 'field':
            self.finish_field()

    # --- LOGIC ---

    def handle_gate_click(self, x, y):
        self.current_points.append((x, y))
        # Draw temp marker
        p, = self.ax.plot(x, y, 'ro')
        self.temp_artists.append(p)
        
        if len(self.current_points) > 1:
            # Draw temp line
            p1, p2 = self.current_points[-2], self.current_points[-1]
            l, = self.ax.plot([p1[0], p2[0]], [p1[1], p2[1]], 'r--')
            self.temp_artists.append(l)
            
        self.fig.canvas.draw()
        
        if len(self.current_points) == 2:
            name = self.popup_input("New Gate", "Enter Gate Name (e.g. N_S0):")
            if name:
                self.gates.append({
                    'name': name, 
                    'p1': self.current_points[0], 
                    'p2': self.current_points[1]
                })
                self.redraw_all()
            self.reset_mode()

    def handle_field_click(self, x, y):
        self.current_points.append((x, y))
        # Visual feedback
        p, = self.ax.plot(x, y, 'cv')
        self.temp_artists.append(p)
        if len(self.current_points) > 1:
            p1, p2 = self.current_points[-2], self.current_points[-1]
            l, = self.ax.plot([p1[0], p2[0]], [p1[1], p2[1]], 'c--')
            self.temp_artists.append(l)
        self.fig.canvas.draw()

    def finish_field(self):
        if len(self.current_points) < 3:
            print("Need at least 3 points.")
            return

        sid = self.popup_input("New Field", "Sensor ID (integer):")
        if not sid or not sid.isdigit(): return
        
        pri = self.popup_input("New Field", "Priority (integer, default 1):")
        if not pri: pri = "1"
        
        self.fields.append({
            'sensor_id': int(sid),
            'priority': int(pri),
            'points': self.current_points
        })
        self.redraw_all()
        self.reset_mode()

    def handle_delete_click(self, x, y):
        # Find nearest object centroid
        threshold = 20.0 # meters proximity
        
        # Check gates
        for i, g in enumerate(self.gates):
            cx = (g['p1'][0] + g['p2'][0]) / 2
            cy = (g['p1'][1] + g['p2'][1]) / 2
            dist = np.sqrt((x-cx)**2 + (y-cy)**2)
            if dist < threshold:
                if messagebox.askyesno("Delete", f"Delete gate '{g['name']}'?"):
                    self.gates.pop(i)
                    self.redraw_all()
                    return

        # Check fields
        for i, f in enumerate(self.fields):
            pts = np.array(f['points'])
            cx, cy = np.mean(pts, axis=0)
            dist = np.sqrt((x-cx)**2 + (y-cy)**2)
            if dist < threshold:
                if messagebox.askyesno("Delete", f"Delete Field S{f['sensor_id']}?"):
                    self.fields.pop(i)
                    self.redraw_all()
                    return

    def redraw_all(self):
        # Clear main axes elements but keep image
        [p.remove() for p in self.ax.patches]
        [l.remove() for l in self.ax.lines]
        [t.remove() for t in self.ax.texts]
        
        self.clear_temp()
        
        # Draw Gates
        for g in self.gates:
            self.ax.plot([g['p1'][0], g['p2'][0]], [g['p1'][1], g['p2'][1]], 'r-', lw=2)
            self.ax.text(g['p1'][0], g['p1'][1], g['name'], color='yellow', fontsize=12, fontweight='bold')

        # Draw Fields
        colors = ['blue', 'green', 'red', 'purple', 'orange']
        for f in self.fields:
            pts = np.array(f['points'])
            sid = f['sensor_id']
            poly = Polygon(pts, closed=True, facecolor=colors[sid % 5], alpha=0.3, edgecolor='white', ls='--')
            self.ax.add_patch(poly)
            cx, cy = np.mean(pts, axis=0)
            self.ax.text(cx, cy, f"S{sid}\n(p{f.get('priority',1)})", color='white', ha='center', fontsize=9)

        self.fig.canvas.draw()

    def clear_temp(self):
        for art in self.temp_artists:
            try: art.remove()
            except: pass
        self.temp_artists = []
        self.fig.canvas.draw()

    def reset_mode(self):
        self.mode = 'idle'
        self.current_points = []
        self.clear_temp()
        self.update_title()

    def on_close(self, event):
        print("Exiting...")

if __name__ == "__main__":
    app = MapAnnotator()