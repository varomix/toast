# Remove a random share of the curves.
# Run Over: Curves
if random(@index, param("seed", 0)) > param("keep", 0.5, min=0, max=1):
    remove_curve(@index)
