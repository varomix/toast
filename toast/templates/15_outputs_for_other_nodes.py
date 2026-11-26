# Give other nodes per-point values: a Voronoi distance and a selection.
# Run Over: Points
cell = voronoi(@position * param("scale", 4.0))
output("distance", cell.distance)
output("color", cell.color)
output("near_center", cell.distance < param("threshold", 0.3))
