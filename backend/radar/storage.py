import sqlite3, json, threading, uuid, hashlib
from datetime import datetime, timezone
from pathlib import Path

def now(): return datetime.now(timezone.utc).isoformat()
def uid(): return uuid.uuid4().hex
def dumps(x): return json.dumps(x,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def fingerprint(x): return hashlib.sha256(dumps(x).encode()).hexdigest()

class Store:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.lock=threading.RLock()
        self.conn=sqlite3.connect(path,check_same_thread=False,isolation_level=None)
        self.conn.row_factory=sqlite3.Row
        self.conn.executescript(Path(__file__).with_name('migration.sql').read_text())
    def rows(self,sql,args=()):
        with self.lock: return [dict(r) for r in self.conn.execute(sql,args).fetchall()]
    def one(self,sql,args=()):
        rows=self.rows(sql,args); return rows[0] if rows else None
    def execute(self,sql,args=()):
        with self.lock: return self.conn.execute(sql,args)
    def mission(self,id):
        r=self.one('SELECT * FROM missions WHERE id=?',(id,))
        if not r: raise KeyError('Mission not found')
        r['plan']=json.loads(r['plan']); return r
    def event(self,mid,kind,payload,mode='live',parent=None):
        with self.lock:
            if mode=='live':
                mission=self.conn.execute('SELECT mode FROM missions WHERE id=?',(mid,)).fetchone()
                if mission and mission[0]=='fixture': mode='fixture'
            seq=self.conn.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE mission_id=?',(mid,)).fetchone()[0]
            self.conn.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)',(uid(),mid,seq,now(),kind,dumps(payload),mode,parent,1))
            return seq
    def mutate(self,mid,kind,payload,records=(),status=None,mode='live'):
        with self.lock:
            self.conn.execute('BEGIN IMMEDIATE')
            try:
                for rkind,r in records:
                    self.conn.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?,?)',(r['id'],mid,rkind,now(),dumps(r)))
                if status: self.conn.execute('UPDATE missions SET status=?,updated_at=? WHERE id=?',(status,now(),mid))
                self.event(mid,kind,{**payload,'record_changes':[{'kind':k,'record':r} for k,r in records]},mode)
                self.conn.execute('COMMIT')
            except BaseException:
                self.conn.execute('ROLLBACK'); raise
    def records(self,mid,kind=None):
        q='SELECT payload FROM records WHERE mission_id=?'; a=[mid]
        if kind: q+=' AND kind=?'; a.append(kind)
        return [json.loads(r['payload']) for r in self.rows(q+' ORDER BY created_at,id',a)]
    def events(self,mid,after=0):
        out=self.rows('SELECT * FROM events WHERE mission_id=? AND seq>? ORDER BY seq',(mid,after))
        for e in out: e['payload']=json.loads(e['payload'])
        return out
    def set_setting(self,key,value): self.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,dumps(value)))
    def setting(self,key,default=None):
        r=self.one('SELECT value FROM settings WHERE key=?',(key,)); return json.loads(r['value']) if r else default
    def recover(self):
        for m in self.rows("SELECT id FROM missions WHERE status IN ('running','pausing')"):
            self.mutate(m['id'],'recovery',{'reason':'Process stopped. Review uncertain paid work before deliberate retry.'},status='interrupted')
        self.execute("UPDATE reservations SET status='uncertain' WHERE status='inflight'")
    def close(self): self.conn.close()
