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
@vorticity: vec3
w = @vorticity
i = @voxel
toward = vec3(length(grid_voxel(0, "vorticity", i + vec3(1, 0, 0))) - length(grid_voxel(0, "vorticity", i - vec3(1, 0, 0))),
              length(grid_voxel(0, "vorticity", i + vec3(0, 1, 0))) - length(grid_voxel(0, "vorticity", i - vec3(0, 1, 0))),
              length(grid_voxel(0, "vorticity", i + vec3(0, 0, 1))) - length(grid_voxel(0, "vorticity", i - vec3(0, 0, 1))))
toward = toward / (length(toward) + 1e-6)
v = v + cross(toward, w) * param("confinement", 4.0) * @voxel_size.x * dt

# Buoyancy, swirl (curl noise, changing over time) and a little drag.
v = v + vec3(0, 0, param("buoyancy", 3.0) * d * dt)
swirl = curl_noise(@position * param("swirl_scale", 1.2) + vec3(0, 0, -@time * 0.6))
v = v + swirl * param("swirl", 4.0) * dt * d
v = v * (1.0 - param("drag", 0.2) * dt)
d = d * (1.0 - param("fade", 0.4) * dt)
@density = d
@velocity = v

# The grid follows the smoke: voxels with smoke keep `margin` voxels around them active (room to
# flow into next step), the others go. Up to a ceiling, so it can't grow forever.
if d > param("keep", 0.02) and @position.z < param("ceiling", 6.0):
    activate_voxel(@voxel, param("margin", 3))
else:
    deactivate_voxel(@voxel)
