# Smoke, divergence (Run Over: Voxels): how much the velocity flows out of each voxel, from the
# six neighbors (grid_voxel() reads a voxel by its index). The pressure solve that follows
# removes it, so smoke swirls and curls instead of bunching up or vanishing.
v = @voxel
px: vec3 = grid_voxel(0, "velocity", v + vec3(1, 0, 0))
nx: vec3 = grid_voxel(0, "velocity", v - vec3(1, 0, 0))
py: vec3 = grid_voxel(0, "velocity", v + vec3(0, 1, 0))
ny: vec3 = grid_voxel(0, "velocity", v - vec3(0, 1, 0))
pz: vec3 = grid_voxel(0, "velocity", v + vec3(0, 0, 1))
nz: vec3 = grid_voxel(0, "velocity", v - vec3(0, 0, 1))
@divergence = ((px.x - nx.x) + (py.y - ny.y) + (pz.z - nz.z)) / (2.0 * @voxel_size.x)
