import os

# extractor.py and normalizer.py read this at import time, so it has to be
# set before pytest imports any test module that imports them.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
