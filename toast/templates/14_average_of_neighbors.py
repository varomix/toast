# Lists: keep the 8 nearest neighbor distances, then store their median.
# Run Over: Points
d = [0.0] * 8
n = 0
for j in nearby_points(0, @position, param("radius", 1.0), 9):
    if j != @index and n < 8:
        d[n] = distance(@position, point_attr(0, "position", j))
        n += 1
# Insertion sort of the first n distances.
for a in range(1, n):
    v = d[a]
    b = a - 1
    while b >= 0 and d[b] > v:
        d[b + 1] = d[b]
        b -= 1
    d[b + 1] = v
@median_distance: float = d[n // 2] if n > 0 else 0.0
