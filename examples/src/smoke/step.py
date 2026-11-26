# Smoke, one step (Run Over: Voxels): each voxel looks back along the velocity to where its smoke
# comes from and takes the density and velocity there (semi-Lagrangian advection, all voxels
# read the grids as they were). Then a source puffs smoke in, smoke rises (buoyancy) and curl
# noise stirs it. Blender has no node for "read a grid somewhere else, per voxel": this is
# sample_grid() at a position the code computes.
dt = param("delta_time", 0.0417)
back = @position - @velocity * dt
d = sample_grid(0, "density", back)
v: vec3 = sample_grid(0, "velocity", back)

# The source: a soft ball near the floor that fills with smoke and pushes it up.
src = param("source", (0.0, 0.0, 0.4))
radius = param("source_radius", 0.25)
puff = 1.0 - smoothstep(radius * 0.5, radius, length(@position - src))
d = max(d, puff * param("source_density", 1.0))
v = v + vec3(0, 0, param("source_speed", 2.0)) * puff * dt * 8.0

# Vorticity confinement: push along the swirls, toward where the smoke spins faster, so the
# small eddies that advection blurs keep turning (vorticity.py measured the spin).
h = param("voxel_size", 0.03125)
@vorticity: vec3
w = @vorticity
p = @position
toward = vec3(length(sample_grid(0, "vorticity", p + vec3(h, 0, 0))) - length(sample_grid(0, "vorticity", p - vec3(h, 0, 0))),
              length(sample_grid(0, "vorticity", p + vec3(0, h, 0))) - length(sample_grid(0, "vorticity", p - vec3(0, h, 0))),
              length(sample_grid(0, "vorticity", p + vec3(0, 0, h))) - length(sample_grid(0, "vorticity", p - vec3(0, 0, h))))
toward = toward / (length(toward) + 1e-6)
v = v + cross(toward, w) * param("confinement", 4.0) * h * dt

# Buoyancy, swirl (curl noise, changing over time) and a little drag.
v = v + vec3(0, 0, param("buoyancy", 3.0) * d * dt)
swirl = curl_noise(@position * param("swirl_scale", 1.2) + vec3(0, 0, -@time * 0.6))
v = v + swirl * param("swirl", 4.0) * dt * d
v = v * (1.0 - param("drag", 0.2) * dt)
# Smoke thins out over time, and near the top and sides of the box, so it never shows the box.
d = d * (1.0 - param("fade", 0.3) * dt)
wall = param("walls", 0.875)
side = max(abs(@position.x), abs(@position.y))
d = d * smoothstep(wall, wall - 0.3, side)
@density = d * smoothstep(param("ceiling", 3.5), param("ceiling", 3.5) - 1.4, @position.z)
@velocity = v
