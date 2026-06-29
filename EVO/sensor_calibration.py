"""
SENSOR CALIBRATION OPTIMIZATION
================================

Calculates optimal rigid transformation (rotation + translation) to align
Sensor 1 to Sensor 0 using isolated vehicle pairs.

Output:
- Recommended azimuth adjustment (degrees)
- Recommended X, Y translation (meters)
- Simple visualization showing raw S0, raw S1, and adjusted S1
"""

import pandas as pd
import numpy as np
import json
import plotly.graph_objects as go
from scipy.optimize import minimize

# Import functions from main fusion script
import sys
sys.path.insert(0, '.')
from claude_latest import parse_xml_config, parse_and_align_data

# ============================================================================
# CONFIGURATION
# ============================================================================
INT_DIR = "../sites/85_US95&PalouseRiver/"
XML_FILE = INT_DIR + "US95_PalouseRiverDr.iprj"#"us95&sh8_iprj.txt"
DATA_FILE = INT_DIR + "10_37_2_85_EVO_1770312209.txt"

ISOLATION_RADIUS = 15.0    # meters - vehicles must be this far from others
COARSE_MATCH_DIST = 10.0   # meters - max distance for pairing S0/S1 detections
MIN_PAIRS = 50             # minimum pairs needed for calibration

# ============================================================================

def find_calibration_pairs(df):
    """
    Find isolated vehicle pairs between S0 and S1.
    Returns: list of (s0_x, s0_y, s1_x, s1_y) tuples
    """
    print("\n--- Finding Calibration Pairs ---")
    
    df = df.sort_values('Time')
    times = df['Time'].unique()
    
    pairs = []
    calib_frames = times[::5]  # Sample every 5th frame
    
    print(f"   Scanning {len(calib_frames)} frames...")
    
    for t in calib_frames:
        frame = df[df['Time'] == t]
        if len(frame) < 2:
            continue
        
        s0_objs = frame[frame['Sensor'] == 0]
        s1_objs = frame[frame['Sensor'] == 1]
        
        if s0_objs.empty or s1_objs.empty:
            continue
        
        # Check each S0 object
        for _, s0_row in s0_objs.iterrows():
            x0, y0 = s0_row['X'], s0_row['Y']
            
            # Isolation check - no other S0 objects nearby
            s0_dists = np.sqrt((s0_objs['X'] - x0)**2 + (s0_objs['Y'] - y0)**2)
            if np.sum(s0_dists < ISOLATION_RADIUS) > 1:
                continue
            
            # Find closest S1 object
            dists = np.sqrt((s1_objs['X'] - x0)**2 + (s1_objs['Y'] - y0)**2)
            min_idx = dists.idxmin()
            min_dist = dists[min_idx]
            
            if min_dist < COARSE_MATCH_DIST:
                s1_row = s1_objs.loc[min_idx]
                x1, y1 = s1_row['X'], s1_row['Y']
                
                # Check S1 isolation too
                s1_dists = np.sqrt((s1_objs['X'] - x1)**2 + (s1_objs['Y'] - y1)**2)
                if np.sum(s1_dists < ISOLATION_RADIUS) > 1:
                    continue
                
                pairs.append((x0, y0, x1, y1))
    
    print(f"   Found {len(pairs)} isolated pairs")
    return pairs


def apply_rigid_transform(points, theta, tx, ty):
    """
    Apply rigid transformation: rotation by theta (radians) + translation (tx, ty)
    points: Nx2 array of (x, y) coordinates
    """
    # Rotation matrix
    cos_t = np.cos(theta)
    sin_t = np.sin(theta)
    
    # Apply rotation then translation
    x_rot = points[:, 0] * cos_t - points[:, 1] * sin_t
    y_rot = points[:, 0] * sin_t + points[:, 1] * cos_t
    
    x_final = x_rot + tx
    y_final = y_rot + ty
    
    return np.column_stack([x_final, y_final])


def optimize_alignment(pairs):
    """
    Find optimal rotation and translation to align S1 to S0.
    Returns: (theta_deg, tx, ty, residual_error)
    """
    print("\n--- Optimizing Alignment ---")
    
    s0_points = np.array([(p[0], p[1]) for p in pairs])
    s1_points = np.array([(p[2], p[3]) for p in pairs])
    
    def objective(params):
        """Sum of squared distances after transformation"""
        theta, tx, ty = params
        s1_transformed = apply_rigid_transform(s1_points, theta, tx, ty)
        errors = np.sqrt(np.sum((s0_points - s1_transformed)**2, axis=1))
        return np.sum(errors**2)
    
    # Initial guess: no rotation, translation = mean offset
    dx_init = np.mean(s0_points[:, 0] - s1_points[:, 0])
    dy_init = np.mean(s0_points[:, 1] - s1_points[:, 1])
    x0 = [0.0, dx_init, dy_init]  # theta, tx, ty
    
    # Optimize
    result = minimize(objective, x0, method='Powell')
    
    theta_opt, tx_opt, ty_opt = result.x
    theta_deg = np.degrees(theta_opt)
    
    # Calculate residual error
    s1_transformed = apply_rigid_transform(s1_points, theta_opt, tx_opt, ty_opt)
    errors = np.sqrt(np.sum((s0_points - s1_transformed)**2, axis=1))
    mean_error = np.mean(errors)
    max_error = np.max(errors)
    
    res_string = "Optimization complete:\n"+\
    f" Azimuth adjustment: {theta_deg:.3f}°\n" +\
    f" X translation: {tx_opt:.3f} m\n" +\
    f" Y translation: {ty_opt:.3f} m\n" +\
    f" Mean residual error: {mean_error:.3f} m\n" +\
    f" Max residual error: {max_error:.3f} m"

    with open(INT_DIR + "calibration_results.txt", "w") as file:
        file.write(res_string)
    
    return theta_deg, tx_opt, ty_opt, mean_error


