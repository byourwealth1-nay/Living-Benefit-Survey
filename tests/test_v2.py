"""Integration + browser UI tests for V2 (optional: pip install playwright + Chromium)."""
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, build_opener, HTTPCookieProcessor
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import server

class Client:
    def __init__(self): self.opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(self, base, path, method='GET', payload=None, csrf=''):
        headers={}
        raw=None
        if payload is not None:
            raw=json.dumps(payload,ensure_ascii=False).encode('utf-8')
            headers['Content-Type']='application/json'
        if csrf: headers['X-CSRF-Token']=csrf
        req=Request(base+path,data=raw,method=method,headers=headers)
        try:
            with self.opener.open(req,timeout=6) as res:
                blob=res.read(); code=res.status
        except HTTPError as e:
            blob=e.read(); code=e.code
        try: parsed=json.loads(blob)
        except Exception: parsed=blob.decode('utf-8',errors='replace')
        return {'status':code,'body':parsed}


def backend_tests(base, admin, guest):
    assert guest.call(base,'/api/overview')['status']==401
    assert guest.call(base,'/api/customers','POST',{'name':'evil'})['status']==403
    assert admin.call(base,'/api/session')['body']['authenticated'] is False
    login=admin.call(base,'/api/login','POST',{'username':'advisor','password':'strong-pass-012345'})
    assert login['status']==200,login
    csrf=admin.call(base,'/api/session')['body']['csrf']
    assert csrf
    assert admin.call(base,'/api/customers','POST',{'name':'Blocked'})['status']==403,'csrf required'
    first=admin.call(base,'/api/customers','POST',{'name':'Test Client','phone':'0812345678'},csrf)
    assert first['status']==201,first
    cid=first['body']['id']
    inv=admin.call(base,'/api/invitations','POST',{'customerId':cid,'mode':'customer'},csrf)
    assert inv['status']==201,inv
    path=inv['body']['path']
    assert guest.call(base,'/api/invite/'+path.rsplit('/',1)[1])['body']['open'] is True
    sample={'customer':'Test Client','age':'35','housePayment':'20000','household':'30000','educationSemester':'30000','termsPerYear':'2','reserveYears':'3','ciOnce':'300000','ciRepeat':'200000','diseases':['โรคมะเร็ง'],'concern':'worried','risk':'transfer'}
    version=guest.call(base,'/api/invite/'+path.rsplit('/',1)[1])['body']['consentVersion']
    assert guest.call(base,'/api/invite/'+path.rsplit('/',1)[1],'POST',{'consent':False,'consentVersion':version,'data':sample})['status']==400
    submitted=guest.call(base,'/api/invite/'+path.rsplit('/',1)[1],'POST',{'consent':True,'consentVersion':version,'data':sample})
    assert submitted['status']==200,submitted
    assert submitted['body']['stats']=={'monthly':55000.0,'desired':1980000.0,'covered':500000.0,'gap':1480000.0}
    assert guest.call(base,'/api/invite/'+path.rsplit('/',1)[1],'POST',{'consent':True,'consentVersion':version,'data':sample})['status']==410
    assert guest.call(base,'/api/invite/'+path.rsplit('/',1)[1])['body']['open'] is False
    overview=admin.call(base,'/api/overview')
    assert overview['status']==200
    assert overview['body']['totals']['completed']==1
    assert overview['body']['totals']['gap']==1480000
    d=admin.call(base,'/api/surveys/'+str(inv['body']['id']))['body']
    assert d['response']['diseases']==['โรคมะเร็ง']
    assert guest.call(base,'/api/surveys/'+str(inv['body']['id']))['status']==401
    renew_inv=admin.call(base,'/api/invitations','POST',{'customerId':cid,'mode':'customer'},csrf)['body']
    old=renew_inv['path'];sid=renew_inv['id']
    newer=admin.call(base,f'/api/surveys/{sid}/renew','POST',{},csrf)
    assert newer['status']==200 and newer['body']['path']!=old
    assert guest.call(base,'/api/invite/'+old.rsplit('/',1)[1])['body']['open'] is False
    assert guest.call(base,'/api/invite/'+newer['body']['path'].rsplit('/',1)[1])['body']['open'] is True
    assert admin.call(base,f'/api/surveys/{sid}','DELETE',None,csrf)['status']==200
    assert guest.call(base,'/api/invite/'+newer['body']['path'].rsplit('/',1)[1])['body']['open'] is False
    assert admin.call(base,'/api/customers/'+str(cid),'DELETE',None,csrf)['status']==200
    assert admin.call(base,'/api/overview')['body']['totals']['customers']==0
    return csrf


