# Text "toast_lib.fractal": distance estimate of a Mandelbulb (a Toast library).

def mandelbulb(p: vec3, power, iterations):
    """Returns (distance to the surface, orbit trap): a lower bound of the distance, and how close
    the orbit came to the origin, for coloring."""
    z = p
    dr = 1.0
    r = length(z)
    trap = 1000.0
    for i in range(iterations):
        r = length(z)
        if r > 2.0:
            break
        if r < 1e-6:
            r = 1e-6
        theta = acos(clamp(z.z / r, -1.0, 1.0)) * power
        phi = atan2(z.y, z.x) * power
        dr = pow(r, power - 1.0) * power * dr + 1.0
        zr = pow(r, power)
        z = vec3(sin(theta) * cos(phi), sin(phi) * sin(theta), cos(theta)) * zr + p
        trap = min(trap, length(z))
    return vec2(0.5 * log(r) * r / dr, trap)
