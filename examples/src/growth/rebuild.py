# Differential growth, parallel version, step 2 (Run Over: Geometry). Walks the loop once, in
# order: puts every point at its @next position (from move.py), adds a point in the middle of
# edges that got too long, and reconnects the loop. Only this walk is sequential, and it does
# almost nothing per point.
n = point_count(0)
split = param("split_length", 0.035)
max_points = param("max_points", 12000)

base = n
added = 0
first = vec3(0, 0, 0)
last = vec3(0, 0, 0)
can_split = n < max_points
for i in range(n):
    np: vec3 = point_attr(0, "next", i)
    if i > 0 and can_split and distance(last, np) > split:
        add_point((last + np) * 0.5)
        added += 1
    add_point(np)
    added += 1
    if i == 0:
        first = np
    last = np
if can_split and distance(last, first) > split:
    add_point((last + first) * 0.5)
    added += 1
for k in range(added):
    add_edge(base + k, base + (k + 1) % added)
for i in range(n):
    remove_point(i)