def browser_tests(base):
    from playwright.sync_api import sync_playwright
    admin_client=Client();guest_client=Client()
    dash_html=(ROOT/'web/dashboard.html').read_text().replace('<link rel="stylesheet" href="/app.css">','').replace('<script src="/dashboard.js"></script>','')
    dash_js=(ROOT/'web/dashboard.js').read_text().replace('new URL(path,location.origin)','new URL(path,"'+base+'")')
    survey_html=(ROOT/'web/survey.html').read_text()
    survey_css=survey_html.split('<style>',1)[1].split('</style>',1)[0]
    survey_html=survey_html.replace('<style>'+survey_css+'</style>','')
    # Strip app inline script; we'll attach after our API bridge is installed.
    survey_js=survey_html.rsplit('<script>',1)[1].split('</script>',1)[0]
    survey_html=survey_html.rsplit('<script>',1)[0]+'</body></html>'
    bridge = '''window.fetch = async function(url,options={}) {
      const x = await window.bridgeApi({url:String(url),method:options.method||'GET',headers:options.headers||{},body:options.body||null});
      return new Response(JSON.stringify(x.body),{status:x.status,headers:{'Content-Type':'application/json'}});
    };'''
    def make_bridge(page,client):
        def call(_source,args):
            payload=json.loads(args['body']) if args.get('body') else None
            hdr=args.get('headers') or {}
            csrf=hdr.get('X-CSRF-Token') or hdr.get('x-csrf-token') or ''
            url=args['url']
            if url.startswith(base):url=url[len(base):]
            return client.call(base,url,args['method'],payload,csrf)
        page.expose_binding('bridgeApi',call)
        page.add_init_script(bridge)
        page.evaluate('(()=>{' + bridge + 'return true})()')
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        admin=browser.new_page(viewport={'width':1440,'height':1000})
        admin.set_default_timeout(8000)
        errors=[]
        admin.on('pageerror',lambda err:errors.append('dash: '+str(err)))
        make_bridge(admin,admin_client)
        admin.set_content(dash_html)
        admin.add_style_tag(content=(ROOT/'web/app.css').read_text())
        admin.add_script_tag(content=dash_js)
        admin.locator('#loginView').wait_for(state='visible')
        admin.locator('#username').fill('advisor')
        admin.locator('#password').fill('strong-pass-012345')
        admin.locator('#loginForm button').click()
        admin.locator('#appView').wait_for(state='visible')
        assert admin.locator('#totalCustomers').inner_text()=='0'
        admin.locator('#newCustomerBtn').click()
        admin.locator('#customerName').fill('คุณสมชาย ตัวอย่าง')
        admin.locator('#customerPhone').fill('0812345678')
        admin.locator('#customerForm button[type="submit"]').click()
        admin.locator('#inviteDialog').wait_for(state='visible')
        link=admin.locator('#inviteUrl').input_value()
        token=link.rsplit('/',1)[1]
        assert len(token)>=32
        admin.locator('#inviteDialog [data-close]').click()
        survey=browser.new_page(viewport={'width':390,'height':844})
        survey.set_default_timeout(8000)
        survey.on('pageerror',lambda err:errors.append('survey: '+str(err)))
        make_bridge(survey,guest_client)
        survey.set_content(survey_html)
        survey.add_style_tag(content=survey_css)
        survey.add_script_tag(content=survey_js.replace("location.pathname.split('/').pop()",repr(token)))
        survey.locator('#gate').wait_for(state='visible')
        assert not survey.locator('#app').is_visible()
        survey.locator('#consentCheck').check()
        survey.locator('#startBtn').click()
        survey.locator('#f-customer').fill('คุณสมชาย ตัวอย่าง')
        survey.locator('#f-age').fill('35')
        survey.locator('input[name="concern"][value="worried"]').check()
        survey.locator('input[data-array="diseases"][value="โรคมะเร็ง"]').check()
        survey.locator('#nextBtn').click()
        survey.locator('input[data-array="behaviors"]').first.check()
        survey.locator('#nextBtn').click()
        survey.locator('#f-housePayment').fill('20000')
        survey.locator('#f-household').fill('30000')
        survey.locator('#f-educationSemester').fill('30000')
        assert survey.locator('#sideMonthly').inner_text()=='฿55,000'
        survey.locator('#nextBtn').click()
        survey.locator('input[data-field="ciOnce"]').fill('300000')
        survey.locator('input[data-field="ciRepeat"]').fill('200000')
        assert survey.locator('#sideGap').inner_text()=='฿1,480,000'
        survey.locator('#nextBtn').click()
        survey.locator('input[name="risk"][value="transfer"]').check()
        assert survey.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),'survey mobile overflow'
        survey.screenshot(path='/mnt/data/Living_Benefits_V2_Survey_Mobile.png',full_page=True)
        survey.locator('#nextBtn').click()
        survey.locator('#submitted').wait_for(state='visible')
        assert survey.locator('#doneGap').inner_text()=='฿1,480,000'
        admin.evaluate('refresh()')
        admin.wait_for_function('document.querySelector("#totalCompleted").textContent === "1"')
        admin.locator('[data-action="detail"]').first.click()
        admin.locator('#detailDialog').wait_for(state='visible')
        assert 'โรคมะเร็ง' in admin.locator('#detailBody').inner_text()
        admin.screenshot(path='/mnt/data/Living_Benefits_V2_Result_Desktop.png',full_page=True)
        admin.locator('#detailDialog [data-close]').first.click()
        admin.screenshot(path='/mnt/data/Living_Benefits_V2_Dashboard_Desktop.png',full_page=True)
        admin.set_viewport_size({'width':390,'height':844})
        assert admin.evaluate('document.documentElement.scrollWidth <= innerWidth+1'),'dashboard mobile overflow'
        admin.screenshot(path='/mnt/data/Living_Benefits_V2_Dashboard_Mobile.png',full_page=True)
        assert not errors,errors
        browser.close()


if __name__=='__main__':
    with tempfile.TemporaryDirectory() as tmp:
        server.DB=Path(tmp)/'tests.sqlite3'
        server.initialize()
        salt='ab'*16
        with server.connect() as db:
            db.execute('INSERT INTO admins(username,salt,password_hash,created_at) VALUES(?,?,?,?)',('advisor',salt,server.password_hash('strong-pass-012345',salt),server.NOW()))
        env=os.environ.copy();env.update({'SURVEY_DB':str(server.DB),'SURVEY_PORT':'8876'})
        proc=subprocess.Popen([sys.executable,'-u',str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        base='http://127.0.0.1:8876'
        try:
            for attempt in range(100):
                try:
                    if Client().call(base,'/api/session')['status']==200:break
                except (URLError,ConnectionError):time.sleep(.05)
            else:raise RuntimeError('Server failed to start')
            backend_tests(base,Client(),Client()); print('PASS API / SQLite: login, CSRF, customer CRUD, invite, consent, A/B/C, one-use, renew, revoke, delete',flush=True)
            browser_tests(base);print('PASS Browser: dashboard, 5-step survey, submission, report, mobile, no JS errors',flush=True)
        finally:
            proc.terminate();proc.wait(timeout=5)
