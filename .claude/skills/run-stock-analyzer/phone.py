"""Phone-width screenshot via CDP device emulation: phone.py URL OUT [WIDTH] [JS].
Prints innerWidth vs scrollWidth and any elements past the right edge."""
import sys, json, time, subprocess, base64, urllib.request, tempfile, os
sys.path.insert(0, '.claude/skills/run-stock-analyzer')
import driver, websocket
url, out = sys.argv[1], sys.argv[2]
w = int(sys.argv[3]) if len(sys.argv) > 3 else 390
prof = tempfile.mkdtemp()
p = subprocess.Popen([driver._browser(), '--headless=new', '--disable-gpu', '--remote-debugging-port=9333', '--remote-allow-origins=*',
                      f'--user-data-dir={prof}', 'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen('http://127.0.0.1:9333/json')); break
        except Exception: time.sleep(0.3)
    ws = websocket.create_connection([t for t in tabs if t['type'] == 'page'][0]['webSocketDebuggerUrl'], timeout=120)
    n = [0]
    def call(m, **params):
        n[0] += 1; ws.send(json.dumps({'id': n[0], 'method': m, 'params': params}))
        while True:
            r = json.loads(ws.recv())
            if r.get('id') == n[0]: return r.get('result', {})
    call('Emulation.setDeviceMetricsOverride', width=w, height=844, deviceScaleFactor=1, mobile=True)
    call('Page.enable'); call('Page.navigate', url=url)
    js = sys.argv[4] if len(sys.argv) > 4 else ''
    for _ in range(90):
        time.sleep(1)
        r = call('Runtime.evaluate', expression="!!document.querySelector('.bk-plan')", returnByValue=True)
        if r['result'].get('value'): break
    time.sleep(2)
    if js: call('Runtime.evaluate', expression=js); time.sleep(1)
    m = call('Runtime.evaluate', returnByValue=True, expression="""(()=>{const d=document.documentElement;
      const wide=[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.right>innerWidth+1&&r.width>0&&getComputedStyle(e).position!=='fixed'}).slice(0,8).map(e=>e.className||e.tagName);
      return {inner:innerWidth, scrollW:d.scrollWidth, overflowing:wide}})()""")
    print(m['result']['value'])
    img = call('Page.captureScreenshot', format='png')
    open(out, 'wb').write(base64.b64decode(img['data']))
finally:
    p.terminate()
