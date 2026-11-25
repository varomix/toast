# Drop points straight down onto the mesh connected to Input 1.
# Run Over: Points
hit = ray_cast(1, @position, (0, 0, -1), param("max_distance", 1000.0))
if hit.hit:
    @position = hit.position
    @ground_normal: vec3 = hit.normal
