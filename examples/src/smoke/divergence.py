# Smoke, divergence (Run Over: Voxels): how much the velocity flows out of each voxel, from the
# six neighbors one voxel away. The pressure solve that follows removes it, so smoke swirls and
# curls instead of bunching up or vanishing.
h = param("voxel_size", 0.03125)
px: vec3 = sample_grid(0, "velocity", @position + vec3(h, 0, 0))
nx: vec3 = sample_grid(0, "velocity", @position - vec3(h, 0, 0))
py: vec3 = sample_grid(0, "velocity", @position + vec3(0, h, 0))
ny: vec3 = sample_grid(0, "velocity", @position - vec3(0, h, 0))
pz: vec3 = sample_grid(0, "velocity", @position + vec3(0, 0, h))
nz: vec3 = sample_grid(0, "velocity", @position - vec3(0, 0, h))
@divergence = ((px.x - nx.x) + (py.y - ny.y) + (pz.z - nz.z)) / (2.0 * h)
