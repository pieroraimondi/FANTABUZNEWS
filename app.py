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
                body=src.read_bytes()
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
