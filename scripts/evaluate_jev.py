"""Small developer-labeled fixture evaluation. Never inserts research evidence."""
import argparse,asyncio,sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from radar.config import Settings,ROOT
from radar.storage import Store,uid,now,dumps
from radar.schemas import Plan
from radar.jev import Jev
from typesafe_sdk import Choice,Noul

CASES=[
 ('Explicit price','The plan costs EUR 19 per month.','Does the supplied text publish a monthly price?','supported'),
 ('Contact only','Contact us for a quote.','Does the supplied text publish a monthly price?','unknown'),
 ('Claim without measurement','Our product is the fastest in the world.','Does the supplied text provide measured benchmark results?','unknown'),
 ('Measured scoped result','On the specified 100-file dataset, this implementation completed in 8.2 seconds.','Does the supplied text provide measured benchmark results?','supported'),
 ('No reach evidence','This article explains local AI infrastructure costs.','Does the supplied text report an audience count?','unknown'),
 ('Publisher audience claim','The publisher reports 1,200 views during June 2026.','Does the supplied text report an audience count?','supported')]
async def main():
 s=Settings.load();s.dev_testing=True
 if not s.key: raise SystemExit('TYPESAFE_API_KEY is not configured server-side; no request made.')
 (ROOT/'.runtime').mkdir(mode=0o700,exist_ok=True)
 db=Store(ROOT/'.runtime/evaluation.sqlite');jev=Jev(s,db)
 try:
  p=Plan(goal='Developer-labeled bounded decision checks',limits={'max_calls':20}).model_dump();mid=uid()
  db.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',(mid,p['goal'],'running',dumps(p),1,now(),now(),None,'fixture'))
  results=[]
  for name,text,q,expected in CASES:
   d=await jev.ask(mid,{'fixture_text':text}, {'support':Choice(instructions=q+' Supported means explicitly stated; unknown means not established in this excerpt.',criteria={'supported':'Explicit in supplied text','unknown':'Not established in supplied text'}), 'has_numeric_measure':Noul(instructions='Does this text contain an explicit numeric measurement, price or count?')},name,cache=False)
   got=d['answers']['support']['choice'];results.append({'case':name,'expected':expected,'actual':got,'error':got!=expected,'latency_ms':d['latency_ms'],'model':d['model'],'usage':d['usage']})
  orders=[]
  for goal,a,b in [
   ('Compare pricing conditions and independently reproducible evidence. Both questions remain open.','Inspect the public pricing page','Inspect the named case study'),
   ('Compare two languages for an application where both runtime speed and memory safety matter.','Inspect the benchmark methodology','Inspect the language safety documentation'),
   ('Determine whether an article has useful distribution evidence, with no platform preferred.','Inspect the linked forum discussion','Inspect the linked public video page')]:
   pair=[]
   for criteria in ({'a':a,'b':b,'unknown':'Neither is useful'}, {'unknown':'Neither is useful','b':b,'a':a}):
    d=await jev.ask(mid,{'goal':goal},{'next':Choice(instructions='Which of these prepared actions most usefully addresses the goal?',criteria=criteria)},'Ambiguous candidate ordering check',cache=False)
    pair.append({'order':list(criteria),'answer':d['answers']['next'],'latency_ms':d['latency_ms']})
   orders.append({'goal':goal,'runs':pair,'selection_changed':pair[0]['answer']['choice']!=pair[1]['answer']['choice']})
  relevance=[]
  for text,expected in [('The language documentation states that ownership and borrowing enforce memory safety.','direct'),('A recipe for apple pie uses flour, butter and apples.','unrelated'),('The language foundation has announced a community conference.','context')]:
   d=await jev.ask(mid,{'goal':'Compare how programming languages enforce memory safety.','fixture_text':text},{'relevance':Choice(instructions='Classify relevance to the stated goal using only the provided excerpt.',criteria={'direct':'Directly addresses memory safety mechanisms','context':'Related language or ecosystem context without memory safety evidence','unrelated':'Unrelated to the language or memory safety goal','unknown':'Cannot determine'})},'Developer-labeled relevance check',cache=False)
   got=d['answers']['relevance']['choice'];relevance.append({'text':text,'expected':expected,'actual':got,'error':got!=expected,'answer':d['answers']['relevance'],'latency_ms':d['latency_ms']})
  out={'source_mode':'developer-labeled fixtures evaluated by live TypeSafe; not research evidence','n':len(results),'errors':sum(r['error'] for r in results),'cases':results,'relevance_n':len(relevance),'relevance_errors':sum(r['error'] for r in relevance),'relevance_cases':relevance,'ordering_checks':orders,'limitation':'Tiny illustrative sample; no general accuracy or benchmark claim. Ambiguous ordering is retained, not normalized away.'}
  (ROOT/'.runtime/evaluation.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
 finally:
  db.close()

if __name__ == '__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--allow-paid',action='store_true',help='Allow up to 15 real TypeSafe requests on synthetic evaluation fixtures.')
 args=parser.parse_args()
 if not args.allow_paid: parser.error('Live evaluation is opt-in; pass --allow-paid to authorize paid requests.')
 asyncio.run(main())
