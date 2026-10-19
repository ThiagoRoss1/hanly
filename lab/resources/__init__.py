"""Resource attribution: what each part of Hanly costs, and whether a change helps.

Developer-only. Stage experiments run Hanly's real providers in fresh, isolated
processes and measure them from outside; session analysis reads the process
samples a recorded run already holds; comparison decides whether two
experiments may be compared before it labels any difference. Nothing here
tunes a production setting or accepts a change.
"""
