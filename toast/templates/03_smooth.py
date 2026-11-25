# Move each point toward the average of its neighbors.
# Run Over: Points
total = vec3(0, 0, 0)
count = 0
for q in point_neighbors(0, @index, 32):
    total += point_attr(0, "position", q)
    count += 1
if count > 0:
    @position = lerp(@position, total / count, param("strength", 0.5))
