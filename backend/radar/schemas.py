from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Literal
import re

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Criterion(Strict):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,31}$')
    label: str = Field(min_length=2,max_length=80)
    question: str = Field(min_length=8,max_length=500)
    rubric: str = Field(default='Select a passage that explicitly addresses the question. Unknown when not present in inspected passages; not applicable only when the dimension cannot apply.',max_length=800)

class Lens(Strict):
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,60}$')
    name: str = Field(min_length=2,max_length=100)
    description: str = Field(max_length=500)
    version: int = Field(default=1,ge=1)
    criteria: list[Criterion] = Field(min_length=1,max_length=8)

class Limits(Strict):
    max_pages: int = Field(default=12,ge=1,le=80)
    max_calls: int = Field(default=60,ge=1,le=200)
    max_queries: int = Field(default=4,ge=0,le=20)
    max_depth: int = Field(default=1,ge=0,le=3)
    per_domain: int = Field(default=6,ge=1,le=20)
    usd: float = Field(default=5,ge=.001,le=1000,allow_inf_nan=False)
    wall_seconds: int = Field(default=600,ge=30,le=3600)
    max_tokens: int = Field(default=250000,ge=1000,le=1000000)

class Plan(Strict):
    goal: str = Field(min_length=8,max_length=2000)
    seeds: list[str] = Field(default_factory=list,max_length=80)
    reference: str = Field(default='',max_length=2048)
    region: str = Field(default='',max_length=80)
    language: str = Field(default='en',pattern=r'^[a-z]{2,3}(-[A-Z]{2})?$')
    time_window: str = Field(default='',max_length=100)
    freshness: Literal['any','recent'] = 'any'
    known_entities: list[str] = Field(default_factory=list,max_length=30)
    excluded_domains: list[str] = Field(default_factory=list,max_length=50)
    excluded_entities: list[str] = Field(default_factory=list,max_length=30)
    lens_id: str = 'landscape'
    research_mode: Literal['adaptive','fixed'] = 'adaptive'
    lens_version: int = Field(default=1,ge=1)
    criteria: list[Criterion] = Field(default_factory=list,max_length=8)
    queries: list[str] = Field(default_factory=list,max_length=20)
    providers: list[Literal['seed','wikipedia','brave']] = Field(default_factory=lambda:['seed'])
    limits: Limits = Field(default_factory=Limits)
    browser: bool = False
    development_test: bool = False
    exploration_every: int = Field(default=4,ge=2,le=10)
    discovery_target: int = Field(default=3,ge=1,le=8)

    @field_validator('seeds','queries','known_entities','excluded_domains','excluded_entities')
    @classmethod
    def bounded_items(cls,v):
        if any(len(x)>2048 for x in v): raise ValueError('Item too long')
        return list(dict.fromkeys(x.strip() for x in v if x.strip()))

class Command(Strict):
    action: Literal['start','pause','resume','cancel','retry']
    idempotency_key: str = Field(min_length=8,max_length=100)

class Steer(Strict):
    url: str = Field(default='',max_length=2048)
    query: str = Field(default='',max_length=500)
    exclude: str = Field(default='',max_length=250)

class Review(Strict):
    state: Literal['unreviewed','approved','rejected','pinned']
    note: str = Field(default='',max_length=2000)

class ImportRequest(Strict):
    kind: Literal['urls','search','analytics']
    format: Literal['csv','json']
    content: str = Field(max_length=1000000)
    provenance: str = Field(min_length=5,max_length=500)
    private: bool = True
    allow_analysis: bool = False

class Profile(Strict):
    name: str = Field(default='Jev Radar by Eliovp',min_length=2,max_length=60)
    accent: str = Field(default='#f1d54a',pattern=r'^#[0-9a-fA-F]{6}$')
    retention_days: int = Field(default=30,ge=1,le=365)

class TextModelSettings(Strict):
    provider: Literal['disabled','openai','gemini','anthropic','openrouter','compatible'] = 'disabled'
    model: str = Field(default='',max_length=160,pattern=r'^[a-zA-Z0-9_.:/@+-]*$')
    max_calls: int = Field(default=6,ge=1,le=12)
    max_output_tokens: int = Field(default=3500,ge=128,le=6000)
    max_tokens: int = Field(default=120000,ge=4096,le=600000)
    usd: float = Field(default=20,ge=.001,le=1000,allow_inf_nan=False)
    input_usd_per_million: float | None = Field(default=None,ge=0,le=10000,allow_inf_nan=False)
    output_usd_per_million: float | None = Field(default=None,ge=0,le=10000,allow_inf_nan=False)

    @field_validator('model')
    @classmethod
    def model_identifier(cls, value, info):
        if info.data.get('provider') == 'gemini' and value and not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}', value):
            raise ValueError('Use a bare Gemini model ID, such as gemini-3.8-flash, without a URL or models/ prefix')
        return value

class SpendLimits(Strict):
    jev_usd: float = Field(default=5,ge=.001,le=1000,allow_inf_nan=False)
    text_usd: float = Field(default=20,ge=.001,le=1000,allow_inf_nan=False)

class ResearchDefaults(Strict):
    lens_id: str = Field(default='auto',min_length=1,max_length=61)
    language: str = Field(default='en',pattern=r'^[a-z]{2,3}(-[A-Z]{2})?$')
    region: str = Field(default='',max_length=80)
    providers: list[Literal['seed','wikipedia','brave']] = Field(default_factory=lambda:['seed','brave'],min_length=1,max_length=3)
    browser: bool = False
    discovery_target: int = Field(default=5,ge=1,le=8)
    limits: Limits = Field(default_factory=lambda:Limits(max_pages=24,max_calls=100,max_queries=6))

class RunEvent(BaseModel):
    id: str
    mission_id: str
    seq: int
    timestamp: str
    type: str
    payload: dict
    mode: str
    parent_id: str | None = None
    schema_version: int = 1

class MissionOut(BaseModel):
    id: str
    goal: str
    status: Literal['draft','running','pausing','paused','blocked','interrupted','complete','partial','cancelled']
    plan: Plan
    plan_version: int
    created_at: str
    updated_at: str
    parent_id: str | None = None
    mode: Literal['live','fixture','system'] = 'live'

class MissionDetailOut(MissionOut):
    records: dict[str,list[dict]]
    telemetry: dict
    events: list[RunEvent]
    opportunities: list[dict]
    cohorts: list[dict]
    outcome: dict = Field(default_factory=dict)
    landscape: dict = Field(default_factory=dict)
    jev_activity: dict = Field(default_factory=dict)
    corpus: dict = Field(default_factory=dict)
