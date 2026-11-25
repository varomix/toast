# Give each instance a random turn around Z and a random scale.
# Run Over: Instances
seed = param("seed", 0)
angle = random(@index, seed) * math.tau
s = map_range(random(@index, seed + 1), 0, 1, param("min_scale", 0.5), param("max_scale", 1.5))
@transform = @transform * mat4_compose((0, 0, 0), quat_axis_angle((0, 0, 1), angle), s)
