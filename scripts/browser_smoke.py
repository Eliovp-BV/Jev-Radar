"""Explicit public Python.org render; no inference and no live research records."""
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from radar.config import Settings,ROOT
from radar.acquisition import Fetcher
from radar.browser import Browser

async def main():
 settings=Settings.load()
 result=await Browser(Fetcher(user_agent=settings.user_agent),ROOT/'.runtime/browser-check').render('https://www.python.org/')
 out={k:v for k,v in result.items() if k not in ('body','targets','headers')}
 out['target_count']=len(result['targets'])
 (ROOT/'.runtime/browser-final-smoke.json').write_text(json.dumps(out,indent=2))
 print(json.dumps(out,indent=2))

asyncio.run(main())
