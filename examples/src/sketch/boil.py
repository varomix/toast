# Sketch, boil (Run Over: Points): hand-drawn animation redraws every line a little differently
# each time ("boiling" lines). Each point moves by noise that changes every `hold` frames, and the
# ink thickness wanders along the stroke. Runs on every layer's strokes, new hairs included.
hold = param("hold", 3.0)
step = floor(@frame / hold)
jitter = param("jitter", 0.012)
p = @position * param("scale", 6.0) + step * 13.7
@position += vec3(signed_noise(p), signed_noise(p + 31.0), signed_noise(p + 67.0)) * jitter
@radius = param("thickness", 0.012) * (0.45 + noise(@position * 3.0 + step))
@opacity: float = 1.0
