# ParaView script: opens the whole-length file (lab x = 0 - 0.80 m) as a soot foil with the red marker lines.
#   lab 0 - 0.30 m : prop1 at 260 us  /  0.30 - 0.80 m : prop1_cycle1 at 441.4 us, moved back +0.30 m
#   red lines: 0.30 m (switch from prop1 data to cycle-1 data), 0.474 m (front at the recycle)
# Open (Mac Terminal):
#   open -n -a /Applications/ParaView-6.2.1.app --args --script=$HOME/Documents/Research/repos/ozone_detonation/05_runs/paraview_strip.py
# or in ParaView: View > Python Shell > Run Script. Other fields: the colour drop-down in the toolbar
# (maxp is a history and continuous; the other fields are snapshots of two different times either side of 0.30 m).
import os
from paraview.simple import *

REPO = os.path.expanduser("~/Documents/Research/repos/ozone_detonation")
VTU = os.path.join(REPO, "05_runs/results/prop1_cycle1_441us/paraview/strip_lab_0_800mm.vtu")

strip = XMLUnstructuredGridReader(registrationName="prop1 + cycle1, lab 0-0.80 m", FileName=[VTU])
view = GetActiveViewOrCreate("RenderView")
d = Show(strip, view)
d.SetRepresentationType("Surface")
ColorBy(d, ("CELLS", "maxp"))
lut = GetColorTransferFunction("maxp")
lut.ApplyPreset("Grayscale", True)
lut.InvertTransferFunction()                     # dark = high peak pressure
lut.AutomaticRescaleRangeMode = "Never"
lut.RescaleTransferFunction(1.5e5, 2.46e5)
lut.UseLogScale = 1
GetOpacityTransferFunction("maxp").RescaleTransferFunction(1.5e5, 2.46e5)
d.LookupTable = lut
bar = GetScalarBar(lut, view)
bar.Title = "Peak pressure maxp (Pa)"; bar.ComponentTitle = ""
bar.Orientation = "Horizontal"; bar.WindowLocation = "Lower Center"; bar.Visibility = 1

t = Show(Text(registrationName="label", Text="Soot foil (maxp), lab x:  prop1 at 260 us to 0.30 m  /  cycle 1 at 441.4 us (moved back +0.30 m) from 0.30 m;"
                                              "  recycle at 0.474 m, front at 0.775 m"), view)
t.FontSize = 14; t.WindowLocation = "Upper Left Corner"
for x, name in ((0.30, "0.30 m: prop1 | cycle 1 data"), (0.474, "0.474 m: recycle (front at the cut)")):
    ln = Line(registrationName=name, Point1=[x, -0.004, 0.5], Point2=[x, 0.064, 0.5])
    dl = Show(ln, view); dl.AmbientColor = dl.DiffuseColor = [0.9, 0.1, 0.1]; dl.LineWidth = 2
view.OrientationAxesVisibility = 0
view.CameraParallelProjection = 1
view.AxesGrid.Visibility = 1
view.AxesGrid.XTitle = "x (m), lab"; view.AxesGrid.YTitle = "y (m)"
view.CameraPosition = [0.40, 0.03, 1.0]; view.CameraFocalPoint = [0.40, 0.03, 0.0]; view.CameraViewUp = [0, 1, 0]
view.CameraParallelScale = 0.12
SetActiveSource(strip)
if os.environ.get("SAVE"):
    view.ViewSize = [2400, 700]; view.CameraParallelScale = 0.125
    SaveScreenshot(os.environ["SAVE"], view, ImageResolution=[2400, 700])
else:
    Render(view)