def plot_calibration(df, pairs, theta_deg, tx, ty, bg_image, config):
    """
    Create animated frame-by-frame visualization showing:
    - Raw S0 (blue)
    - Raw S1 (red)
    - Adjusted S1 (green)
    """
    print("\n--- Creating Visualization ---")
    
    # Apply transformation to all S1 data
    s1_mask = df['Sensor'] == 1
    if s1_mask.any():
        s1_points = df.loc[s1_mask, ['X', 'Y']].values
        theta_rad = np.radians(theta_deg)
        s1_adjusted = apply_rigid_transform(s1_points, theta_rad, tx, ty)
        
        # Create adjusted S1 dataframe
        df_s1_adj = df[s1_mask].copy()
        df_s1_adj['X'] = s1_adjusted[:, 0]
        df_s1_adj['Y'] = s1_adjusted[:, 1]
        df_s1_adj['Sensor'] = 2  # Use sensor ID 2 for adjusted S1
    else:
        df_s1_adj = pd.DataFrame()
    
    # Combine all data
    df_plot = pd.concat([df, df_s1_adj], ignore_index=True)
    
    # Add color coding
    color_map = {0: 'blue', 1: 'red', 2: 'lime'}
    df_plot['ColorVal'] = df_plot['Sensor'].map(color_map)
    
    # Add labels
    label_map = {0: 'S0 (Raw)', 1: 'S1 (Raw)', 2: f'S1 (Adjusted: {theta_deg:.2f}°)'}
    df_plot['SensorLabel'] = df_plot['Sensor'].map(label_map)
    
    # Convert time to relative display
    min_time = df_plot['Time'].min()
    df_plot['TimeDisplay'] = df_plot['Time'].apply(lambda t: f"{(t - min_time):.1f}s")
    
    # Downsample for performance
    unique_times = df_plot['Time'].unique()
    sample_times = unique_times[::5][:200]  # Every 5th frame, max 200 frames
    df_plot = df_plot[df_plot['Time'].isin(sample_times)].copy()
    
    print(f"   Frames: {len(df_plot['Time'].unique())}")
    print(f"   Total points: {len(df_plot)}")
    
    # Create animated scatter plot
    import plotly.express as px
    
    fig = px.scatter(
        df_plot,
        x='X', y='Y',
        animation_frame='TimeDisplay',
        animation_group='ID',
        color='ColorVal',
        hover_name='SensorLabel',
        color_discrete_map='identity',
        title=f"Sensor Calibration Analysis<br><sub>Azimuth: {theta_deg:.3f}°, Translation: ({tx:.2f}m, {ty:.2f}m)</sub>"
    )
    
    fig.update_traces(marker=dict(size=8, opacity=0.8, line=dict(width=0.5, color='black')))
    
    # Add background
    w = config.get('width', 1000) * config.get('scale', 0.1)
    h = config.get('height', 1000) * config.get('scale', 0.1)
    
    fig.update_layout(
        images=[dict(source=bg_image, xref="x", yref="y", x=0, y=0, sizex=w, sizey=h,
                    sizing="stretch", opacity=0.6, layer="below")],
        xaxis=dict(range=[0, w], showgrid=True, zeroline=False, visible=True),
        yaxis=dict(range=[h, 0], showgrid=True, zeroline=False, visible=True, scaleanchor="x", scaleratio=1),
        template="plotly_dark",
        height=800,
        hovermode='closest'
    )
    
    # Set animation speed
    if fig.layout.updatemenus:
        fig.layout.updatemenus[0].buttons[0].args[1]["frame"]["duration"] = 100

    fig.write_html(INT_DIR + "sensor_calibration.html")
    print("   ✓ Saved to sensor_calibration.html")


def main():
    print("="*70)
    print("SENSOR CALIBRATION OPTIMIZATION")
    print("="*70)
    
    # Load configuration and data
    config, bg_image = parse_xml_config(XML_FILE)
    df = parse_and_align_data(DATA_FILE, config)
    
    if df.empty:
        print("ERROR: No data loaded")
        return
    
    # Find calibration pairs
    pairs = find_calibration_pairs(df)
    
    if len(pairs) < MIN_PAIRS:
        print(f"\n⚠️ Warning: Only found {len(pairs)} pairs (need {MIN_PAIRS} minimum)")
        print("   Continuing anyway, but results may be unreliable...")
    
    # Optimize alignment
    theta_deg, tx, ty, error = optimize_alignment(pairs)
    
    # Create visualization
    plot_calibration(df, pairs, theta_deg, tx, ty, bg_image, config)
    
    # Summary
    print("\n" + "="*70)
    print("CALIBRATION RECOMMENDATIONS")
    print("="*70)
    print(f"Adjust Sensor 1 configuration:")
    print(f"  Azimuth: ADD {theta_deg:.3f}° to current value")
    print(f"  X position: ADD {tx:.3f} meters")
    print(f"  Y position: ADD {ty:.3f} meters")
    print(f"\nExpected improvement: {error:.3f}m mean alignment error")
    print("="*70)


if __name__ == "__main__":
    main()