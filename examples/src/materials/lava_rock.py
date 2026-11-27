# Lava rock (Run Over: Shader): dark basalt broken into cells (the toast_lib.cells library), with
# molten light in the cracks that breathes over time.
from toast_lib.cells import cells

scale = param("scale", 3.0)
width = param("width", 0.09)
glow = param("glow", 1.6)

p = @object * scale
c = cells(p + (fbm(p * 0.7, 3.0) - 0.5) * 0.6, 1.0)
edge = c.y - c.x
crack = 1.0 - smoothstep(0.0, width, edge)
# The heat in each crack rises and falls slowly, differently from place to place.
heat = crack * (0.45 + 0.55 * noise(p * 0.6 + vec3(0.0, 0.0, @time * 0.4)))

rock = lerp(vec3(0.035, 0.03, 0.028), vec3(0.11, 0.09, 0.08), fbm(p * 4.0, 5.0) * 0.6 + c.z * 0.4)
hot = lerp(vec3(1.0, 0.05, 0.0), vec3(1.0, 0.35, 0.0), heat * heat)
output("color", vec4(rock.x, rock.y, rock.z, 1.0))
output("emission", vec4(hot.x, hot.y, hot.z, 1.0))
output("strength", heat * glow)
output("height", smoothstep(0.0, width * 2.5, edge) + fbm(p * 6.0, 4.0) * 0.3)
output("roughness", lerp(0.85, 0.4, crack))
