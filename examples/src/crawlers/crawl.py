# Crawlers, one frame (Run Over: Curves, a volume with the shape's SDF on Input 1): each curve's
# tip is a crawler. It circles the shape, wiggled by curl noise, with the part that points off
# the surface taken out (the SDF's gradient is the surface's normal), then steps back onto the
# surface by the distance the SDF gives. Its trail is the curve: extend_curve() adds the new tip, and the
# oldest point goes once the trail is long enough.
tip = 0
root = 0
n = 0
for p in curve_points(0, @index, 4096):
    if n == 0:
        root = p
    tip = p
    n += 1
here: vec3 = point_attr(0, "position", tip)

normal = normalize(grid_gradient(1, "sdf", here))
# Around the shape (along the surface, across "up"), wiggled by curl noise.
around = cross(normal, vec3(0, 0, 1)) * param("around", 1.0)
flow = around + curl_noise(here * param("scale", 2.5) + vec3(0, 0, @time * param("evolve", 0.2))) * param("wiggle", 0.6)
flow = flow - normal * dot(flow, normal)
step = here + normalize(flow + vec3(1e-6, 0, 0)) * param("speed", 0.012)

# Back onto the surface, hovering a little above it.
gap = sample_grid(1, "sdf", step) - param("hover", 0.02)
step = step - normalize(grid_gradient(1, "sdf", step)) * gap
extend_curve(@index, step)
if n >= param("trail", 60):
    remove_point(root)
@hue: float = random(@index, 7)
