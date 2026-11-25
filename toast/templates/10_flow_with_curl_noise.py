# Push points along a swirling flow (curl noise), animated over time.
# Run Over: Points
freq = param("freq", 1.5)
speed = param("speed", 0.2)
@position += curl_noise(@position * freq + (0, 0, @time * speed)) * param("amount", 0.1)
