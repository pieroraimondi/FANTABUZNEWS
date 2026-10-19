"""Basket News v1 — server HTTP standard library, DB SQLite, RSS collector.

Avvio: python app.py. Non serve alcun pacchetto esterno.
"""
import csv
import difflib
import io
import json
import mimetypes
import os
from pathlib import Path
import sqlite3
import threading
import time
import traceback
import urllib.parse
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo
from catalog import TEAMS, TEAM_MAP, DIRECT_FEEDS, SPECIAL_SITES, SOCIAL_PROFILES, normalize
from collector import run_collector

HERE=Path(__file__).resolve().parent
DB_PATH=Path(os.environ.get('DATABASE_PATH',str(HERE/'data'/'basket_news.db')))
DB_PATH.parent.mkdir(parents=True,exist_ok=True)
PORT=int(os.environ.get('PORT','8000'))
REFRESH_TOKEN=os.environ.get('REFRESH_TOKEN','')
PRODUCTION=bool(os.environ.get('RENDER') or os.environ.get('PRODUCTION'))
AUTO_INITIAL_REFRESH=os.environ.get('AUTO_INITIAL_REFRESH','1')=='1'
TZ=ZoneInfo('Europe/Rome')
LOCK=threading.RLock()
STATUS={'running':False,'started_at':None,'finished_at':None,'last_update':None,
        'total':0,'done':0,'imported':0,'errors':[]}

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def conn():
    c=sqlite3.connect(str(DB_PATH),timeout=30)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    return c

