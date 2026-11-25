# Pull points onto the closest surface of the mesh on Input 1.
# Run Over: Points
target = closest_point(1, @position)
@position = lerp(@position, target.position, param("factor", 1.0))
