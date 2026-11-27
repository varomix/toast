# Terrain, shape (Run Over: Points): an island of ridged mountains rising out of rolling hills.
# Stores the height (0 at the sea, about 1 at the top) for the material.
scale = param("scale", 0.22)
height = param("height", 3.0)
seed = param("seed", 3.0)

p = @position * scale + vec3(seed * 13.7, seed * 5.1, 0.0)
# Ridged noise: 1 - |noise| has a sharp crest where the noise crosses zero; each octave is
# weighted by the one before, so the detail gathers on the ridges, as erosion would leave it.
ridges = 0.0
amp = 0.5
freq = 1.0
weight = 1.0
for i in range(7):
    n = 1.0 - abs(signed_noise(p * freq + float(i) * 7.31))
    n = n * n * weight
    weight = clamp(n * 2.0, 0.0, 1.0)
    ridges += n * amp
    freq *= 2.05
    amp *= 0.5
hills = fbm(p * 0.6 + 3.0, 4.0)
# Where the mountains rise: a slow noise, so there are valleys and plains between them.
mask = smoothstep(0.35, 0.6, fbm(p * 0.35 + 11.0, 2.0))
h = lerp(hills * 0.45, ridges * 1.15 + 0.12, mask)
# An island: down to the sea towards the edges, along a coast bent by noise.
r = length(vec2(@position.x, @position.y)) / 5.0 + (fbm(p * 1.5 + 21.0, 3.0) - 0.5) * 0.5
land = smoothstep(0.0, 0.45, 0.95 - r)
h = h * land - 0.12 * (1.0 - land)
@position.z = h * height
@height = h
