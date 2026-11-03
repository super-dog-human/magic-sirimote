"""Candidate: press-time position -> latched direction/center click.

No native keys, cursor, device/network operations or IR. `emit(action,
down)` is an injected semantic sink. A future native adapter must route
center only to the existing BTN_LEFT path and directions only to the
reviewed key path; never also run the old all-positions TouchClick output on
the same reports.
"""
import math
import struct
import time
from touch_coordinates import decode_touch
from touch_click import TouchClick, button_mask


class SurfaceRegions:
    """Explicitly calibrated raw bounds; no zero-centered geometry guess."""
    def __init__(self, *, x_min, x_max, y_min, y_max, center_fraction=.65):
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (x_min,x_max,y_min,y_max)):
            raise ValueError('Finite calibrated bounds required')
        if not (-2048<=x_min<x_max<=2047 and -2048<=y_min<y_max<=2047):
            raise ValueError('Ordered signed-12-bit calibration required')
        if type(center_fraction) not in (int,float) or not math.isfinite(center_fraction) or not .5<=center_fraction<=.8:
            raise ValueError('Broad center width: 50–80 percent of each axis')
        self.x_min,self.x_max,self.y_min,self.y_max=x_min,x_max,y_min,y_max
        self.center_fraction=center_fraction

    def classify(self,x,y):
        return self.classify_with_reason(x,y)[0]

    def classify_with_reason(self,x,y):
        # Diagnostic reasons do not widen bounds or change a classification.
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (x,y)):return None,'nonfinite-position'
        if not(self.x_min<=x<=self.x_max and self.y_min<=y<=self.y_max):return None,'outside-calibrated-bounds'
        x=2*(x-self.x_min)/(self.x_max-self.x_min)-1
        y=2*(y-self.y_min)/(self.y_max-self.y_min)-1
        if max(abs(x),abs(y))<=self.center_fraction:return 'center',None
        # Exactly ambiguous outer diagonal boundaries are not guessed.
        if math.isclose(abs(x),abs(y),abs_tol=1e-9):return None,'ambiguous-outer-diagonal'
        if abs(x)>abs(y):return ('right' if x>0 else 'left'),None
        return ('up' if y>0 else 'down'),None


class PositionPress:
    CACHE_SECONDS=.05

    def __init__(self,emit,regions,*,clock=time.monotonic,max_seconds=30,max_presses=16):
        if not isinstance(regions,SurfaceRegions):raise ValueError('Explicit calibrated surface required')
        if type(max_seconds) not in (int,float) or not math.isfinite(max_seconds) or not 0<max_seconds<=30:
            raise ValueError('At most thirty seconds')
        self.emit,self.regions,self.clock=emit,regions,clock
        self.cache=self.pending=self.active=None
        self.pending_reason='no-recent-position'
        self.last_rejection_reason=None
        self.rejection_reasons={}
        self.events=self.rejected=0
        self.presses=dict.fromkeys(('center','up','down','left','right'),0)
        self.core=TouchClick(self._translate,max_seconds=max_seconds,max_clicks=max_presses,clock=clock)

    def _translate(self,packet):
        if len(packet)!=32:raise ValueError('Unexpected click-core frame')
        event=struct.unpack('=iiHHi',packet[:16]);syn=struct.unpack('=iiHHi',packet[16:])
        if event[:4]!=(0,0,1,0x110) or event[4] not in (0,1) or syn!=(0,0,0,0,0):
            raise ValueError('Only reviewed physical-press transitions accepted')
        if event[4]:
            self.active=self.pending
            if self.active is None:
                self.rejected+=1
                reason=self.pending_reason or 'no-recent-position'
                self.last_rejection_reason=reason
                self.rejection_reasons[reason]=self.rejection_reasons.get(reason,0)+1
            else:
                self.emit(self.active,True)
                self.events+=1;self.presses[self.active]+=1
        elif self.active is not None:
            self.emit(self.active,False)
            self.events+=1;self.active=None
        return len(packet)

    def bind(self,generation):
        accepted=self.core.bind(generation)
        if accepted:self.cache=self.pending=self.active=None
        return accepted

    def unbind(self,generation):
        accepted=self.core.unbind(generation)
        if accepted:self.cache=self.pending=None
        return accepted

    def stop(self,reason='requested'):
        try:self.core.stop(reason)
        finally:self.cache=self.pending=None

    def tick(self):return self.core.tick()

    def feed(self,generation,value):
        # Stale-link input must not contaminate the next valid press location.
        if type(generation) is not int or generation!=self.core.generation:return False
        now=self.clock();mask=button_mask(value);decoded=decode_touch(value)
        self.pending=None
        self.pending_reason='unsupported-position-report'
        if decoded is not None:
            if len(decoded['fingers'])==1 and decoded['fingers'][0]['state'] in (3,4) and mask in (0,0x80):
                f=decoded['fingers'][0];zone,self.pending_reason=self.regions.classify_with_reason(f['x'],f['y'])
                self.pending=zone
                self.cache=(now,zone) if mask==0 and zone is not None else None
            else:
                self.cache=None
                self.pending_reason=('multiple-contacts' if len(decoded['fingers'])!=1 else
                                     'inactive-contact' if decoded['fingers'][0]['state'] not in (3,4) else
                                     'other-buttons')
        elif type(value) in (bytes,bytearray) and len(value)==2 and value[0]==0 and mask in (0,0x80):
            # A button-only press may use the immediately preceding touch,
            # never a stale position, lift, another link or another button.
            if self.cache is not None and 0<=now-self.cache[0]<=self.CACHE_SECONDS:
                self.pending=self.cache[1]
                self.pending_reason=None
            else:
                self.pending_reason='expired-position-cache' if self.cache is not None else 'no-recent-position'
                self.cache=None
        else:self.cache=None
        before=self.events
        self.core.feed(generation,value)
        return self.events!=before

    def summary(self):
        return {'presses':dict(self.presses),'semanticEvents':self.events,'rejectedPositionPresses':self.rejected,
                'positionRejectionReasons':dict(self.rejection_reasons),
                'activeAction':self.active,'safety':self.core.summary(),
                'centerFraction':self.regions.center_fraction,'cursorEvents':0,'liveKeyWrites':0,
                'deviceOrNetworkOpens':0,'policy':'position latched at physical press; no touch/swipe action'}
