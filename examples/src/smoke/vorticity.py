# Smoke, vorticity (Run Over: Voxels): how fast the smoke spins at each voxel (the curl of the
# velocity, from the six neighbors). step.py uses it to keep small swirls alive that the
# advection would blur away (vorticity confinement).
v = @voxel
px: vec3 = grid_voxel(0, "velocity", v + vec3(1, 0, 0))
nx: vec3 = grid_voxel(0, "velocity", v - vec3(1, 0, 0))
py: vec3 = grid_voxel(0, "velocity", v + vec3(0, 1, 0))
ny: vec3 = grid_voxel(0, "velocity", v - vec3(0, 1, 0))
pz: vec3 = grid_voxel(0, "velocity", v + vec3(0, 0, 1))
nz: vec3 = grid_voxel(0, "velocity", v - vec3(0, 0, 1))
@vorticity: vec3 = vec3((py.z - ny.z) - (pz.y - nz.y),
                        (pz.x - nz.x) - (px.z - nx.z),
                        (px.y - nx.y) - (py.x - ny.x)) / (2.0 * @voxel_size.x)
