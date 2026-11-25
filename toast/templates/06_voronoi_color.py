# Color by Voronoi cell, and store the distance to the cell's center.
# Run Over: Points
cell = voronoi(@position * param("scale", 4.0))
@color = cell.color
@cell_distance: float = cell.distance
