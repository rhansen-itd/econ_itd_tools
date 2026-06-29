# econ_itd_tools

A loose collection of standalone scripts for working with Econolite EOS traffic
signal controllers and EVO radar units. There is no shared package or library
code here — each tool is independent and can be run on its own. They're grouped
by which device they talk to.

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run scripts from inside `EOS/` or `EVO/` (their `INT_DIR` config blocks are
relative to that directory, pointing at `../sites/<intersection>/`).

## EOS/ — Econolite EOS controller tools

- `eos_set_time.py` — sets the clock on an EOS controller over its front-panel
  WebSocket interface; can be run directly or scheduled via cron.
- `eos_read_phase_state.py` — reads active signal phases from an EOS controller
  over WebSocket.
- `eos_nav_debug.txt` — diagnostic capture log written by `eos_set_time.py`.
- `eos.ipynb` — early exploratory notebook for the EOS WebSocket protocol.
- `legacy/_eos_set_time.py` — superseded draft of `eos_set_time.py`.

## EVO/ — EVO radar tools

- `fusion_visualizer.py` — the main tool: fuses multi-sensor EVO radar tracks,
  learns common vehicle paths through an intersection, applies spatial bias
  correction, and renders HTML/MP4 visualizations. Configure via the `INT_DIR`
  block at the top of the file to point at a folder under `../sites/`.
- `gate_field_draw.py` — interactive tool for drawing movement gates and trusted
  sensor field polygons on an intersection map (used as input to the tools above).
- `evo_recorder.py` / `evo_recorder_multi.py` — capture live raw radar track data
  from one or more EVO sensors over WebSocket.
- `sensor_calibration.py` — computes the rigid transform (rotation + translation)
  to align one sensor's tracks to another's, for multi-sensor calibration.
- `same_sensor_tmc_counter.py` — counts intersection turning movements from raw
  gate crossings (no fusion/stitching).
- `dxf_iprj_excel_conv.py` — converts EVO `.iprj` project files and `.dxf`
  drawings to/from Excel for editing sensor and detection-zone configuration.
- `EVO_plotter.ipynb`, `EVO recorder.ipynb`, `dxf_xlsx_iprj.ipynb` — exploratory
  notebooks that preceded the `.py` tools above.
- `legacy/` — earlier AI-assisted iterations of `fusion_visualizer.py` and
  `gate_field_draw.py` (named after the model that wrote each draft), kept for
  reference but superseded.

## sites/

Per-intersection working data (raw radar captures, `.iprj` configs, generated
gates/fields/path-template/spatial-model files, and exported `.xlsx`/background
images). Each subfolder is one intersection; tools read/write within the
relevant site folder via their `INT_DIR` config.
