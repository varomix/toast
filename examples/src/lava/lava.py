# Lava, shading (Run Over: Shader): @lava and @heat come from the simulation. Hot lava is open
# and bright; as it cools a dark crust forms in plates (toast_lib.cells) whose cracks glow and
# close; cold lava is black rock. Bare ground is ash and stone.
from toast_lib.cells import cells

glow = param("glow", 2.0)
size = param("size", 11.0)

heat = @heat
lava = @lava
p = @position
is_lava = smoothstep(0.002, 0.012, lava)

# Crust plates, stretched a little by noise; the cracks between them open with the heat.
c = cells(p * size + (fbm(p * 2.0, 3.0) - 0.5) * 1.5, 1.0)
edge = c.y - c.x
crack = 1.0 - smoothstep(0.0, lerp(0.02, 0.35, heat * heat), edge)
molten = smoothstep(0.75, 0.95, heat + (noise(p * 5.0) - 0.5) * 0.2)
hot = clamp(max(crack, molten), 0.0, 1.0) * smoothstep(0.08, 0.35, heat) * is_lava

# Color of the light by temperature: deep red, orange, yellow.
t = heat * (0.8 + 0.2 * noise(p * 12.0))
light = lerp(vec3(0.8, 0.04, 0.0), vec3(1.0, 0.35, 0.02), smoothstep(0.2, 0.6, t))
light = lerp(light, vec3(1.0, 0.55, 0.1), smoothstep(0.75, 1.0, t))

crust = vec3(0.03, 0.028, 0.026) * lerp(0.6, 1.4, fbm(p * 30.0, 3.0)) + c.z * 0.02
ash = lerp(vec3(0.16, 0.14, 0.12), vec3(0.3, 0.27, 0.23), fbm(p * 3.0, 5.0))
col = lerp(ash, crust, is_lava) * (1.0 - hot)
output("color", vec4(col.x, col.y, col.z, 1.0))
output("emission", vec4(light.x, light.y, light.z, 1.0))
output("strength", hot * glow * (0.3 + t * t))
output("roughness", lerp(lerp(0.9, 0.55, is_lava), 0.3, hot))
output("height", (smoothstep(0.0, 0.12, edge) * 0.6 + fbm(p * 30.0, 3.0) * 0.4) * is_lava + fbm(p * 8.0, 4.0) * (1.0 - is_lava))
