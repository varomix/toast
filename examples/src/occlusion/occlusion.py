# Ambient occlusion and dust (Run Over: Points): every point shoots `rays` rays over the
# hemisphere around its normal with ray_cast() against the whole scene (Input 0 itself), and
# counts how many escape. Few escape in creases and under objects: dark. Rays that escape
# upward bring dust: upward-facing, open places get dusty, in drifts.
# Blender's nodes can't loop over rays; here it is a for loop, on every core.
rays = param("rays", 48, min=1, max=512)
reach = param("reach", 1.5)                 # rays longer than this count as escaped
seed = param("seed", 0)

n = normalize(@normal)
# A frame around the normal: tangent t, bitangent b.
up = vec3(0, 0, 1) if abs(n.z) < 0.9 else vec3(1, 0, 0)
t = normalize(cross(up, n))
b = cross(n, t)
origin = @position + n * 0.002
# Each point turns the same spiral of directions by its own random angle: no banding, and
# neighbors still see slightly different rays (the noise averages out under smooth shading).
spin = random(@index, seed) * math.tau
golden = math.pi * (3.0 - sqrt(5.0))

open_sum = 0.0
sky = 0.0
for i in range(rays):
    # Cosine-weighted hemisphere: points of a disc (Fibonacci spiral) lifted onto the sphere.
    r = sqrt((i + 0.5) / rays)
    a = i * golden + spin
    d = t * (r * cos(a)) + b * (r * sin(a)) + n * sqrt(max(0.0, 1.0 - r * r))
    hit = ray_cast(0, origin, d, reach)
    if not hit.hit:
        open_sum += 1.0
        sky += max(d.z, 0.0)
    else:
        # A far hit occludes less than a near one.
        open_sum += hit.distance / reach * 0.5

openness = open_sum / rays
dust = smoothstep(param("dust_start", 0.35), param("dust_end", 0.6), sky / rays) * smoothstep(0.2, 0.7, n.z)
# Wind leaves it in drifts: patches from fbm noise.
dust *= smoothstep(0.35, 0.75, fbm(@position * param("drift_scale", 2.5), detail=4)) * param("dust", 0.6)

@occlusion: float = 1.0 - openness
@dust: float = dust
albedo = param("albedo", (0.55, 0.32, 0.22))
dust_color = param("dust_color", (0.85, 0.82, 0.74))
ao = pow(openness, param("contrast", 2.0))
@color = lerp(albedo, dust_color, dust) * ao
