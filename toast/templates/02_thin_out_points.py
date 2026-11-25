# Remove a random share of the points.
# Run Over: Points
keep = param("keep", 0.5, min=0, max=1)
if random(@index, param("seed", 0)) > keep:
    remove_point(@index)
