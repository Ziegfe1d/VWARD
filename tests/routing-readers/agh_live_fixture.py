"""Loopback AGH fixture: the real curl process speaks HTTP; no router/provider access."""
import http.server
import json
import shutil
import threading
from fixture import ROOT
from live_fixture import LiveFixture

CURL=shutil.which('curl')
JQ=shutil.which('jq')
assert CURL and JQ,'installed HTTP fixture requires actual curl and jq'

class AghLiveFixture(LiveFixture):
    def __init__(self):
        super().__init__()
        self.agh=self.p/'actual-agh.json'
        self.agh.write_text(json.dumps({'upstream_dns':['9.9.9.9'],'upstream_dns_file':'','protection_enabled':True}))
        self.http_calls=[]
        self.pause=None;self.entered=threading.Event();self.resume=threading.Event();self.lost=False
        outer=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                outer.http_calls.append(('GET',self.path))
                if self.path!='/control/dns_info':self.send_error(404);return
                data=outer.agh.read_bytes()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
                self.wfile.write(data)
            def do_POST(self):
                outer.http_calls.append(('POST',self.path))
                if self.path!='/control/dns_config':self.send_error(404);return
                request=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
                if set(request)!={'upstream_dns'} or not isinstance(request['upstream_dns'],list):self.send_error(400);return
                if outer.pause=='before':outer.entered.set();outer.resume.wait(12)
                data=json.loads(outer.agh.read_text());data.update(request);outer.agh.write_text(json.dumps(data))
                if outer.pause=='after':outer.entered.set();outer.resume.wait(12)
                if outer.lost:self.close_connection=True;return
                self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'{}')
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        config=self.prefix/'opt/etc/AdGuardHome';config.mkdir()
        (config/'AdGuardHome.yaml').write_text('# loopback fixture only\n')
        share=self.prefix/'opt/share/vward/ads-privacy-guard';share.mkdir(parents=True)
        helper=share/'vward-ads-privacy-common.sh'
        shutil.copy2(ROOT/'components/ads-privacy-guard/lib/vward-ads-privacy-common.sh',helper)
        helper.chmod(0o644) # Actual signed package-map mode, independent of checkout mode.
        self.env|={'AGH_API_BASE':f'http://127.0.0.1:{self.server.server_port}/control',
                   'VWARD_ADS_CURL':CURL,'VWARD_ADS_JQ':JQ,
                   'VWARD_ADS_ETC':str(self.etc/'ads-privacy-guard'),
                   'VWARD_ADS_AGH_AUTH_FILE':str(self.etc/'ads-privacy-guard/agh-api.auth'),
                   'VWARD_ADS_DEVICE_CONFIG':str(self.etc/'device.conf')}
        self.configure_dns('agh')
        for name in ('policies','upstreams','context','bindings'):
            shutil.copy2(self.decision/(name+'.tsv'),self.live/'decision'/(name+'.tsv'))
    def close(self):
        if hasattr(self,'server'):
            self.resume.set();self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
        super().close()
