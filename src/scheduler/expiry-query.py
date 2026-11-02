import json,time,urllib.request,urllib.parse,re,stat,os
from pathlib import Path
out={'operation':'read-current-devmode-session','timeEpochMs':int(time.time()*1000),'readOnly':True,'credentialSavedOrPrinted':False,'officialHost':'developer.lge.com'}
try:
 p=Path('/var/luna/preferences/devmode_enabled')
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode) or not 1<=st.st_size<=4096:raise ValueError('invalid session marker')
  token=os.read(fd,4097).decode('ascii').strip()
 finally:os.close(fd)
 if not token or any(ord(c)<33 or ord(c)>126 for c in token):raise ValueError('invalid token format')
 url='https://developer.lge.com/secure/CheckDevModeSession.dev?sessionToken='+urllib.parse.quote(token,safe='')
 request=urllib.request.Request(url,headers={'User-Agent':'webOS-SiriRemote-session-check/1'})
 class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*args,**kwargs):return None
 opener=urllib.request.build_opener(NoRedirect)
 with opener.open(request,timeout=8) as response:
  raw=response.read(8193);out['httpStatus']=response.status
 del url,token,request
 if len(raw)>8192:raise ValueError('reply too large')
 value=json.loads(raw);result=value.get('result');message=value.get('errorMsg')
 out['serverResult']=result if result in ('success','fail') else 'unrecognized'
 if result=='success' and type(message) is str and re.fullmatch(r'[0-9]{1,4}(:[0-5][0-9]){2}',message):
  h,m,s=map(int,message.split(':'));out['remainingSeconds']=h*3600+m*60+s;out['remainingDisplay']=message;out['timeVerified']=True
 else:out['timeVerified']=False
except Exception as e:
 out['timeVerified']=False;out['errorType']=type(e).__name__
print(json.dumps(out))