def initialize():
    with conn() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
          CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL UNIQUE, source TEXT NOT NULL, host TEXT NOT NULL,
            published TEXT, collected TEXT NOT NULL, category TEXT NOT NULL,
            origin TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0
          );
          CREATE TABLE IF NOT EXISTS article_teams (
            article_id INTEGER NOT NULL, team_id TEXT NOT NULL,
            PRIMARY KEY(article_id,team_id)
          );
          CREATE INDEX IF NOT EXISTS idx_article_team ON article_teams(team_id);
          CREATE INDEX IF NOT EXISTS idx_article_published ON articles(published);
          CREATE INDEX IF NOT EXISTS idx_article_collected ON articles(collected);
          CREATE TABLE IF NOT EXISTS coverage (
            article_id INTEGER NOT NULL, url TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL, origin TEXT NOT NULL,
            PRIMARY KEY(article_id,url)
          );
          CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        ''')
        x=c.execute("SELECT value FROM meta WHERE key='last_update'").fetchone()
        if x: STATUS['last_update']=x['value']

def save_article(item):
    title=item['title']
    url=item['url']
    teams=item['teams']
    if not teams: return
    ts=utc_now()
    with LOCK, conn() as c:
        matched=c.execute('SELECT article_id FROM coverage WHERE url=?',(url,)).fetchone()
        article_id=matched['article_id'] if matched else None
        if article_id is None:
            cutoff=(datetime.now(timezone.utc)-timedelta(days=6)).isoformat(timespec='seconds')
            same_team=tuple(teams)
            qs=','.join('?'*len(same_team))
            candidates=c.execute(f'''SELECT DISTINCT a.id,a.title FROM articles a
              JOIN article_teams t ON t.article_id=a.id
              WHERE t.team_id IN ({qs}) AND a.collected>=?
              ORDER BY a.id DESC LIMIT 120''',(*same_team,cutoff)).fetchall()
            norm=normalize(title)
            for row in candidates:
                target=normalize(row['title'])
                if norm==target or (min(len(norm),len(target))>=40 and
                    difflib.SequenceMatcher(None,norm,target).ratio()>=.91):
                    article_id=row['id']; break
        if article_id is None:
            c.execute('''INSERT OR IGNORE INTO articles
               (title,summary,url,source,host,published,collected,category,origin,priority)
               VALUES(?,?,?,?,?,?,?,?,?,?)''',(
                title,item['summary'],url,item['source'],item['host'],item['published'],ts,
                item['category'],item['origin'],item['priority']))
            row=c.execute('SELECT id FROM articles WHERE url=?',(url,)).fetchone()
            article_id=row['id']
        else:
            # Priorità aumenta se almeno una fonte identifica una notizia importante.
            c.execute('UPDATE articles SET priority=max(priority,?) WHERE id=?',(item['priority'],article_id))
        c.execute('INSERT OR IGNORE INTO coverage(article_id,url,source,origin) VALUES(?,?,?,?)',(
            article_id,url,item['source'],item['origin']))
        c.executemany('INSERT OR IGNORE INTO article_teams(article_id,team_id) VALUES(?,?)',[(article_id,x) for x in teams])

def report(**kwargs):
    with LOCK:
        if 'total' in kwargs: STATUS['total']=kwargs['total']
        if 'done' in kwargs: STATUS['done']=kwargs['done']
        if 'progress' in kwargs: STATUS['done']+=kwargs['progress']
        if 'imported' in kwargs: STATUS['imported']=kwargs['imported']
        if 'errors' in kwargs: STATUS['errors']=kwargs['errors']
        if 'error' in kwargs:
            STATUS['errors'].append(kwargs['error'])
            if len(STATUS['errors'])>30: STATUS['errors']=STATUS['errors'][-30:]

def worker():
    try:
        run_collector(save_article,report)
    except Exception as e:
        report(error={'fonte':'sistema','errore':str(e)})
    finally:
        with LOCK:
            STATUS['finished_at']=utc_now()
            STATUS['last_update']=STATUS['finished_at']
            STATUS['running']=False
            with conn() as c:
                c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_update',?)",(STATUS['last_update'],))

def start_refresh(force=False):
    with LOCK:
        if STATUS['running']: return False,'Aggiornamento già in corso'
        # intervallo antiabuso, tranne scheduler locale
        previous=STATUS['started_at']
        if previous and not force:
            try:
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(previous)).total_seconds()
                if age<120: return False,'Ultimo aggiornamento avviato meno di 2 minuti fa'
            except (ValueError,TypeError): pass
        STATUS.update(running=True,started_at=utc_now(),finished_at=None,total=0,done=0,imported=0,errors=[])
    threading.Thread(target=worker,daemon=True,name='basket-refresh').start()
    return True,'Aggiornamento avviato'

def daily_schedule():
    # Affidabile solo se il processo rimane attivo: su Render con sleep, usare schedulatore esterno.
    last_key=None
    while True:
        now=datetime.now(TZ)
        key=f'{now.date()}-{now.hour}'
        if now.hour in (8,20) and key!=last_key:
            last_key=key
            start_refresh(force=True)
        time.sleep(30)

def get_news(params):
    team=params.get('team',[''])[0]
    league=params.get('league',[''])[0]
    topic=params.get('topic',[''])[0]
    origin=params.get('origin',[''])[0]
    search=params.get('q',[''])[0].strip()[:150]
    days=params.get('days',['7'])[0]
    important=params.get('important',['0'])[0]=='1'
    try: limit=min(max(int(params.get('limit',['80'])[0]),1),200)
    except ValueError: limit=80
    try: offset=min(max(int(params.get('offset',['0'])[0]),0),20000)
    except ValueError: offset=0
    where=[]; args=[]
    if team in TEAM_MAP:
        where.append('t.team_id=?');args.append(team)
    elif league in ('LBA','A2'):
        ids=[t.id for t in TEAMS if t.league==league]
        where.append('t.team_id IN ('+','.join('?'*len(ids))+')');args.extend(ids)
    if topic: where.append('a.category=?');args.append(topic)
    if origin: where.append('(a.origin=? OR EXISTS(SELECT 1 FROM coverage cc WHERE cc.article_id=a.id AND cc.origin=?))');args.extend((origin,origin))
    if search:
        where.append('(a.title LIKE ? OR a.summary LIKE ? OR a.source LIKE ?)')
        args.extend(['%'+search+'%']*3)
    if days in ('1','3','7','30'):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=int(days))).isoformat(timespec='seconds')
        where.append('COALESCE(a.published,a.collected)>=?');args.append(cutoff)
    if important: where.append('a.priority>=2')
    condition=' AND '.join(where) if where else '1=1'
    base=' FROM articles a JOIN article_teams t ON t.article_id=a.id WHERE '+condition
    with conn() as c:
        total=c.execute('SELECT COUNT(DISTINCT a.id)'+base,args).fetchone()[0]
        rows=c.execute('''SELECT DISTINCT a.* FROM articles a JOIN article_teams t
                          ON t.article_id=a.id WHERE '''+condition+
                        ''' ORDER BY COALESCE(a.published,a.collected) DESC,a.id DESC LIMIT ? OFFSET ?''',args+[limit,offset]).fetchall()
        news=[]
        for row in rows:
            a=dict(row)
            a['teams']=[x[0] for x in c.execute('SELECT team_id FROM article_teams WHERE article_id=?',(a['id'],)).fetchall()]
            a['coverage']=[dict(x) for x in c.execute('SELECT url,source,origin FROM coverage WHERE article_id=?',(a['id'],)).fetchall()]
            news.append(a)
    return {'total':total,'items':news,'limit':limit,'offset':offset}

def get_teams():
    cutoff=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat(timespec='seconds')
    with conn() as c:
        counts=dict(c.execute('''SELECT t.team_id,COUNT(*) FROM article_teams t
             JOIN articles a ON a.id=t.article_id
             WHERE COALESCE(a.published,a.collected)>=? GROUP BY t.team_id''',(cutoff,)).fetchall())
    return {'teams':[{**t.to_dict(),'count':counts.get(t.id,0)} for t in TEAMS]}

def get_sources():
    return {'leagues':[{'name':'LBA','url':'https://www.legabasket.it/'},
                       {'name':'LNP','url':'https://www.legapallacanestro.com/'}],
            'rss':DIRECT_FEEDS,
            'specialSites':SPECIAL_SITES,
            'socialProfiles':SOCIAL_PROFILES,
            'teams':[{'id':t.id,'name':t.name,'official':t.official,'local':list(t.local)} for t in TEAMS]}


# Interfaccia incorporata: consente il deploy anche se GitHub non carica la cartella static.
# Se i file static/ sono presenti, si preferisce il loro contenuto (aggiornabile).
import base64 as _base64
import gzip as _gzip
_EMBEDDED_ASSETS = {
    'app.js': (
        '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'
    ),
    'index.html': (
        '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'
        'c+JP+jCXntfx/6L5GghBcwEgAA'
    ),
    'style.css': (
        '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'
    ),
}

def _load_asset(src, name):
    if src.is_file():
        return src.read_bytes()
    packed = _EMBEDDED_ASSETS.get(name)
    if packed is None:
        raise FileNotFoundError(name)
    return _gzip.decompress(_base64.b64decode(packed))

class Handler(BaseHTTPRequestHandler):
    server_version='BasketNews/1.1'
    def log_message(self,fmt,*args): print('%s %s'%(self.address_string(),fmt%args),flush=True)
    def json_response(self,obj,status=200):
        content=json.dumps(obj,ensure_ascii=False,default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(content)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(content)
    def do_GET(self):
        url=urllib.parse.urlsplit(self.path)
        path=url.path
        params=urllib.parse.parse_qs(url.query)
        try:
            if path=='/api/status':
                with LOCK: d=dict(STATUS);d['errors']=list(STATUS['errors'])
                with conn() as c: d['articles']=c.execute('SELECT count(*) FROM articles').fetchone()[0]
                self.json_response(d)
            elif path=='/api/teams': self.json_response(get_teams())
            elif path=='/api/news': self.json_response(get_news(params))
            elif path=='/api/sources': self.json_response(get_sources())
            elif path=='/health': self.json_response({'ok':True,'service':'basket-news'})
            elif path=='/api/export.csv':
                data=get_news({**params,'limit':['200']})
                output=io.StringIO()
                w=csv.writer(output,delimiter=';')
                w.writerow(['Data','Campionato/Squadre','Fonte','Tipo','Categoria','Titolo','Link'])
                for x in data['items']:
                    w.writerow([x['published'] or x['collected'],', '.join(TEAM_MAP[t].name for t in x['teams']),
                                x['source'],x['origin'],x['category'],x['title'],x['url']])
                body=('\ufeff'+output.getvalue()).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type','text/csv; charset=utf-8')
                self.send_header('Content-Disposition','attachment; filename="basket-news.csv"')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path in ('/','/index.html','/static/style.css','/static/app.js'):
                name='index.html' if path in ('/','/index.html') else path.split('/')[-1]
                src=HERE/'static'/name
                body=_load_asset(src,name)
                self.send_response(200)
                self.send_header('Content-Type',mimetypes.guess_type(str(src))[0] or 'text/plain')
                self.send_header('Content-Length',str(len(body)))
                self.send_header('Cache-Control','public, max-age=60')
                self.send_header('X-Content-Type-Options','nosniff')
                self.end_headers(); self.wfile.write(body)
            else: self.json_response({'error':'not found'},404)
        except Exception as exc:
            traceback.print_exc()
            self.json_response({'error':str(exc)},500)
    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path!='/api/refresh':
            return self.json_response({'error':'not found'},404)
        if (PRODUCTION or REFRESH_TOKEN):
            if not REFRESH_TOKEN: return self.json_response({'error':'Configura REFRESH_TOKEN sul server'},503)
            supplied=self.headers.get('X-Refresh-Token','')
            import hmac
            if not hmac.compare_digest(supplied,REFRESH_TOKEN):
                return self.json_response({'error':'Token non valido'},403)
        ok,msg=start_refresh()
        self.json_response({'ok':ok,'message':msg},202 if ok else 409)

def main():
    initialize()
    threading.Thread(target=daily_schedule,daemon=True,name='basket-scheduler').start()
    if AUTO_INITIAL_REFRESH: start_refresh()
    host='0.0.0.0' if (PRODUCTION or REFRESH_TOKEN) else '127.0.0.1'
    server=ThreadingHTTPServer((host,PORT),Handler)
    print('Basket News su http://localhost:%s (database: %s)'%(PORT,DB_PATH),flush=True)
    server.serve_forever()

if __name__=='__main__': main()
