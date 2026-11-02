"""Pure quaternion helpers, XYZW; no device access or physical-axis assertion."""
import math


def compact_quaternion(xyz):
    if len(xyz)!=3 or not all(math.isfinite(x) for x in xyz):return None
    norm=sum(x*x for x in xyz)
    if norm>1.0001:return None
    q=tuple(xyz)+(math.sqrt(max(0.,1.-norm)),)
    length=math.sqrt(sum(x*x for x in q))
    return tuple(x/length for x in q)


def conjugate(q):return (-q[0],-q[1],-q[2],q[3])


def multiply(a,b):
    x,y,z,w=a;X,Y,Z,W=b
    return (w*X+x*W+y*Z-z*Y,w*Y-x*Z+y*W+z*X,
            w*Z+x*Y-y*X+z*W,w*W-x*X-y*Y-z*Z)


def rotation_vector(q):
    if q[3]<0:q=tuple(-x for x in q)
    length=math.sqrt(sum(x*x for x in q[:3]))
    if length<1e-12:return (0.,0.,0.)
    factor=2*math.atan2(length,max(0.,q[3]))/length
    return tuple(x*factor for x in q[:3])


def pointing_angles(reference_inverse,q):
    # Pointing ray is body+Y: same small-angle axes as prior Z→X, X→−Y.
    # R(conj(reference)*q) * (0,1,0), standard Hamilton active rotation.
    x,y,z,w=multiply(reference_inverse,q)
    forward=(2*(x*y-w*z),1-2*(x*x+z*z),2*(y*z+w*x))
    horizontal=math.hypot(forward[0],forward[1])
    if horizontal<.05:return None  # Heading undefined near the vertical pole.
    return (math.atan2(forward[0],forward[1]),
            -math.atan2(forward[2],horizontal))


def shortest_angle(delta):return (delta+math.pi)%(2*math.pi)-math.pi


class PoseRateAgreement:
    """Bounded pairwise moments only; never retains/exports a motion time series."""
    def __init__(self):
        self.previous=None;self.n=0;self.skipped=0
        self.sx=[0.]*3;self.sy=[0.]*3;self.xx=[0.]*3;self.yy=[0.]*3
        self.xy=[[0.]*3 for _ in range(3)]

    def break_link(self):self.previous=None

    def feed(self,now,q,rate):
        prior=self.previous;self.previous=(now,q)
        if prior is None:return
        dt=now-prior[0]
        if not .005<=dt<=.06:self.skipped+=1;return
        vector=rotation_vector(multiply(conjugate(prior[1]),q))
        # Exclude undefined/discontinuous pairs, don't clamp or emit them.
        if math.sqrt(sum(v*v for v in vector))>.3:self.skipped+=1;return
        derivative=[v/dt for v in vector]
        self.n+=1
        for i in range(3):
            self.sx[i]+=rate[i];self.sy[i]+=derivative[i]
            self.xx[i]+=rate[i]*rate[i];self.yy[i]+=derivative[i]*derivative[i]
            for j in range(3):self.xy[i][j]+=rate[i]*derivative[j]

    def summary(self):
        corr=[[None]*3 for _ in range(3)];slopes=[[None]*3 for _ in range(3)]
        if self.n>2:
            for i in range(3):
                vx=max(0.,self.xx[i]-self.sx[i]*self.sx[i]/self.n)
                for j in range(3):
                    vy=max(0.,self.yy[j]-self.sy[j]*self.sy[j]/self.n)
                    cov=self.xy[i][j]-self.sx[i]*self.sy[j]/self.n
                    if vx>1e-9 and vy>1e-9:
                        corr[i][j]=max(-1.,min(1.,cov/math.sqrt(vx*vy)))
                        slopes[i][j]=cov/vx
        return {'pairs':self.n,'skippedPairs':self.skipped,'rateToBodyPoseCorrelation':corr,
                'rateToBodyPoseSlope':slopes,'matrixRows':'compactB XYZ',
                'matrixColumns':'conj(previousQ)*currentQ body rotation XYZ per host second',
                'physicalAxesValidated':False,'sensorTimestampsAvailable':False,'timeSeriesExported':False}
