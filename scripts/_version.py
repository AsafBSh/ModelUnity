"""Single source of truth for Modelunify's user-visible version string.

Kept in a dedicated module (rather than inside `web_ui.py`) so the
launcher banner can read the version without paying the cost of
importing `web_ui` and all of its heavy transitive deps (torch,
diffusers, gradio, every engine). Both the UI header pill and the
Rich progress banner import from here.
"""
MODELUNIFY_VERSION = "1.11.2"
