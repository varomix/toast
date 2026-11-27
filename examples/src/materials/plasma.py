# Plasma (Run Over: Shader): domain warping (noise moving noise moving noise) through a cosine
# color palette, flowing with time. Pure light: connect it to an Emission shader.
scale = param("scale", 1.6)
speed = param("speed", 0.25)

p = @object * scale
t = @time * speed
q = vec3(fbm(p + vec3(0.0, 0.0, t), 4.0), fbm(p + vec3(5.2, 1.3, -t), 4.0), fbm(p + vec3(2.1, 7.7, t), 4.0))
r = vec3(fbm(p + q * 4.0 + vec3(1.7, 9.2, t * 1.5), 4.0), fbm(p + q * 4.0 + vec3(8.3, 2.8, -t), 4.0), 0.0)
v = fbm(p + r * 4.0, 5.0)
# Palette: a + b * cos(2 pi (c v + d)).
c = vec3(0.5) + vec3(0.5) * cos(math.tau * (vec3(1.0, 0.7, 0.4) * (v * 1.4 + length(q) * 0.3) + vec3(0.0, 0.15, 0.2)))
c = c * c * smoothstep(0.25, 0.75, v)
output("color", vec4(c.x, c.y, c.z, 1.0))
output("strength", 0.4 + 3.0 * v * v)
