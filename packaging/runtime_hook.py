"""Set warning policy in every frozen process without importing heavy runtimes.

WebEngine and OCR imports belong to their respective children, keeping the shell
light.
"""

from hanly_app.lookup.preload import silence_runtime_warnings

silence_runtime_warnings()
