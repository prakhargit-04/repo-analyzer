"""
Puts pipeline/ on sys.path so tests import the modules the same way
main.py does (flat imports, no package prefix) rather than duplicating
import logic here.
"""
import os
import sys

PIPELINE_DIR = os.path.join(os.path.dirname(__file__), "..", "pipeline")
sys.path.insert(0, os.path.abspath(PIPELINE_DIR))
