"""Real sandboxed Chromium on a route-fulfilled fixture; no external network."""
import pytest
from radar.browser import Browser
from radar.config import ROOT

@pytest.mark.asyncio
@pytest.mark.parametrize('status',[200,404])
async def test_browser_denies_private_subrequests(tmp_path,monkeypatch,status):
 monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH',str(ROOT/'.cache/ms-playwright'))
 calls=[]
 class FixtureFetcher:
  async def permitted(self,url):return url
  async def get(self,url):
   calls.append(url)
   assert '127.0.0.1' not in url and '169.254' not in url
   return {'url':'https://example.com/final/','status':status,'headers':{'Content-Type':'text/html'},'body':b'<html><head><title>Isolated fixture</title></head><body><p>Fixture only.</p><img src="http://127.0.0.1:8787/api/settings"><img src="http://169.254.169.254/latest/meta-data/"><script>fetch("https://example.com/mutate",{method:"POST",body:"blocked"})</script></body></html>'}
 result=await Browser(FixtureFetcher(),tmp_path).render('https://example.com/')
 assert result['artifact_id'] and (tmp_path/'artifacts'/f"{result['artifact_id']}.png").exists()
 assert calls==['https://example.com/']
 assert result['url']=='https://example.com/final/' and result['status']==status
 if status==200:assert len([e for e in result['trace'] if e['operation']=='network.blocked'])>=2
