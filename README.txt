X1X Harness 3D Topology - Source Code Package (2026-09-27)
===========================================================

Contents:
  harness_3d/
    harness_topology.py  - Main analysis: STEP -> topology.json
    report_xlsx.py       - topology.json -> Excel report
    viz_topology.py      - topology.json -> 3D PNG
    tests/               - 50 topology tests + 10 report tests
    requirements.txt     - Python dependencies

Usage (Windows):
  1. Install Python 3.10+ from python.org (check "Add to PATH")
  2. pip install -r harness_3d/requirements.txt
  3. Run analysis:
       python harness_3d/harness_topology.py X1X-DRD_AllCATPart.stp 3.0
     (outputs topology.json in current dir)
  4. Generate Excel:
       python harness_3d/report_xlsx.py topology.json
     (outputs report.xlsx)
  5. Generate 3D plot:
       python harness_3d/viz_topology.py topology.json
     (outputs topology_3d.png)
  6. Run tests:
       python harness_3d/tests/test_topology_logic.py
       python harness_3d/tests/test_report_new.py

If you already have the portable_app from before:
  Just overwrite the .py files in portable_app with these new ones,
  then run with portable_app/python/python.exe instead of python.

Instance name mapping (CATIA product tree):
  Edit INSTANCE_MAP at the top of report_xlsx.py to add/correct
  STEP tag -> instance full name entries.
