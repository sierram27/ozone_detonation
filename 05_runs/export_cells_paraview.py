"""Laptop replacement for steps [1]-[2] of analyze.slurm: read a *decomposed* run (processor*/TIME) with
ParaView, no OpenFOAM and no reconstruction needed, and write the cell centres and fields that
analyze_prop.py reads (Ccx Ccy maxp p T cellLevel) into OUT_DIR.
    pvpython export_cells_paraview.py CASE_DIR TIME OUT_DIR
CASE_DIR needs processor*/TIME (with polyMesh), processor*/constant, system/controlDict and an empty
case.foam file. Reads only."""
import os, sys
from paraview.simple import OpenFOAMReader, CellCenters, MergeBlocks
from paraview import servermanager as sm
from vtk.numpy_interface import dataset_adapter as dsa
import numpy as np

case, time, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
os.makedirs(out, exist_ok=True)
r = OpenFOAMReader(FileName=os.path.join(case, "case.foam"))
r.CaseType = "Decomposed Case"
r.MeshRegions = ["internalMesh"]
r.CellArrays = ["maxp", "p", "T", "cellLevel"]
r.UpdatePipelineInformation()
times = list(r.TimestepValues)
t = min(times, key=lambda v: abs(v - time))
if abs(t - time) > 1e-12:
    sys.exit(f"ERROR: time {time} not found; available: {times[-5:]}")
cc = MergeBlocks(Input=CellCenters(Input=r))
cc.UpdatePipeline(t)
d = dsa.WrapDataObject(sm.Fetch(cc))
pts = np.asarray(d.Points)
data = {"Ccx": pts[:, 0], "Ccy": pts[:, 1]}
for k in ("maxp", "p", "T", "cellLevel"):
    data[k] = np.asarray(d.PointData[k])
n = pts.shape[0]
for k, v in data.items():
    with open(os.path.join(out, k), "w") as f:
        f.write(f"// {k} at t = {t} from {case} (ParaView, decomposed)\ninternalField nonuniform List<scalar>\n{n}\n(\n")
        f.write("\n".join(repr(float(x)) for x in v))
        f.write("\n)\n;\n")
print(f"t = {t}: {n} cells; x {pts[:, 0].min():.6f} .. {pts[:, 0].max():.6f} m; "
      f"maxp max {data['maxp'].max():.1f} Pa; levels {sorted(set(int(x) for x in data['cellLevel']))}; wrote {out}")
