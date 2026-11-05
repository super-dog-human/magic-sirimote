import math
import struct
import unittest
from rolling_receiver import RollingReceiver
from pose_math import multiply, pointing_angles
from test_navigation_mode import Outputs


def frame(yaw=0., roll=0.):
    # Rotate the heading in the original screen plane while rolling around
    # the remote's forward (+Y) axis. Roll must not redefine that plane.
    q=multiply((0.,0.,math.sin(yaw/2),math.cos(yaw/2)),
               (0.,math.sin(roll/2),0.,math.cos(roll/2)))
    return b'\xfc\x04\x00'+struct.pack('<3f',*q[:3])+b'\0'*6


class CursorReferenceContinuityTests(unittest.TestCase):
    def setUp(self):
        self.now=0.;self.outputs=Outputs()
        self.remote=RollingReceiver(self.outputs,continuity=lambda:True,
            mode_verified=lambda:True,clock=lambda:self.now,seconds=31)
        self.remote.start()
        for _ in range(30):self.feed()
        self.reference=self.remote.receiver.router.pose.reference_inverse
        self.assertIsNotNone(self.reference)

    def feed(self,yaw=0.,roll=0.):
        self.now+=.01
        self.remote.feed_raw(1,frame(yaw,roll));self.remote.tick()

    def test_timer_rollover_while_tilted_keeps_screen_axes(self):
        prior=self.remote.receiver
        self.now=29.01
        self.feed(roll=math.pi/3)
        self.assertEqual(self.remote.rotations,1)
        for _ in range(30):self.feed(roll=math.pi/3)
        pose=self.remote.receiver.router.pose
        self.assertEqual(pose.reference_inverse,self.reference)
        self.assertIsNot(self.remote.receiver,prior)
        self.assertTrue(prior.closed)
        # Horizontal heading remains horizontal instead of acquiring a large
        # vertical component from the tilted rollover baseline.
        q=multiply((0.,0.,math.sin(.1),math.cos(.1)),
                   (0.,math.sin(math.pi/6),0.,math.cos(math.pi/6)))
        x,y=pointing_angles(pose.reference_inverse,q)
        self.assertAlmostEqual(x,-.2,places=5)
        self.assertAlmostEqual(y,0.,places=5)

    def test_screen_pause_preserves_basis_without_replaying_movement(self):
        prior=self.remote.receiver;self.remote.pause_output()
        count=len(self.outputs.events)
        self.now+=100;self.remote.resume_output()
        self.assertEqual(self.remote.receiver.router.pose.reference_inverse,self.reference)
        self.assertIsNot(self.remote.receiver,prior)
        for _ in range(30):self.feed(.3,math.pi/3)
        self.assertEqual(len(self.outputs.events),count)
        self.assertFalse(self.remote.receiver.router.pose.closed)

    def test_action_budget_rollover_keeps_basis_and_resets_budget(self):
        prior=self.remote.receiver
        prior.router.press.core.stats['pressAttempts']=self.remote.policy.max_actions-1
        self.feed(roll=math.pi/3)
        self.assertEqual(self.remote.rotations,1)
        self.assertEqual(self.remote.receiver.router.pose.reference_inverse,self.reference)
        self.assertEqual(self.remote.receiver.router.press.core.stats['pressAttempts'],0)

    def test_new_sensor_session_still_needs_its_own_reference(self):
        self.remote.stop()
        new=RollingReceiver(Outputs(),continuity=lambda:True,mode_verified=lambda:True,
                            clock=lambda:self.now,seconds=31)
        new.start()
        self.assertIsNone(new.receiver.router.pose.reference_inverse)

    def test_partial_calibration_is_not_carried_across_pause(self):
        fresh=RollingReceiver(Outputs(),continuity=lambda:True,mode_verified=lambda:True,
                              clock=lambda:self.now,seconds=31)
        fresh.start();fresh.feed_raw(1,frame(roll=math.pi/3))
        self.assertIsNone(fresh.receiver.router.pose.reference_inverse)
        fresh.pause_output();fresh.resume_output()
        self.assertIsNone(fresh.receiver.router.pose.reference_inverse)
        self.assertEqual(fresh.receiver.router.pose.samples,0)

if __name__=='__main__':unittest.main()
