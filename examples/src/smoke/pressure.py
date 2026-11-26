# Smoke, pressure (Run Over: Voxels): one Jacobi step of the pressure solve; the Repeat Zone runs
# it many times. Each voxel takes the average pressure of its six neighbors, less its
# divergence. Outside the box the pressure grid is 0 (its background): smoke can leave.
h = param("voxel_size", 0.03125)
p = @position
around = (sample_grid(0, "pressure", p + vec3(h, 0, 0)) + sample_grid(0, "pressure", p - vec3(h, 0, 0))
          + sample_grid(0, "pressure", p + vec3(0, h, 0)) + sample_grid(0, "pressure", p - vec3(0, h, 0))
          + sample_grid(0, "pressure", p + vec3(0, 0, h)) + sample_grid(0, "pressure", p - vec3(0, 0, h)))
@pressure = (around - @divergence * h * h) / 6.0
