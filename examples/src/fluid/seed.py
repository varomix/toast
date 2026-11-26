# Fluid, step 1 (Run Over: Points): stack the particles in a tall column at one end of the tank
# (a "dam break"), a little jittered.
spacing = param("spacing", 0.05)
side = param("side", 18)                     # particles along x and y
i = @index
x = i % side
y = (i // side) % side
z = i // (side * side)
jitter = (vec3(random(i, 1), random(i, 2), random(i, 3)) - 0.5) * spacing * 0.2
@position = param("corner", (-1.15, -0.42, 0.05)) + vec3(x, y, z) * spacing + jitter
@velocity = (0, 0, 0)
