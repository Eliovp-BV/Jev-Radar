from pathlib import Path
from dataclasses import dataclass
from dotenv import dotenv_values
import os

ROOT = Path(__file__).resolve().parents[2]

@dataclass
class Settings:
    data_dir: Path = ROOT / 'data'
    host: str = '0.0.0.0'
    port: int = 8787
    model: str = 'jev-1.13.0'
    contact_url: str = ''
    key: str = ''
    brave_key: str = ''
    openai_key: str = ''
    gemini_key: str = ''
    anthropic_key: str = ''
    openrouter_key: str = ''
    text_model_key: str = ''
    text_model_base_url: str = ''
    text_provider: str = 'disabled'
    text_model: str = ''
    # Optional operator estimates for the explicitly configured text model.
    text_input_rate: float | None = None
    text_output_rate: float | None = None
    dev_testing: bool = False
    http_concurrency: int = 4
    jev_concurrency: int = 4
    browser_contexts: int = 1
    # Public list price, verified 2026-09-18. Account-specific charges may differ.
    input_rate: float = .042
    output_rate: float = 0
    pricing_source: str = 'https://docs.typesafe.ai/models (2026-09-18 public list price; account rate unverified)'

    @property
    def user_agent(self):
        from .security import validate_url
        contact=validate_url(self.contact_url) if self.contact_url.strip() else ''
        return 'JevRadarBot/0.1 ('+(contact+'; ' if contact else '')+'bounded single-user public research)'

    @classmethod
    def load(cls):
        local = dotenv_values(ROOT / '.env')
        def get(name, default=''):
            return str(local.get(name) or os.environ.get(name) or default)
        def credential(name):
            value=get(name).strip()
            placeholders={'your_key_here','your_typesafe_key','your_brave_search_key','your_openai_key','your_gemini_key','your_google_key','your_anthropic_key','your_openrouter_key','your_text_model_key','your_actual_key','your_api_key','replace_me','changeme'}
            return '' if value.casefold() in placeholders else value
        key = credential('TYPESAFE_API_KEY')
        def optional_rate(name):
            value=get(name).strip()
            if not value: return None
            try: return float(value)
            except ValueError: return float('nan')  # Invalid explicit pricing must fail closed.
        return cls(data_dir=Path(get('RADAR_DATA_DIR', str(ROOT / 'data'))).resolve(),
                   host=get('RADAR_HOST', '0.0.0.0'), port=int(get('RADAR_PORT', '8787')),
                   model=get('JEV_MODEL', 'jev-1.13.0'), contact_url=get('RADAR_CONTACT_URL'), key=key, brave_key=credential('BRAVE_SEARCH_API_KEY'),
                   openai_key=credential('OPENAI_API_KEY'),anthropic_key=credential('ANTHROPIC_API_KEY'),openrouter_key=credential('OPENROUTER_API_KEY'),
                   gemini_key=credential('GEMINI_API_KEY') or credential('GOOGLE_API_KEY'),
                   text_model_key=credential('TEXT_MODEL_API_KEY'),text_model_base_url=get('TEXT_MODEL_BASE_URL').strip(),
                   text_provider=get('TEXT_MODEL_PROVIDER','disabled').strip(),text_model=get('TEXT_MODEL_MODEL').strip(),
                   text_input_rate=optional_rate('TEXT_MODEL_INPUT_USD_PER_MILLION'),text_output_rate=optional_rate('TEXT_MODEL_OUTPUT_USD_PER_MILLION'),
                   dev_testing=get('RADAR_DEV_LIVE_TEST') == '1',
                   http_concurrency=max(1,min(4,int(get('RADAR_HTTP_CONCURRENCY','4')))),
                   jev_concurrency=max(1,min(4,int(get('RADAR_JEV_CONCURRENCY','4')))),
                   browser_contexts=max(1,min(2,int(get('RADAR_BROWSER_CONTEXTS','1')))),
                   input_rate=float(get('JEV_INPUT_USD_PER_MILLION', '.042')),
                   output_rate=float(get('JEV_OUTPUT_USD_PER_MILLION', '0')),
                   pricing_source=get('JEV_PRICING_SOURCE',cls.pricing_source))
