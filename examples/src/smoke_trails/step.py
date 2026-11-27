# Smoke trails, one step (Run Over: Voxels, the comets on Input 1): smoke drifts along its
# velocity, spreads to its neighbors, and each comet leaves new smoke along the segment it flew
# this frame. Then the grid follows the smoke: voxels with smoke keep room around them, empty
# ones go.
dt = param("delta_time", 0.0417)
back = @position - @velocity * dt
d = sample_grid(0, "density", back)
vel: vec3 = sample_grid(0, "velocity", back)

# Spread: a little of the average of the six neighbors. grid_voxel() one step from @voxel reads
# arrays the node prepared, not a lookup per read.
v = @voxel
around = (grid_voxel(0, "density", v + vec3(1, 0, 0)) + grid_voxel(0, "density", v - vec3(1, 0, 0))
          + grid_voxel(0, "density", v + vec3(0, 1, 0)) + grid_voxel(0, "density", v - vec3(0, 1, 0))
          + grid_voxel(0, "density", v + vec3(0, 0, 1)) + grid_voxel(0, "density", v - vec3(0, 0, 1)))
d = lerp(d, around / 6.0, param("spread", 0.06))

# New smoke: the distance from this voxel to each comet's segment.
radius = param("trail_radius", 0.07)
for j in range(point_count(1)):
    a: vec3 = point_attr(1, "prev", j)
    b: vec3 = point_attr(1, "position", j)
    ab = b - a
    t = clamp(dot(@position - a, ab) / max(dot(ab, ab), 1e-8), 0.0, 1.0)
    dist = length(@position - (a + ab * t))
    puff = 1.0 - smoothstep(radius * 0.3, radius, dist)
    d = max(d, puff)
    # The comet drags the air along a little.
    vel = vel + ab / dt * puff * param("drag_along", 0.05)

# Swirl, a slow rise, and loss over time.
swirl = curl_noise(@position * param("swirl_scale", 1.3) + vec3(0, 0, @time * 0.3))
vel = vel + swirl * param("swirl", 1.5) * dt + vec3(0, 0, param("rise", 0.4) * d * dt)
vel = vel * (1.0 - param("drag", 0.8) * dt)
d = d * (1.0 - param("fade", 0.35) * dt)
@density = d
@velocity = vel

if d > param("keep", 0.01):
    activate_voxel(@voxel, 2)
else:
    deactivate_voxel(@voxel)
