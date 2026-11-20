"""Visual check of a "cut and append" recycle (recycle_fields.py cut) in ParaView. Runs with pvpython/pvbatch:
    pvbatch compare_cut_paraview.py SOURCE_CASE NEW_CASE SHIFT OUT_DIR
SOURCE_CASE: case with the reconstructed source save (TIME/polyMesh + fields), NEW_CASE: the recycled case
(constant/polyMesh + fields). Both need system/controlDict and an empty case.foam file.
The new case is moved back by +SHIFT in x and drawn in a second view below the source (same camera), so
the kept part must line up cell for cell with the source from x = SHIFT onward. Writes PNG images and prints a numerical comparison."""
import sys
from paraview.simple import *
from paraview import servermanager as sm
from vtk.numpy_interface import dataset_adapter as dsa
import numpy as np

src_case, new_case, shift, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
H = 0.06
GAP = 0.012


def load(case):
    r = OpenFOAMReader(FileName=case + "/case.foam")
    r.MeshRegions = ["internalMesh"]
    r.CellArrays = ["p", "T", "maxp"]
    r.UpdatePipeline(max(r.TimestepValues) if r.TimestepValues else 0)
    return r


src = load(src_case)
new = load(new_case)
new_back = Transform(Input=new)
new_back.Transform.Translate = [shift, 0.0, 0.0]          # back to lab position
for s in (src, new_back):
    s.UpdatePipeline(max(src.TimestepValues))

# ---- numbers: cell centres and p of both, matched by position
def cells(proxy, dx=0.0):
    cc = MergeBlocks(Input=CellCenters(Input=proxy))
    cc.UpdatePipeline(max(src.TimestepValues))
    d = dsa.WrapDataObject(sm.Fetch(cc))
    pts = np.asarray(d.Points)
    p = np.asarray(d.PointData["p"])
    return pts[:, 0] + dx, pts[:, 1], p


xs, ys, ps = cells(src)
xn, yn, pn = cells(new, shift)
key = lambda x, y: (np.round(x / 62.5e-6).astype(np.int64), np.round(y / 62.5e-6).astype(np.int64))  # every cell centre lies on a 62.5 um grid
ks = dict(zip(zip(*key(xs, ys)), ps))
kept = xn < 0.5 + 1e-9
kn = list(zip(*key(xn[kept], yn[kept])))
matched = sum(1 for k in kn if k in ks)
maxdiff = max(abs(ks[k] - v) for k, v in zip(kn, pn[kept]) if k in ks)
src_kept = int(np.sum(xs > shift))
print(f"source cells at x > {shift} m: {src_kept}; new cells that came from there: {int(kept.sum())}; "
      f"same position found in source: {matched}; largest p difference: {maxdiff} Pa")
print(f"new cells beyond the source (appended, lab x > 0.5 m): {int((~kept).sum())}, "
      f"p there {pn[~kept].min()} .. {pn[~kept].max()} Pa")

# ---- pictures: source on top, new (moved back) below, same camera in both views
lut = GetColorTransferFunction("p")
lut.ApplyPreset("Rainbow Uniform", True)
lut.RescaleTransferFunction(6670.0, 2.3e5)
views, reps = [], []
for s_, label in ((src, "source: prop1 at 260 us"),
                  (new_back, "new: prop1_cycle1, drawn moved back +%.2f m (lab x)" % shift)):
    v = CreateView("RenderView")
    v.OrientationAxesVisibility = 0
    v.Background = [1, 1, 1]
    try:
        v.UseColorPaletteForBackground = 0
    except AttributeError:
        pass
    d = Show(s_, v)
    ColorBy(d, ("CELLS", "p"))
    d.LookupTable = lut
    d.EdgeColor = [0.55, 0.55, 0.55]
    t = Show(Text(Text=label), v)
    t.Color = [0, 0, 0]
    t.FontSize = 18
    t.WindowLocation = "Upper Left Corner"
    views.append(v)
    reps.append(d)
bar = GetScalarBar(lut, views[1])
bar.Title = "p (Pa)"
bar.ComponentTitle = ""
bar.TitleColor = bar.LabelColor = [0, 0, 0]
bar.Visibility = 1
layout = CreateLayout("compare")
layout.SplitVertical(0, 0.5)
layout.AssignView(1, views[0])
layout.AssignView(2, views[1])


def shot(name, x0, x1, y0, y1, edges, wpx=1600):
    hpx = int(wpx * (y1 - y0) / (x1 - x0)) + 60
    for v, d in zip(views, reps):
        d.SetRepresentationType("Surface With Edges" if edges else "Surface")
        xc, yc = (x0 + x1) / 2, (y0 + y1) / 2
        v.CameraPosition = [xc, yc, 1.0]
        v.CameraFocalPoint = [xc, yc, 0.0]
        v.CameraViewUp = [0, 1, 0]
        v.CameraParallelProjection = 1
        v.CameraParallelScale = (y1 - y0) / 2 * 1.04
    layout.SetSize(wpx, 2 * hpx)
    SaveScreenshot(f"{out}/{name}", layout, ImageResolution=[wpx, 2 * hpx])
    print(f"wrote {out}/{name}")


shot("cut_compare_full.png", 0.0, 0.8, 0.0, H, False, 2400)              # source 0-0.5 m, new 0.3-0.8 m (lab)
shot("cut_compare_front.png", 0.462, 0.478, 0.022, 0.034, True)          # the front: fine cells must line up
shot("cut_compare_cut.png", 0.296, 0.306, 0.0, 0.006, True)              # lab 0.3 m = new inlet (new starts here)
shot("cut_compare_end.png", 0.494, 0.508, 0.024, 0.032, True)            # old outlet -> appended fresh cells
