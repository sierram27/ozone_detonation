# ParaView startup script (runs on your Mac, not on Stampede3).
# Loads one VTK file written by to_vtk.slurm and shows maxp (peak-pressure history), whose
# dark lines are the triple-point tracks of the detonation cells.
#
# Usage (Mac terminal; VTK_FILE = the big .vtk file directly inside the VTK/ folder):
#   VTK_FILE=$HOME/Documents/Research/repos/ozone_detonation/local_data/prop1_vtk_0.0002/VTK/prop1_34863.vtk \
#     /Applications/ParaView-6.2.1.app/Contents/MacOS/paraview --script=$HOME/Documents/Research/repos/ozone_detonation/05_runs/paraview_maxp.py
#
# Do not use "open -a ParaView file.vtk": ParaView 6.2.1 does not load files passed that way
# ("No proxy that matches: group= and proxy= were found").
import os
from paraview.simple import *

path = os.environ["VTK_FILE"]
r = LegacyVTKReader(registrationName=os.path.basename(path), FileNames=[path])
v = GetActiveViewOrCreate("RenderView")
d = Show(r, v)
ColorBy(d, ("CELLS", "maxp"))
lut = GetColorTransferFunction("maxp")
lut.ApplyPreset("Grayscale", True)
lut.InvertTransferFunction()               # dark = high peak pressure
lut.AutomaticRescaleRangeMode = "Never"    # keep the range below
lut.RescaleTransferFunction(1.5e5, 3.3e5)  # positive range first...
lut.UseLogScale = 1                        # ...then log scale (a range from 0 gives a warning)
d.SetScalarBarVisibility(v, True)
v.InteractionMode = "2D"
v.ResetActiveCameraToNegativeZ()
v.ResetCamera()
Render()
