# Smoke, projection (Run Over: Voxels): take the pressure's gradient off the velocity. What is
# left flows without bunching up: the swirls of real smoke.
v = @voxel
gradient = vec3(grid_voxel(0, "pressure", v + vec3(1, 0, 0)) - grid_voxel(0, "pressure", v - vec3(1, 0, 0)),
                grid_voxel(0, "pressure", v + vec3(0, 1, 0)) - grid_voxel(0, "pressure", v - vec3(0, 1, 0)),
                grid_voxel(0, "pressure", v + vec3(0, 0, 1)) - grid_voxel(0, "pressure", v - vec3(0, 0, 1)))
@velocity = @velocity - gradient / (2.0 * @voxel_size.x)
