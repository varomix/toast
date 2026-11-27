# Fire, divergence (Run Over: Voxels): as in the smoke, how much the velocity flows out of each
# voxel; less where the fuel burns, so the pressure solve pushes the hot gas outward: burning
# gas expands, and flames billow.
v = @voxel
px: vec3 = grid_voxel(0, "velocity", v + vec3(1, 0, 0))
nx: vec3 = grid_voxel(0, "velocity", v - vec3(1, 0, 0))
py: vec3 = grid_voxel(0, "velocity", v + vec3(0, 1, 0))
ny: vec3 = grid_voxel(0, "velocity", v - vec3(0, 1, 0))
pz: vec3 = grid_voxel(0, "velocity", v + vec3(0, 0, 1))
nz: vec3 = grid_voxel(0, "velocity", v - vec3(0, 0, 1))
flow_out = ((px.x - nx.x) + (py.y - ny.y) + (pz.z - nz.z)) / (2.0 * @voxel_size.x)
@divergence = flow_out - @flame * param("expansion", 0.5)
