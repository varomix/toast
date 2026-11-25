# Move points along their normals by Blender's Noise Texture.
# Run Over: Points
amp = param("amp", 0.2)
n = noise(@position * param("freq", 4.0))
@position += @normal * (n - 0.5) * amp
@height: float = n
