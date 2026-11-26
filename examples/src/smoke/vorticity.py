# Smoke, vorticity (Run Over: Voxels): how fast the smoke spins at each voxel (the curl of the
# velocity, from the six neighbors). step.py uses it to keep small swirls alive that the
# advection would blur away (vorticity confinement).
h = param("voxel_size", 0.03125)
px: vec3 = sample_grid(0, "velocity", @position + vec3(h, 0, 0))
nx: vec3 = sample_grid(0, "velocity", @position - vec3(h, 0, 0))
py: vec3 = sample_grid(0, "velocity", @position + vec3(0, h, 0))
ny: vec3 = sample_grid(0, "velocity", @position - vec3(0, h, 0))
pz: vec3 = sample_grid(0, "velocity", @position + vec3(0, 0, h))
nz: vec3 = sample_grid(0, "velocity", @position - vec3(0, 0, h))
@vorticity: vec3 = vec3((py.z - ny.z) - (pz.y - nz.y),
                        (pz.x - nz.x) - (px.z - nx.z),
                        (px.y - nx.y) - (py.x - ny.x)) / (2.0 * h)
