from .schemas import Lens
import re


def suggested_lens(goal):
    rules=[('landscape',r'\b(competitors?|alternatives?|companies|vendors?|suppliers?|providers?|pricing)\b','The goal asks about competing offers, providers or pricing.'),
           ('campaign',r'\b(campaigns?|traction|engagement|distribution|reach|virality|viral|views)\b','The goal asks about observed campaigns, reach or engagement.'),
           ('content',r'\b(content|videos?|articles?|blogs?|youtube|seo|editorial|posts?|topics?|hooks?)\b','The goal asks about useful content, formats or reader questions.'),
           ('open',r'\b(technical|benchmarks?|implementation|open.source|libraries|library|sdk|programming|protocols?|frameworks?|api)\b','The goal asks about technical implementation or evidence.')]
    for lens_id,pattern,reason in rules:
        if re.search(pattern,goal,re.I):return lens_id,reason
    return 'open','No specialized intent rule matched; use general implementation, evidence and limitations questions.'

def lens(id,name,description,questions):
    return Lens(id=id,name=name,description=description,criteria=[{'id':k,'label':label,'question':q} for k,label,q in questions]).model_dump()

BUILTINS = [
 lens('landscape','Competitor landscape','Compare public offers, positioning and evidence gaps.',[
 ('offering','Offering','What product or service does this entity publicly offer?'),
 ('audience','Audience','Which intended customers or users are explicitly identified?'),
 ('capabilities','Capabilities','What concrete capabilities or delivery methods are advertised?'),
 ('pricing','Public pricing','What prices, pricing conditions or purchase terms are explicitly published?'),
 ('geography','Geography','Which geographies are explicitly served?'),
 ('proof','Proof & cases','What named case studies, methods or reproducible evidence are presented?')]),
 lens('content','Content & search','Inspect useful content and observed search appearances.',[
 ('intent','Reader intent','What specific reader question does this page answer?'),
 ('format','Format','What useful format, method, tool or explanation does the content provide?'),
 ('evidence','Evidence quality','What verifiable sources, original data or methods does the page provide?'),
 ('limitations','Limitations','What limitations or uncertainty does the content explicitly acknowledge?')]),
 lens('campaign','Campaign & traction','Trace public artifacts and distribution without inventing reach.',[
 ('campaign','Campaign artifact','What campaign, event or published initiative is explicitly described?'),
 ('distribution','Distribution','What named distribution channel or public reference is mentioned?'),
 ('engagement','Reported engagement','What numeric engagement measure and its period are explicitly reported?'),
 ('audience','Intended audience','Which audience is the artifact intended to reach?')]),
 lens('open','Open investigation','Apply your own bounded evaluation questions to any public topic.',[
 ('implementation','Implementation / offer','What concrete implementation, product or activity is described?'),
 ('evidence','Supporting evidence','What reproducible evidence or source supports the public claims?'),
 ('limitations','Known limitations','What limitations, unsupported claims or evidence gaps are explicitly stated?')])
]
