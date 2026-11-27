# Terrain, ground (Run Over: Shader): sand at the shore, grass on gentle slopes (lusher where
# the geometry node found water), rock in layers on steep slopes, snow on high flat ground.
# @height and @wet come from the geometry nodes; the detail is drawn here for every pixel.
snow_line = param("snow_line", 0.62)
rock_slope = param("rock_slope", 0.32)
sea = param("sea", 0.04)

p = @position
n = @normal
h = @height
wet = @wet
slope = 1.0 - n.z
d = fbm(p * 6.0, 5.0)
fine = fbm(p * 40.0, 3.0)

# Rock: layers of sediment, tilted and bent by noise.
strata = sin((p.z * 16.0 + p.x * 0.8 + (fbm(p * 1.2, 3.0) - 0.5) * 6.0) * math.pi)
rock = lerp(vec3(0.13, 0.12, 0.11), vec3(0.3, 0.26, 0.22), strata * 0.35 + 0.5 + (d - 0.5) * 0.6)
rock = rock * lerp(0.7, 1.1, fine)
# Dry yellow grass in patches, lush dark green where it's wet.
dry = smoothstep(0.45, 0.65, fbm(p * 0.8 + 9.0, 3.0))
grass = lerp(vec3(0.08, 0.2, 0.04), vec3(0.36, 0.32, 0.12), dry)
grass = lerp(grass, vec3(0.03, 0.12, 0.03), clamp(wet * 1.4 - 0.3 + (d - 0.5), 0.0, 1.0))
grass = grass * lerp(0.75, 1.15, fine)
sand = vec3(0.62, 0.55, 0.4) * lerp(0.85, 1.05, fine)
snow = vec3(0.92, 0.94, 0.97)

c = grass
is_rock = smoothstep(rock_slope - 0.06, rock_slope + 0.06, slope + (d - 0.5) * 0.25)
c = lerp(c, rock, is_rock)
is_sand = 1.0 - smoothstep(sea + 0.01, sea + 0.04, h + (d - 0.5) * 0.04)
c = lerp(c, sand, is_sand)
# Snow lies on flat ground above the snow line and slides off steep faces.
is_snow = smoothstep(snow_line - 0.04, snow_line + 0.04, h + (d - 0.5) * 0.2) * (1.0 - smoothstep(0.35, 0.55, slope))
c = lerp(c, snow, is_snow)

output("color", vec4(c.x, c.y, c.z, 1.0))
output("roughness", lerp(lerp(0.85, 0.6, is_rock), 0.35, is_snow))
output("height", fine * 0.6 + strata * 0.4 * is_rock)
