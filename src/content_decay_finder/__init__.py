"""Find decaying pages in Google Search Console data and decide which ones to refresh first."""

from content_decay_finder._version import __version__
from content_decay_finder.analyze import AnalysisResult, analyze
from content_decay_finder.config import AnalysisConfig
from content_decay_finder.loader import Dataset, load_csv, load_paths

__all__ = ["AnalysisConfig", "AnalysisResult", "Dataset", "__version__", "analyze", "load_csv", "load_paths"]
