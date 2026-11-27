# Fire, one step (Run Over: Voxels): the smoke example's step with combustion. Each voxel takes
# its fuel, temperature, smoke and velocity from where they come from (advection with
# sample_grid()). A burner pours in hot fuel; fuel above the ignition temperature burns: it
# heats the voxel, leaves soot (smoke) and pushes the gas apart (divergence.py). Heat rises and
# cools off, so flames go yellow, orange, red, then dark smoke.
dt = param("delta_time", 0.0417)
back = @position - @velocity * dt
fuel = sample_grid(0, "fuel", back)
temp = sample_grid(0, "temperature", back)
d = sample_grid(0, "density", back)
v: vec3 = sample_grid(0, "velocity", back)

# The burner: a flat disc on the floor, flickering (noise over time), that pours out hot fuel.
src = param("burner", (0.0, 0.0, 0.08))
radius = param("burner_radius", 0.4)
off = @position - src
disc = (1.0 - smoothstep(radius * 0.6, radius, length(vec3(off.x, off.y, 0.0)))) \
    * (1.0 - smoothstep(0.04, 0.1, abs(off.z)))
flicker = 0.6 + 0.4 * noise(@position * 4.0 + vec3(0, 0, -@time * 3.0))
fuel = max(fuel, disc * flicker)
temp = max(temp, disc * param("burner_heat", 0.9))
v = v + vec3(0, 0, param("burner_speed", 1.5)) * disc * dt * 8.0

# Combustion: fuel above the ignition temperature burns at `burn_rate`, giving heat and soot.
burn = 0.0
if temp > param("ignition", 0.3):
    burn = min(fuel, param("burn_rate", 4.0) * fuel * dt)
fuel = fuel - burn
temp = temp + burn * param("heat", 2.5)
d = d + burn * param("soot", 0.6)
@flame = burn / max(dt, 1e-4)  # per second; the first frame has no time step

# Vorticity confinement (as in the smoke): keeps the licks of flame turning.
@vorticity: vec3
w = @vorticity
i = @voxel
toward = vec3(length(grid_voxel(0, "vorticity", i + vec3(1, 0, 0))) - length(grid_voxel(0, "vorticity", i - vec3(1, 0, 0))),
              length(grid_voxel(0, "vorticity", i + vec3(0, 1, 0))) - length(grid_voxel(0, "vorticity", i - vec3(0, 1, 0))),
              length(grid_voxel(0, "vorticity", i + vec3(0, 0, 1))) - length(grid_voxel(0, "vorticity", i - vec3(0, 0, 1))))
toward = toward / (length(toward) + 1e-6)
v = v + cross(toward, w) * param("confinement", 6.0) * @voxel_size.x * dt

# Hot gas rises, smoke is a little heavy; turbulence stirs where it's hot.
v = v + vec3(0, 0, (param("buoyancy", 6.0) * temp - param("weight", 0.3) * d) * dt)
swirl = curl_noise(@position * param("swirl_scale", 2.5) + vec3(0, 0, -@time * 1.5))
v = v + swirl * param("swirl", 6.0) * dt * temp
v = v * (1.0 - param("drag", 0.3) * dt)
temp = temp * (1.0 - param("cooling", 1.5) * dt)
d = d * (1.0 - param("fade", 0.3) * dt)
fuel = fuel * (1.0 - param("fuel_fade", 2.0) * dt)

@fuel = fuel
@temperature = temp
@density = d
@velocity = v

# The grid follows the fire and its smoke, up to a ceiling.
if max(max(d, fuel), temp) > param("keep", 0.02) and @position.z < param("ceiling", 4.0):
    activate_voxel(@voxel, param("margin", 3))
else:
    deactivate_voxel(@voxel)
