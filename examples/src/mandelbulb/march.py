# Mandelbulb (Run Over: Points): every point of a grid is a pixel. It shoots a ray from the
# eye through itself, ray-marches the fractal (up to max_steps distance estimates, each up to
# `iterations` fractal iterations), and moves onto the surface it hits, or is removed.
# Shading: surface normal from 6 more estimates, ambient occlusion from the step count.
# This is the heavy-math test: hundreds of thousands of points x hundreds of iterations each.
from toast_lib.fractal import mandelbulb

eye = param("eye", (0.0, -3.2, 0.0))
focal = param("focal", 2.6)              # how far the grid stands in front of the eye
power = param("power", 8.0) + param("power_wobble", 1.0) * sin(@time * 0.5)
iterations = param("iterations", 8)
max_steps = param("max_steps", 96)
# The grid lies on the XY plane; stand it up in front of the eye.
pixel = vec3(@position.x, eye.y + focal, @position.y)
ray = normalize(pixel - eye)

t = 0.0
hit = False
steps = 0
de = vec2(0, 0)
for s in range(max_steps):
    de = mandelbulb(eye + ray * t, power, iterations)
    if de.x < 0.0005 * t:
        hit = True
        break
    t += de.x
    steps += 1
    if t > 6.0:
        break
if not hit:
    remove_point(@index)
    return

p = eye + ray * t
e = 0.0005 * t
n = normalize(vec3(
    mandelbulb(p + (e, 0, 0), power, iterations).x - mandelbulb(p - (e, 0, 0), power, iterations).x,
    mandelbulb(p + (0, e, 0), power, iterations).x - mandelbulb(p - (0, e, 0), power, iterations).x,
    mandelbulb(p + (0, 0, e), power, iterations).x - mandelbulb(p - (0, 0, e), power, iterations).x))
occlusion = 1.0 - float(steps) / max_steps
light = clamp(dot(n, normalize(param("light", (0.6, -0.8, 0.9)))), 0.0, 1.0)
# Color from the orbit trap, with a cosine palette.
trap = de.y * param("color_scale", 1.6) + param("color_shift", 0.1)
base = vec3(0.5, 0.5, 0.5) + vec3(0.5, 0.45, 0.4) * cos((vec3(trap, trap, trap) + (0.0, 0.15, 0.3)) * math.tau)
@position = p
@normal = n
# Far points cover more of the image: size each one to fill its pixel.
@radius = t * param("pixel", 0.008) / focal * 0.8
@color = base * (0.25 + 0.75 * light) * occlusion
output("occlusion", occlusion)
