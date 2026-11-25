# Grow a hair edge from every point along its normal.
# Run Over: Points
length_ = param("length", 0.2)
tip = add_point(@position + @normal * length_ * (0.5 + random(@index, 3)))
add_edge(@index, tip)
