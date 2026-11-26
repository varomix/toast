# Smoke, pressure (Run Over: Voxels): one Jacobi step of the pressure solve; the Repeat Zone runs
# it many times. Each voxel takes the average pressure of its six neighbors, less its
# divergence. Where there are no voxels the pressure is 0 (the grid's background): open air.
v = @voxel
h = @voxel_size.x
around = (grid_voxel(0, "pressure", v + vec3(1, 0, 0)) + grid_voxel(0, "pressure", v - vec3(1, 0, 0))
          + grid_voxel(0, "pressure", v + vec3(0, 1, 0)) + grid_voxel(0, "pressure", v - vec3(0, 1, 0))
          + grid_voxel(0, "pressure", v + vec3(0, 0, 1)) + grid_voxel(0, "pressure", v - vec3(0, 0, 1)))
@pressure = (around - @divergence * h * h) / 6.0
