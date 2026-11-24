"""Join the two ParaView sources into ONE file covering the whole simulated length (lab x = 0 - 0.80 m):
  lab 0 - 0.30 m     : prop1 at 260 us (reconstructed case, constant/ + TIME/polyMesh)
  lab 0.30 - 0.80 m  : prop1_cycle1 at its final save (decomposed case, processor*/TIME), moved +0.30 m
and write it as a compressed .vtu with maxp, T, p, U and the 9 mass fractions.
    pvbatch export_strip_paraview.py PROP1_CASE CYCLE1_CASE OUT.vtu
Both case folders need an empty case.foam file and system/controlDict. maxp is a history and joins without a
seam; the other fields are snapshots of two different times on either side of 0.30 m."""
import os, sys
from paraview.simple import *

p1_case, c1_case, out = sys.argv[1], sys.argv[2], sys.argv[3]
SHIFT = 0.30
FIELDS = ["maxp", "T", "p", "U", "H2", "O2", "H2O", "OH", "H", "O", "HO2", "H2O2", "AR"]

p1 = OpenFOAMReader(FileName=os.path.join(p1_case, "case.foam"))
p1.MeshRegions = ["internalMesh"]; p1.CellArrays = FIELDS
p1.UpdatePipeline(max(p1.TimestepValues))
left = Clip(Input=MergeBlocks(Input=p1))
left.ClipType = "Plane"; left.ClipType.Origin = [SHIFT, 0, 0]; left.ClipType.Normal = [1, 0, 0]
left.Invert = 1; left.Crinkleclip = 1               # whole cells with x < 0.30 (a cell edge)

c1 = OpenFOAMReader(FileName=os.path.join(c1_case, "case.foam"))
c1.CaseType = "Decomposed Case"
c1.MeshRegions = ["internalMesh"]; c1.CellArrays = FIELDS
c1.UpdatePipelineInformation()
c1.UpdatePipeline(max(c1.TimestepValues))
right = Transform(Input=MergeBlocks(Input=c1))
right.Transform.Translate = [SHIFT, 0, 0]

strip = AppendDatasets(Input=[left, right])
strip.UpdatePipeline()
SaveData(out, proxy=strip, CompressorType="LZMA", CompressionLevel=9, DataMode="Appended")
i = strip.GetDataInformation()
print(f"wrote {out}: {os.path.getsize(out) / 1e6:.1f} MB, {i.GetNumberOfCells()} cells, x {i.GetBounds()[0]:.3f}-{i.GetBounds()[1]:.3f} m, "
      f"prop1 t = {max(p1.TimestepValues)}, cycle1 t = {max(c1.TimestepValues)}")
