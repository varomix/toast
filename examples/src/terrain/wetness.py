# Terrain, wetness (Run Over: Points): water gathers in hollows and low ground. A point lower
# than its neighbors' average is in a hollow; the second ring of neighbors widens the view.
reach = param("reach", 0.08)

around = 0.0
n = 0
for q in point_neighbors(0, @index, 8):
    for r in point_neighbors(0, q, 8):
        other: vec3 = point_attr(0, "position", r)
        around += other.z
        n += 1
hollow = (around / max(float(n), 1.0) - @position.z) / reach
low = 1.0 - smoothstep(0.05, 0.35, @height)
@wet = clamp(hollow * 0.5 + 0.5, 0.0, 1.0) * 0.7 + low * 0.3
