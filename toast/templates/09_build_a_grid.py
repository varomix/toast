# Build a grid of faces from scratch (Run Over Geometry runs once).
# Run Over: Geometry
size = param("size", 5)
spacing = param("spacing", 0.1)
base = point_count(0)
for y in range(size):
    for x in range(size):
        add_point((x * spacing, y * spacing, 0))
for y in range(size - 1):
    for x in range(size - 1):
        a = base + y * size + x
        add_face((a, a + 1, a + size + 1, a + size))
