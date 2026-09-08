import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

# LLM / OpenRouter
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY', '')
LLM_BASE_URL = os.getenv('LLM_BASE_URL', 'https://openrouter.ai/api/v1')
LLM_MODEL = os.getenv('LLM_MODEL', 'openai/gpt-4o-mini')

# Database
DB_PATH = os.getenv('DB_PATH', str(BASE_DIR / 'fulcrum.db'))

# Thresholds (Locked by Spec & DECISIONS.md)
CONFIDENCE_THRESHOLD = 0.5
SIMILARITY_HIGH_THRESHOLD = 0.85
SIMILARITY_LOW_THRESHOLD = 0.65
RECONCILIATION_CHUNK_WINDOW = 15
PERCENTAGE_TOLERANCE = 0.05
ABSOLUTE_TOLERANCE = 0.01

# Document Paths
MACRO_DIR = BASE_DIR / 'starter-datasets' / 'india-macroeconomy'
RBI_PDF = MACRO_DIR / '02-rbi-annual-report-2024-25-excerpt.pdf'
IMF_PDF = MACRO_DIR / '03-imf-india-2025-article-iv-excerpt.pdf'
ECON_SURVEY_PDF = MACRO_DIR / '01-india-economic-survey-2024-25-excerpt.pdf'
DELHIVERY_DIR = BASE_DIR / 'starter-datasets' / 'delhivery'
